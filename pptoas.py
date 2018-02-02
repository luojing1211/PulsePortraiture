#!/usr/bin/env python

########
#pptoas#
########

#pptoas is a command-line program used to simultaneously fit for phases (TOAs),
#    and dispersion measures (DMs).  Full-functionality is obtained when using
#    pptoas within an interactive python environment.

#Written by Timothy T. Pennucci (TTP; tim.pennucci@nanograv.org).
#Contributions by Scott M. Ransom (SMR) and Paul B. Demorest (PBD).

from pptoaslib import *

#cfitsio defines a maximum number of files (NMAXFILES) that can be opened in
#the header file fitsio2.h.  Without calling unload() with PSRCHIVE, which
#touches the archive, I am not sure how to close the files.  So, to avoid the
#loop crashing, set a maximum number of archives for pptoas.  Modern machines
#should be able to handle almost 1000.
max_nfile = 999

#See F0_fact in pplib.py
if F0_fact:
    rm_baseline = True
else:
    rm_baseline = False

class TOA:

    """
    TOA class bundles common TOA attributes together with useful functions.
    """

    def __init__(self, archive, frequency, MJD, TOA_error, telescope, DM=None,
            DM_error=None, flags={}):
        """
        Form a TOA.

        archive is the string name of the TOA's archive.
        frequency is the reference frequency [MHz] of the TOA.
        MJD is a PSRCHIVE MJD object (the TOA, topocentric).
        TOA_error is the TOA uncertainty [us].
        telescope is the string designating the observatory.
        DM is the full DM [cm**-3 pc] associated with the TOA.
        DM_error is the DM uncertainty [cm**-3 pc].
        flags is a dictionary of arbitrary TOA flags
            (e.g. {'subint':0, 'be':'GUPPI'}).
        """
        self.archive = archive
        self.frequency = frequency
        self.MJD = MJD
        self.TOA_error = TOA_error
        self.telescope = telescope
        self.DM = DM
        self.DM_error = DM_error
        self.flags = flags
        for flag in flags.keys():
            exec('self.%s = flags["%s"]'%(flag, flag))

    def write_TOA(self, format="tempo2", outfile=None):
        """
        Print a formatted TOA to standard output or to file.

        format is one of 'tempo2', ... others coming ...
        outfile is the output file name; if None, will print to standard
            output.
        """
        write_TOAs(self, format=format, outfile=outfile, append=True)

    def convert_TOA(self, new_frequency, covariance):
        """
        To do...
        """
        print "Convert TOA to new reference frequency, with new error, \
            if covariance provided."

class GetTOAs:

    """
    GetTOAs is a class with methods to measure TOAs and DMs from data.
    """

    def __init__(self, datafiles, modelfile, quiet=False):
        """
        Unpack all of the data and set initial attributes.

        datafiles is either a single PSRCHIVE file name, or a name of a
            metafile containing a list of archive names.
        modelfile is a ppgauss or ppinterp model file.  modelfile can also be
            an arbitrary PSRCHIVE archive, although this feature is
            *not*quite*implemented*yet*.
        quiet=True suppresses output.
        """
        if file_is_type(datafiles, "ASCII"):
            self.datafiles = [datafile[:-1] for datafile in \
                    open(datafiles, "r").readlines()]
        else:
            self.datafiles = [datafiles]
        if len(self.datafiles) > max_nfile:
            print "Too many archives.  See/change max_nfile(=%d) in pptoas.py."%max_nfile
            sys.exit()
        self.is_FITS_model = file_is_type(modelfile, "FITS")
        self.modelfile = modelfile  # the model file in use
        self.obs = []  # observatories from the observations
        self.doppler_fs = []  # PSRCHIVE Doppler factors from Earth's motion
        self.nu0s = []  # PSRCHIVE center frequency
        self.nu_fits = []  # reference frequencies for the fit
        self.nu_refs = []  # reference frequencies for the output
        self.ok_isubs = [] # list of indices for the good subintegrations
        self.epochs = []  # PSRCHIVE midpoints of the subintegrations
        self.MJDs = []  # same as epochs, in days
        self.Ps = []  # PSRCHIVE spin period at each epoch
        self.phis = []  # the fitted phase shifts / phi parameter
        self.phi_errs = [] # their uncertainties
        self.TOAs = []  # the fitted TOA
        self.TOA_errs = []  # their uncertainties
        self.DM0s = []  # the stored PSRCHIVE header DMs
        self.DMs = []  # the fitted DMs (may include the Doppler correction)
        self.DM_errs = []  # their uncertainties
        self.DeltaDM_means = []  # fitted single mean DM-DM0
        self.DeltaDM_errs = []  # their uncertainties
        self.taus = []  # fitted scattering timescales
        self.tau_errs = []  # their uncertainties
        self.alphas = []  # fitted scattering indices
        self.alpha_errs = []  # their uncertainties
        self.GMs = []  # fitted "GM" parameter, from delays that go as nu**-4
        self.GM_errs = []  # their uncertainties
        self.scales = []  # fitted per-channel scaling parameters
        self.scale_errs = []  # their uncertainties
        self.covariances = []  # full covariance matrices
        self.red_chi2s = []  # reduced chi2 values of the fit
        self.nfevals = []  # number of likelihood function evaluations
        self.rcs = []  # return codes from the fit
        self.fit_durations = []  # durations of the fit
        self.order = []  # order that datafiles are examined (deprecated)
        self.TOA_list = []  # complete, single list of TOAs
        self.quiet = quiet  # be quiet?

    def get_TOAs(self, datafile=None, nu_refs=None, DM0=None,
            bary_DM=True, fit_DM=True, fit_GM=False, fit_scat=False,
            log10_tau=True, fix_alpha=False, print_phase=False,
            method='trust-ncg', bounds=None, nu_fits=None, show_plot=False,
            addtnl_toa_flags={}, quiet=None):
        """
        Measure TOAs from wideband data accounting for numerous ISM effects.

        datafile defaults to self.datafiles, otherwise it is a single
            PSRCHIVE archive name
        nu_refs is a tuple containing two output reference frequencies [MHz],
            one for the TOAs, and the other for the scattering timescales;
            defaults to the zero-covariance frequency between the TOA and DM,
            and the scattering timescale and index, respectively.
        DM0 is the baseline dispersion measure [cm**-3 pc]; defaults to what is
            stored in each datafile.
        bary_DM=True corrects the measured DMs (and GMs) based on the Doppler
            motion of the observatory with respect to the solar system
            barycenter.
        fit_DM=False will not fit for DM; if this is the case, you might want
            to set bary_DM to False.
        fit_GM=True will fit for a parameter ('GM') characterizing a delay term
            for each TOA that scales as nu**-4.  Will be highly covariant with
            DM.
        fit_scat=True will fit the scattering timescale and index for each TOA.
        log10_tau=True does the scattering fit with log10(scattering timescale)
            as the parameter.
        fix_alpha=True will hold the scattering index fixed, in the case that
            fit_scat==True.  alpha is fixed to the value specified in the
            .gmodel file, or scattering_alpha in pplib.py if no .gmodel is
            provided.
        print_phase=True will print the fitted parameter phi on the TOA line
            with the flag -phs.
        method is the scipy.optimize.minimize method; currently can be 'TNC',
            'Newton-CG', or 'trust-cng', which are all Newton
            Conjugate-Gradient algorithms.
        bounds is a list of five 2-tuples, giving the lower and upper bounds on
            the phase, dispersion measure, GM, tau, and alpha parameters,
            respectively.  NB: this is only used if method=='TNC'.
        nu_fits is a tuple (deprecated), analogous to nu_ref, where these
            reference frequencies [MHz] are used in the fit; defaults to a
            guess at the zero-covariance frequency based on signal-to-noise
            ratios.
        show_plot=True will show a plot of the fitted model, data, and
            residuals at the end of the fitting.
        addtnl_toa_flags are pairs making up TOA flags to be written uniformly
            to all tempo2-formatted TOAs. e.g. ('pta','NANOGrav','version',0.1)
        quiet=True suppresses output.
        """
        if quiet is None: quiet = self.quiet
        already_warned = False
        warning_message = \
                "You are using an experimental functionality of pptoas!"
        self.nfit = 1
        self.nchan_min = 1
        if fit_DM:
            self.nfit += 1
            self.nchan_min += 1
        if fit_GM:
            self.nfit += 1
            self.nchan_min += 1
        if fit_scat: self.nfit += 2
        if fix_alpha: self.nfit -= 1
        self.fit_phi = True
        self.fit_DM = fit_DM
        self.fit_GM = fit_GM
        self.fit_tau = self.fit_alpha = fit_scat
        if fit_scat: self.fit_alpha = not fix_alpha
        if self.fit_alpha: self.nchan_min = max(2, self.nchan_min)
        self.fit_flags = [int(self.fit_phi), int(self.fit_DM),
                int(self.fit_GM), int(self.fit_tau), int(self.fit_alpha)]
        self.log10_tau = log10_tau
        if not fit_scat:
            self.log10_tau = log10_tau = False
        nu_ref_tuple = nu_refs
        nu_fit_tuple = nu_fits
        self.DM0 = DM0
        self.bary_DM = bary_DM
        self.ok_idatafiles = []
        start = time.time()
        tot_duration = 0.0
        if datafile is None:
            datafiles = self.datafiles
        else:
            datafiles = [datafile]
        for iarch, datafile in enumerate(datafiles):
            fit_duration = 0.0
            #Load data
            try:
                data = load_data(datafile, dedisperse=False,
                        dededisperse=False, tscrunch=False, pscrunch=True,
                        fscrunch=False, rm_baseline=rm_baseline,
                        flux_prof=False, refresh_arch=False, return_arch=False,
                        quiet=quiet)
                if not len(data.ok_isubs):
                    if not quiet:
                        print "No subints to fit for %s.  Skipping it."%\
                                datafile
                    continue
                else: self.ok_idatafiles.append(iarch)
            except RuntimeError:
                if not quiet:
                    print "Cannot load_data(%s).  Skipping it."%datafile
                continue
            #Unpack the data dictionary into the local namespace; see load_data
            #for dictionary keys.
            for key in data.keys():
                exec(key + " = data['" + key + "']")
            if source is None: source = "noname"
            #Observation info
            obs = DataBunch(telescope=telescope, backend=backend,
                    frontend=frontend, tempo_code=tempo_code)
            doppler_fs = np.ones(nsub, dtype=np.float64)
            nu_fits = list(np.zeros([nsub, 3], dtype=np.float64))
            nu_refs = list(np.zeros([nsub, 3], dtype=np.float64))
            phis = np.zeros(nsub, dtype=np.double)
            phi_errs = np.zeros(nsub, dtype=np.double)
            TOAs = np.zeros(nsub, dtype="object")
            TOA_errs = np.zeros(nsub, dtype="object")
            DMs = np.zeros(nsub, dtype=np.float64)
            DM_errs = np.zeros(nsub, dtype=np.float64)
            GMs = np.zeros(nsub, dtype=np.float64)
            GM_errs = np.zeros(nsub, dtype=np.float64)
            taus = np.zeros(nsub, dtype=np.float64)
            tau_errs = np.zeros(nsub, dtype=np.float64)
            alphas = np.zeros(nsub, dtype=np.float64)
            alpha_errs = np.zeros(nsub, dtype=np.float64)
            nfevals = np.zeros(nsub, dtype="int")
            rcs = np.zeros(nsub, dtype="int")
            scales = np.zeros([nsub, nchan], dtype=np.float64)
            scale_errs = np.zeros([nsub, nchan], dtype=np.float64)
            red_chi2s = np.zeros(nsub, dtype=np.float64)
            covariances = np.zeros([nsub, self.nfit, self.nfit],
                    dtype=np.float64)
            #PSRCHIVE epochs are *midpoint* of the integration
            MJDs = np.array([epochs[isub].in_days() \
                    for isub in xrange(nsub)], dtype=np.double)
            DM_stored = DM # = arch.get_dispersion_measure()
            if self.DM0 is None:
                DM0 = DM_stored
            else:
                DM0 = self.DM0
            if not fit_DM:
                bounds[1] = (DM0, DM0)
            if self.is_FITS_model:
                if not already_warned:
                    print warning_message
                    already_warned = True
                model_data = load_data(self.modelfile, dedisperse=False,
                    dededisperse=False, tscrunch=True, pscrunch=True,
                    fscrunch=False, rm_baseline=True, flux_prof=False,
                    #fscrunch=False, rm_baseline=False, flux_prof=False,
                    refresh_arch=False, return_arch=False, quiet=True)
                model = (model_data.masks * model_data.subints)[0,0]
                if model_data.nchan == 1:
                    model = np.tile(model[0], len(freqs[isub])).reshape(
                            len(freqs[isub]), nbin)
                    print model.shape
            if not quiet:
                print "\nEach of the %d TOAs is approximately %.2f s"%(
                        len(ok_isubs), integration_length / nsub)
                print "Doing Fourier-domain least-squares fit..."
            itoa = 1
            for isub in ok_isubs:
                id = datafile + "_%d"%isub
                epoch = epochs[isub]
                MJD = MJDs[isub]
                P = Ps[isub]
                if not self.is_FITS_model:
                    #Read model
                    try:
                        if not fit_scat:
                            self.model_name, self.ngauss, model = read_model(
                                    self.modelfile, phases, freqs[isub],
                                    Ps[isub],
                                    quiet=bool(quiet+(itoa-1)))
                        else:
                            if not already_warned:
                                print warning_message
                                already_warned = True
                            self.model_name, self.ngauss, full_model = \
                                    read_model(self.modelfile, phases,
                                            freqs[isub], Ps[isub],
                                            quiet=bool(quiet+(itoa-1)))
                            self.model_name, self.model_code, \
                                    self.model_nu_ref, self.ngauss, \
                                    self.gparams, fit_flags, self.alpha, \
                                    fit_alpha = read_model(self.modelfile,
                                            quiet=bool(quiet+(itoa-1)))
                            unscat_params = np.copy(self.gparams)
                            unscat_params[1] = 0.0
                            model = unscat_model = gen_gaussian_portrait(
                                    self.model_code, unscat_params, 0.0,
                                    phases, freqs[isub], self.model_nu_ref)
                    except UnboundLocalError:
                        self.model_name, model = read_interp_model(
                                self.modelfile, freqs[isub], nbin,
                                quiet=True) #bool(quiet+(itoa-1)))
                #else:
                ##THESE FREQUENCIES WILL BE OFF IF AVERAGED CHANNELS##
                #    print model_data.freqs[0, ok_ichans[isub]] - \
                #            freqs[isub,ok_ichans[isub]]
                freqsx = freqs[isub,ok_ichans[isub]]
                portx = subints[isub,0,ok_ichans[isub]]
                modelx = model[ok_ichans[isub]]
                SNRsx = SNRs[isub,0,ok_ichans[isub]]
                #NB: Time-domain uncertainties below
                errs = noise_stds[isub,0,ok_ichans[isub]]
                #nu_fit is the reference frequency for parameters in the fit
                nu_mean = freqsx.mean()
                if nu_fit_tuple is None:
                    #NB: the subints are dedispersed at different nu_fit.
                    nu_fit = guess_fit_freq(freqsx, SNRsx)
                    nu_fit_DM = nu_fit_GM = nu_fit_tau = nu_fit
                else:
                    nu_fit_DM = nu_fit_GM = nu_fit_tuple[0]
                    nu_fit_tau = nu_fit_tuple[1]
                nu_fits[isub] = [nu_fit_DM, nu_fit_GM, nu_fit_tau]
                if nu_ref_tuple is None:
                    nu_ref = None
                    nu_ref_DM = nu_ref_GM = nu_ref_tau = nu_ref
                else:
                    nu_ref_DM = nu_ref_GM = nu_ref_tuple[0]
                    nu_ref_tau = nu_ref_tuple[1]
                nu_refs[isub] = [nu_ref_DM, nu_ref_GM, nu_ref_tau]

                #################
                #INITIAL GUESSES#
                #################
                DM_guess = DM_stored
                rot_port = rotate_data(portx, 0.0, DM_guess, P, freqsx,
                        nu_mean)
                rot_prof = rot_port.mean(axis=0)
                GM_guess = 0.0
                tau_guess = 0.0
                alpha_guess = 0.0
                if fit_scat:
                    if hasattr(self, 'alpha'): alpha_guess = self.alpha
                    else: alpha_guess = scattering_alpha
                    if hasattr(self, 'gparams'):
                        tau_guess = (self.gparams[1] / P) * \
                                (nu_fit_tau/self.model_nu_ref)**alpha_guess
                    else:
                        #tau_guess = guess_tau(rot_prof, modelx.mean(axis=0))
                        tau_guess = 0.0
                    model_prof_scat = np.fft.irfft(scattering_portrait_FT(
                        np.array([scattering_times(tau_guess, alpha_guess,
                            nu_mean, nu_mean)]), nbin)[0] * np.fft.rfft(
                                modelx.mean(axis=0)))
                    phi_guess = fit_phase_shift(rot_prof,
                            model_prof_scat, Ns=100).phase
                    if self.log10_tau:
                        if tau_guess == 0.0: tau_guess = nbin**-1
                        tau_guess = np.log10(tau_guess)
                else:
                    #NB: Ns should be larger than nbin for very low S/N data,
                    #especially in the case of noisy models...
                    phi_guess = fit_phase_shift(rot_prof, modelx.mean(axis=0),
                            Ns=100).phase
                phi_guess = phase_transform(phi_guess, DM_guess, nu_mean,
                        nu_fit_DM, P, mod=True) # why not use nu_fit at first?
                #Need a status bar?
                param_guesses = [phi_guess, DM_guess, GM_guess, tau_guess,
                        alpha_guess]
                if bounds is None and method == 'TNC':
                    phi_bounds = (None, None)
                    DM_bounds = (None, None)
                    GM_bounds = (None, None)
                    if not self.log10_tau: tau_bounds = (0.0, None)
                    else: tau_bounds = (np.log10((10*nbin)**-1), None)
                    alpha_bounds = (-10.0, 10.0)
                    bounds = [phi_bounds, DM_bounds, GM_bounds, tau_bounds,
                            alpha_bounds]

                ####################
                #      THE FIT     #
                ####################
                if not quiet:
                    print "Fitting for TOA #%d"%(itoa)
                if len(freqsx) >= self.nchan_min:
                    results = fit_portrait_full(portx, modelx, param_guesses,
                            P, freqsx, nu_fits[isub], nu_refs[isub], errs,
                            self.fit_flags, bounds, self.log10_tau, option=0,
                            id=id, method=method, quiet=quiet)
                    # Old code
                    #results = fit_portrait(portx, modelx,
                    #        np.array([phi_guess, DM_guess]), P, freqsx,
                    #        nu_fit_DM, nu_ref_DM, errs, bounds=bounds, id=id,
                    #        quiet=quiet)
                    #results.phi = results.phase
                    #results.phi_err = results.phase_err
                    #results.GM = results.GM_err = None
                    #results.tau = results.tau_err = None
                    #results.alpha = results.alpha_err = None
                    #results.covariance_matrix = np.zeros([2,2])
                    #results.nu_DM = results.nu_GM = results.nu_tau = results.nu_ref
                else:  #1-channel hack
                    if not quiet:
                        print "TOA only has %d frequency channel!..."%len(
                                freqsx)
                        print "...using Fourier phase gradient routine to fit phase only..."
                    results = fit_phase_shift(portx[0], modelx[0], errs[0],
                            Ns=nbin)
                    results.phi = results.phase
                    results.phi_err = results.phase_err
                    results.DM = results.DM_err = None
                    results.GM = results.GM_err = None
                    results.tau = results.tau_err = None
                    results.alpha = results.alpha_err = None
                    results.nu_DM, results.nu_GM, results.nu_tau = \
                            [freqsx[0], freqsx[0], freqsx[0]]
                    results.nfeval = 0
                    results.return_code = -2
                    results.scales = np.array([results.scale])
                    results.scale_errs = np.array([results.scale_error])
                    results.covariance_matrix = np.identity(self.nfit)
                fit_duration += results.duration

                ####################
                #  CALCULATE  TOA  #
                ####################
                results.TOA = epoch + pr.MJD(
                        ((results.phi * P) + backend_delay) /
                        (3600 * 24.))
                results.TOA_err = results.phi_err * P * 1e6 # [us]

                ##########################
                #DOPPLER CORRECTION OF DM#
                ##########################
                if self.bary_DM: #Default is True
                    #NB: the 'doppler factor' retrieved from PSRCHIVE seems to
                    #be the inverse of the convention nu_source/nu_observed
                    df = doppler_factors[isub]
                    if len(freqsx) > 1:
                        results.DM *= df  #NB: No longer the *fitted* value!
                        results.GM *= df  #NB: No longer the *fitted* value!
                    doppler_fs[isub] = df
                else:
                    doppler_fs[isub] = 1.0

                #show_portrait(portx)
                nu_refs[isub] = [results.nu_DM, results.nu_GM, results.nu_tau]
                phis[isub] = results.phi
                phi_errs[isub] = results.phi_err
                TOAs[isub] = results.TOA
                TOA_errs[isub] = results.TOA_err
                DMs[isub] = results.DM
                DM_errs[isub] = results.DM_err
                GMs[isub] = results.GM
                GM_errs[isub] = results.GM_err
                taus[isub] = results.tau
                tau_errs[isub] = results.tau_err
                alphas[isub] = results.alpha
                alpha_errs[isub] = results.alpha_err
                nfevals[isub] = results.nfeval
                rcs[isub] = results.return_code
                scales[isub, ok_ichans[isub]] = results.scales
                scale_errs[isub, ok_ichans[isub]] = results.scale_errs
                covariances[isub] = results.covariance_matrix
                red_chi2s[isub] = results.red_chi2
                #Compile useful TOA flags
                toa_flags = {}
                if fit_GM:
                    toa_flags['gm'] = results.GM
                    toa_flags['gm_err'] = results.GM_err
                if fit_scat:
                    if self.log10_tau:
                        toa_flags['scat_time'] = 10**results.tau * P * 1e6#usec
                        toa_flags['log10_scat_time'] = results.tau + \
                                np.log10(P)
                        toa_flags['log10_scat_time_err'] = results.tau_err
                    else:
                        toa_flags['scat_time'] = results.tau * P * 1e6 # usec
                        toa_flags['scat_time_err'] = results.tau_err * P * 1e6
                    toa_flags['scat_ind'] = results.alpha
                    toa_flags['scat_ind_err'] = results.alpha_err
                    toa_flags['scat_ref_freq'] = results.nu_tau
                toa_flags['be'] = backend
                toa_flags['fe'] = frontend
                toa_flags['f'] = frontend + "_" + backend
                toa_flags['nbin'] = nbin
                toa_flags['nch'] = nchan
                toa_flags['nchx'] = len(freqsx)
                toa_flags['bw'] = freqsx.max() - freqsx.min()
                toa_flags['subint'] = isub
                toa_flags['tobs'] = subtimes[isub]
                toa_flags['tmplt'] = self.modelfile
                if nu_ref_DM is not None and self.fit_phi and self.fit_DM:
                    toa_flags['phi_DM_cov'] = results.covariance_matrix[0,1]
                toa_flags['gof'] = results.red_chi2
                if print_phase: toa_flags['phs'] = results.phi
                toa_flags['snr'] = results.snr
                for k,v in addtnl_toa_flags.iteritems():
                    toa_flags[k] = v
                self.TOA_list.append(TOA(datafile, results.nu_DM, results.TOA,
                    results.TOA_err, telescope.lower(), results.DM,
                    results.DM_err, toa_flags))
                itoa += 1

            DeltaDMs = DMs - DM0
            #The below returns the weighted mean and the sum of the weights,
            #but needs to do better in the case of small-error outliers from
            #RFI, etc.  Also, last TOA may mess things up...use median...?
            DeltaDM_mean, DeltaDM_var = np.average(DeltaDMs[ok_isubs],
                    weights=DM_errs[ok_isubs]**-2, returned=True)
            DeltaDM_var = DeltaDM_var**-1
            if len(ok_isubs) > 1:
                #The below multiply by the red. chi-squared to inflate the
                #errors.
                DeltaDM_var *= np.sum(
                        ((DeltaDMs[ok_isubs] - DeltaDM_mean)**2) /
                        (DM_errs[ok_isubs]**2)) / (len(DeltaDMs[ok_isubs]) - 1)
            DeltaDM_err = DeltaDM_var**0.5
            self.order.append(datafile)
            self.obs.append(obs)
            self.doppler_fs.append(doppler_fs)
            self.nu0s.append(nu0)
            self.nu_fits.append(nu_fits)
            self.nu_refs.append(nu_refs)
            self.ok_isubs.append(ok_isubs)
            self.epochs.append(epochs)
            self.MJDs.append(MJDs)
            self.Ps.append(Ps)
            #NB: phis are w.r.t. nu_ref!!!
            self.phis.append(phis)
            self.phi_errs.append(phi_errs)
            #NB: TOAs are w.r.t. nu_ref!!!
            self.TOAs.append(TOAs)
            self.TOA_errs.append(TOA_errs)
            #NB: DMs are Doppler corrected, if bary_DM is set!!!
            self.DM0s.append(DM0)
            self.DMs.append(DMs)
            self.DM_errs.append(DM_errs)
            self.DeltaDM_means.append(DeltaDM_mean)
            self.DeltaDM_errs.append(DeltaDM_err)
            self.GMs.append(GMs)
            self.GM_errs.append(GM_errs)
            self.taus.append(taus)
            self.tau_errs.append(tau_errs)
            self.alphas.append(alphas)
            self.alpha_errs.append(alpha_errs)
            self.scales.append(scales)
            self.scale_errs.append(scale_errs)
            self.covariances.append(covariances)
            self.red_chi2s.append(red_chi2s)
            self.nfevals.append(nfevals)
            self.rcs.append(rcs)
            self.fit_durations.append(fit_duration)
            if not quiet:
                print "--------------------------"
                print datafile
                print "~%.4f sec/TOA"%(fit_duration / len(ok_isubs))
                print "Avg. TOA error is %.3f us"%(phi_errs[ok_isubs].mean() *
                        Ps.mean() * 1e6)
            if show_plot:
                stop = time.time()
                tot_duration += stop - start
                self.show_fit(datafile)
                start = time.time()
        if not show_plot:
            tot_duration = time.time() - start
        if not quiet and len(self.ok_isubs):
            print "--------------------------"
            print "Total time: %.2f sec, ~%.4f sec/TOA"%(tot_duration,
                    tot_duration / (np.array(map(len, self.ok_isubs)).sum()))

    def get_channel_red_chi2s(self, threshold=1.5, show=False):
        """
        Calculate reduced chi-squared values for each profile fit.

        Adds attributes self.channel_red_chi2s and self.zap_channels, the
            latter based on a thresholding value.

        threshold is a reduced chi-squared value which is used to flag channels
            for zapping (cf. ppzap.py).  Values above threshold are added to
            self.zap_channels.
        show=True will show the before/after portraits for each subint with
            proposed channels to zap.
        """
        self.channel_red_chi2s = []
        self.zap_channels = []
        for iarch,ok_idatafile in enumerate(self.ok_idatafiles):
            datafile = self.datafiles[ok_idatafile]
            channel_red_chi2s = []
            zap_channels = []
            for isub in self.ok_isubs[iarch]:
                red_chi2s = []
                bad_ichans = []
                port, model, ok_ichans, freqs, noise_stds = self.show_fit(
                        datafile=datafile, isub=isub, rotate=0.0, show=False,
                        return_fit=True, quiet=True)
                for ichan in ok_ichans:
                    channel_red_chi2 = get_red_chi2(port[ichan],
                            model[ichan], errs=noise_stds[ichan],
                            dof=len(port[ichan])-0) #Not sure about exact dof
                    red_chi2s.append(channel_red_chi2)
                    if channel_red_chi2 > threshold: bad_ichans.append(ichan)
                    elif np.isnan(channel_red_chi2): bad_ichans.append(ichan)
                channel_red_chi2s.append(red_chi2s)
                zap_channels.append(bad_ichans)
                if show and len(bad_ichans):
                    show_portrait(port, get_bin_centers(port.shape[1]),
                            title="%s, subint: %d\nbad chans: %s"%(datafile,
                                isub, bad_ichans), show=False)
                    port[bad_ichans] *= 0.0
                    show_portrait(port, get_bin_centers(port.shape[1]),
                            title="%s, subint: %d\nbad chans: %s"%(datafile,
                                isub, bad_ichans), show=True)
            self.channel_red_chi2s.append((channel_red_chi2s))
            self.zap_channels.append((zap_channels))

    def write_princeton_TOAs(self, datafile=None, outfile=None, nu_ref=None,
            one_DM=False, dmerrfile=None):
        """
        Write TOAs to file.

        Currently only writes Princeton-formatted TOAs.

        datafile defaults to self.datafiles, otherwise it is a list of
            PSRCHIVE archive names that have been fitted for TOAs.
        outfile is the name of the output file.
        nu_ref is the desired output reference frequency [MHz] of the TOAs;
            defaults to nu_ref from get_TOAs(...).
        one_DM writes the weighted average delta-DM in the TOA file, instead of
            the per-TOA delta-DM.
        dmerrfile is a string specifying the name of a "DM" file to be written
            containing the TOA, the (full) DM, and the DM uncertainty.  This
            output needs improvement!
        """
        if datafile is None:
            datafiles = self.datafiles
        else:
            datafiles = [datafile]
        if outfile is not None:
            sys.stdout = open(outfile,"a")
        if dmerrfile is not None:
            dmerrs = open(dmerrfile,"a")
        for datafile in datafiles:
            ifile = list(np.array(self.datafiles)[self.ok_idatafiles]).index(
                    datafile)
            ok_isubs = self.ok_isubs[ifile]
            DM0 = self.DM0s[ifile]
            nsub = len(self.nu_refs[ifile])
            if nu_ref is None:
                #Default to self.nu_refs
                if self.nu_ref is None:
                    nu_refs = self.nu_refs[ifile]

                else:
                    nu_refs = self.nu_ref * np.ones(nsub)
                TOAs = self.TOAs[ifile]
                TOA_errs = self.TOA_errs[ifile]
            else:
                nu_refs = nu_ref * np.ones(nsub)
                epochs = self.epochs[ifile]
                Ps = self.Ps[ifile]
                phis = self.phis[ifile]
                TOAs = np.zeros(nsub, dtype="object")
                TOA_errs = self.TOA_errs[ifile]
                DMs = self.DMs[ifile]
                DMs_fitted = DMs / self.doppler_fs[ifile]
                for isub in ok_isubs:
                    TOAs[isub] = calculate_TOA(epochs[isub], Ps[isub],
                            phis[isub], DMs_fitted[isub],
                            self.nu_refs[ifile][isub], nu_refs[isub])
            obs_code = obs_codes[self.obs[ifile].telescope.lower()]
            #Currently writes topocentric frequencies
            for isub in ok_isubs:
                TOA_MJDi = TOAs[isub].intday()
                TOA_MJDf = TOAs[isub].fracday()
                TOA_err = TOA_errs[isub]
                if one_DM:
                    DeltaDM_mean = self.DeltaDM_means[ifile]
                    DM_err = self.DeltaDM_errs[ifile]
                    write_princeton_TOA(TOA_MJDi, TOA_MJDf, TOA_err,
                            nu_refs[isub], DeltaDM_mean, obs=obs_code)
                else:
                    DeltaDMs = self.DMs[ifile] - self.DM0s[ifile]
                    DM_err = self.DM_errs[ifile][isub]
                    write_princeton_TOA(TOA_MJDi, TOA_MJDf, TOA_err,
                            nu_refs[isub], DeltaDMs[isub], obs=obs_code)
                if dmerrfile is not None:
                    TOA_MJDi = TOAs[isub].intday()
                    TOA_MJDf = TOAs[isub].fracday()
                    TOA = "%5d"%int(TOA_MJDi) + ("%.13f"%TOA_MJDf)[1:]
                    dmerrs.write("%.3f\t%s\t%.8f\t%.6f\n"%(nu_refs[isub], TOA,
                        self.DMs[ifile][isub], self.DM_errs[ifile][isub]))
        if dmerrfile is not None:
            dmerrs.close()
        sys.stdout = sys.__stdout__

    def show_subint(self, datafile=None, isub=0, rotate=0.0, quiet=None):
        """
        Plot a phase-frequency portrait of a subintegration.

        datafile is a single PSRCHIVE archive name; defaults to the first one
            listed in self.datafiles.
        isub is the index of the subintegration to be displayed.
        rotate is a phase [rot] specifying the amount to rotate the portrait.
        quiet=True suppresses output.

        To be improved.
        (see show_portrait(...))
        """
        if quiet is None: quiet = self.quiet
        if datafile is None:
            datafile = self.datafiles[0]
        ifile = list(np.array(self.datafiles)[self.ok_idatafiles]).index(
                datafile)
        data = load_data(datafile, dedisperse=True,
                dededisperse=False, tscrunch=False,
                #pscrunch=True, fscrunch=False, rm_baseline=rm_baseline,
                pscrunch=True, fscrunch=False, rm_baseline=True,
                flux_prof=False, refresh_arch=False, return_arch=False,
                quiet=quiet)
        title = "%s ; subint %d"%(datafile, isub)
        port = data.masks[isub,0] * data.subints[isub,0]
        if rotate: port = rotate_data(port, rotate)
        show_portrait(port=port, phases=data.phases, freqs=data.freqs[isub],
                title=title, prof=True, fluxprof=True, rvrsd=bool(data.bw < 0))

    def show_fit(self, datafile=None, isub=0, rotate=0.0, show=True,
            return_fit=False, quiet=None):
        """
        Plot the fit results from a subintegration.

        datafile is a single PSRCHIVE archive name; defaults to the first one
            listed in self.datafiles.
        isub is the index of the subintegration to be displayed.
        rotate is a phase [rot] specifying the amount to rotate the portrait.
        quiet=True suppresses output.

        To be improved.
        (see show_residual_plot(...))
        """
        if quiet is None: quiet = self.quiet
        if datafile is None:
            datafile = self.datafiles[0]
        ifile = list(np.array(self.datafiles)[self.ok_idatafiles]).index(
                datafile)
        data = load_data(datafile, dedisperse=False,
                dededisperse=False, tscrunch=False,
                #pscrunch=True, fscrunch=False, rm_baseline=rm_baseline,
                pscrunch=True, fscrunch=False, rm_baseline=True,
                flux_prof=False, refresh_arch=False, return_arch=False,
                quiet=quiet)
        phi = self.phis[ifile][isub]
        #Pre-corrected DM, if corrected
        DM_fitted = self.DMs[ifile][isub] / self.doppler_fs[ifile][isub]
        GM_fitted = self.GMs[ifile][isub] / self.doppler_fs[ifile][isub]
        scales = self.scales[ifile][isub]
        freqs = data.freqs[isub]
        nu_ref_DM, nu_ref_GM, nu_ref_tau = self.nu_refs[ifile][isub]
        P = data.Ps[isub]
        phases = data.phases
        if self.is_FITS_model:
            model_data = load_data(self.modelfile, dedisperse=False,
                    dededisperse=False, tscrunch=True, pscrunch=True,
                    fscrunch=False, rm_baseline=True, flux_prof=False,
                    #fscrunch=False, rm_baseline=False, flux_prof=False,
                    refresh_arch=False, return_arch=False, quiet=True)
            model = (model_data.masks * model_data.subints)[0,0]
            if model_data.nchan == 1:
                model = np.tile(model[0], len(freqs)).reshape(len(freqs),
                        model_data.nbin)
            model_name = self.modelfile
        else:
            try:
                model_name, ngauss, model = read_model(self.modelfile, phases,
                        freqs, data.Ps.mean(), quiet=quiet)
                        #freqs, data.Ps[isub], quiet=quiet)     #Track down
                if self.taus[ifile][isub] != 0.0:
                    model_name, model_code, model_nu_ref, ngauss, gparams, \
                            fit_flags, alpha, fit_alpha = read_model(
                                    self.modelfile, quiet=quiet)
                    gparams[1] = 0.0
                    model = gen_gaussian_portrait(model_code, gparams, 0.0,
                            phases, freqs, model_nu_ref)
            except:
                model_name, model = read_interp_model(self.modelfile,
                        freqs, data.nbin, quiet=True) #quiet=bool(quiet+(itoa-1)))
        if self.taus[ifile][isub] != 0.0:
            tau = self.taus[ifile][isub]
            if self.log10_tau: tau = 10**tau
            alpha = self.alphas[ifile][isub]
            model = np.fft.irfft(scattering_portrait_FT(
                scattering_times(tau, alpha, freqs, nu_ref_tau), data.nbin) * \
                        np.fft.rfft(model, axis=1), axis=1)
        port = rotate_portrait_full(data.subints[isub,0], phi, DM_fitted,
                GM_fitted, freqs, nu_ref_DM, nu_ref_GM, P)
        if rotate:
            model = rotate_data(model, rotate)
            port = rotate_data(port, rotate)
        port *= data.masks[isub,0]
        model_scaled = np.transpose(scales * np.transpose(model))
        titles = ("%s\nSubintegration %d"%(datafile, isub),
                "Fitted Model %s"%(model_name), "Residuals")
        if show:
            show_residual_plot(port=port, model=model_scaled, resids=None,
                    phases=phases, freqs=freqs, titles=titles,
                    rvrsd=bool(data.bw < 0))
        if return_fit:
            return (port, model_scaled, data.ok_ichans[isub], freqs,
                    data.noise_stds[isub,0])


if __name__ == "__main__":

    from optparse import OptionParser

    usage = "Usage: %prog -d <datafile or metafile> -m <modelfile> [options]"
    parser = OptionParser(usage)
    #parser.add_option("-h", "--help",
    #                  action="store_true", dest="help", default=False,
    #                  help="Show this help message and exit.")
    parser.add_option("-d", "--datafiles",
                      action="store", metavar="archive", dest="datafiles",
                      help="PSRCHIVE archive from which to measure TOAs/DMs, or a metafile listing archive filenames.  \
                              ***NB: Files should NOT be dedispersed!!*** \
                              i.e. vap -c dmc <datafile> should return 0!")
    parser.add_option("-m", "--modelfile",
                      action="store", metavar="model", dest="modelfile",
                      help="Model file from ppgauss.py, ppinterp.py, or PSRCHIVE FITS file that either has same channel frequencies, nchan, & nbin as datafile(s), or is a single profile (nchan = 1, with the same nbin) to be interpreted as a constant template.")
    parser.add_option("-o", "--outfile",
                      action="store", metavar="timfile", dest="outfile",
                      default=None,
                      help="Name of output .tim file. Will append. [default=stdout]")
    parser.add_option("-f", "--format",
                      action="store", metavar="format", dest="format",
                      help="Format of output .tim file; either 'princeton' or 'tempo2'.  Default is tempo2 format.")
    parser.add_option("--flags",
                      action="store", metavar="flags", dest="toa_flags",
                      default="",
                      help="Pairs making up TOA flags to be written uniformly to all tempo2-formatted TOAs.  e.g. ('pta','NANOGrav','version',0.1)")
    parser.add_option("--nu_ref",
                      action="store", metavar="nu_ref", dest="nu_ref",
                      default=None,
                      help="Frequency [MHz] to which the output TOAs are referenced, i.e. the frequency that has zero delay from a non-zero DM. 'inf' is used for inifite frequency.  [default=nu_zero (zero-covariance frequency, recommended)]")
    parser.add_option("--DM",
                      action="store", metavar="DM", dest="DM0", default=None,
                      help="Nominal DM [cm**-3 pc] from which to reference offset DM measurements.  If unspecified, will use the DM stored in each archive.")
    parser.add_option("--no_bary_DM",
                      action="store_false", dest="bary_DM", default=True,
                      help='Do not Doppler-correct the DM to make a "barycentric DM".')
    parser.add_option("--one_DM",
                      action="store_true", dest="one_DM", default=False,
                      help="Returns single DM value in output .tim file for all subints in the epoch instead of a fitted DM per subint.")
    parser.add_option("--snr_cut",
                      metavar="SNR", action="store", dest="snr_cutoff",
                      default=0.0,
                      help="Set a SNR cutoff for TOAs written.")
    parser.add_option("--errfile",
                      action="store", metavar="errfile", dest="errfile",
                      default=None,
                      help="If specified, will write the fitted DM errors to errfile (desirable if using non-tempo2 formatted TOAs). Will append.")
    parser.add_option("--fix_DM",
                      action="store_false", dest="fit_DM", default=True,
                      help="Do not fit for DM. NB: the parfile DM will still be 'barycentered' in the TOA lines unless --no_bary_DM is used!")
    parser.add_option("--fit_dt4",
                      action="store_true", dest="fit_GM", default=False,
                      help="Fit for delays that scale as nu**-4 and return 'GM' parameters s.t. dt4 = Dconst**2 * GM * nu**-4.  GM has units [cm**-6 pc**2 s**-1] and can be related to a discrete cloud causing refractive, geometric delays.")
    parser.add_option("--fit_scat",
                      action="store_true", dest="fit_scat", default=False,
                      help="Fit for scattering timescale and index per TOA.  Can be used with --fix_alpha.")
    parser.add_option("--no_logscat",
                      action="store_false", dest="log10_tau", default=True,
                      help="If using fit_scat, this flag specifies not to fit the log10 of the scattering timescale, but simply the scattering timescale.")
    parser.add_option("--fix_alpha",
                      action="store_true", dest="fix_alpha", default=False,
                      help="Fix the scattering index value to the value specified as scattering_alpha in pplib.py or alpha in the provided .gmodel file.  Only used in combination with --fit_scat.")
    parser.add_option("--print_phase",
                      action="store_true", dest="print_phase", default=False,
                      help="Print the fitted phase shift on the TOA line with the flag -phs")
    parser.add_option("--showplot",
                      action="store_true", dest="show_plot", default=False,
                      help="Show a plot of fitted data/model/residuals for each subint.  Good for diagnostic purposes only.")
    parser.add_option("--quiet",
                      action="store_true", dest="quiet", default=False,
                      help="Only TOAs printed to standard output, if outfile is None.")

    (options, args) = parser.parse_args()

    if (options.datafiles is None or options.modelfile is None):
        print "\npptoas.py - simultaneously measure TOAs and DMs in broadband data\n"
        parser.print_help()
        print ""
        parser.exit()

    datafiles = options.datafiles
    modelfile = options.modelfile
    nu_ref = options.nu_ref
    if nu_ref:
        if nu_ref == "inf":
            nu_ref = np.inf
        else:
            nu_ref = np.float64(nu_ref)
        nu_refs = (nu_ref, None)
    else: nu_refs = None
    DM0 = options.DM0
    if DM0: DM0 = np.float64(DM0)
    bary_DM = options.bary_DM
    one_DM = options.one_DM
    fit_DM = options.fit_DM
    fit_GM = options.fit_GM
    fit_scat = options.fit_scat
    log10_tau = options.log10_tau
    fix_alpha = options.fix_alpha
    print_phase = options.print_phase
    outfile = options.outfile
    format = options.format
    k,v = options.toa_flags.split(',')[::2],options.toa_flags.split(',')[1::2]
    addtnl_toa_flags = dict(zip(k,v))
    snr_cutoff = float(options.snr_cutoff)
    errfile = options.errfile
    show_plot = options.show_plot
    quiet = options.quiet

    gt = GetTOAs(datafiles=datafiles, modelfile=modelfile, quiet=quiet)
    gt.get_TOAs(datafile=None, nu_refs=nu_refs, DM0=DM0, bary_DM=bary_DM,
            fit_DM=fit_DM, fit_GM=fit_GM, fit_scat=fit_scat,
            log10_tau=log10_tau, fix_alpha=fix_alpha, print_phase=print_phase,
            method='trust-ncg', bounds=None, nu_fits=None, show_plot=show_plot,
            addtnl_toa_flags=addtnl_toa_flags, quiet=quiet)
    if format == "princeton":
        gt.write_princeton_TOAs(outfile=outfile, one_DM=one_DM,
            dmerrfile=errfile)
    else:
        if one_DM:
            gt.TOA_one_DM_list = [toa for toa in gt.TOA_list]
            for toa in gt.TOA_one_DM_list:
                ifile = list(np.array(gt.datafiles)[gt.ok_idatafiles]).index(
                        toa_archive)
                DDM = gt.DeltaDM_means[ifile]
                DDM_err = gt.DeltaDM_errs[ifile]
                toa.DM = DDM + gt.DM0s[ifile]
                toa.DM_error = DDM_err
                toa.flags['DM_mean'] = True
            write_TOAs(gt.TOA_one_DM_list, format="tempo2",
                    SNR_cutoff=snr_cutoff, outfile=outfile, append=True)
        else:
            write_TOAs(gt.TOA_list, format="tempo2", SNR_cutoff=snr_cutoff,
                    outfile=outfile, append=True)
