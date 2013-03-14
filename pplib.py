#!/usr/bin/env python

# To be used with PSRCHIVE Archive files

# This fitting algorithm lays on the bed of Procrustes all too comfortably.

#Next two lines needed for dispatching on nodes (not implemented yet)
#import matplotlib
#matplotlib.use("Agg")

import sys
import time
import matplotlib.pyplot as plt
import numpy as np
import numpy.fft as fft
import scipy.optimize as opt
import lmfit as lm
import psrchive as pr

#Colormap preference
#plt.copper()
#plt.gray()
#plt.bone()
plt.pink()
plt.close("all")

#List of colors
cols = ['b','g','r','c','m','y','b','g','r','c','m','y','b','g','r','c','m',
        'y','b','g','r','c','m','y','b','g','r','c','m','y']

#List of observatory codes; not sure what "0" corresponds to.
obs_codes = {"bary":"@", "inf":"0", "gbt":"1", "atca":"2", "ao":"3",
             "nanshan":"5", "tid43":"6", "pks":"7", "jb":"8", "vla":"c",
             "ncy":"f", "eff":"g", "jbdfb":"q", "wsrt":"i"}

#RCSTRINGS dictionary, for the return codes given by scipy.optimize.fmin_tnc
RCSTRINGS = {"-1":"INFEASIBLE: Infeasible (low > up).",
             "0":"LOCALMINIMUM: Local minima reach (|pg| ~= 0).",
             "1":"FCONVERGED: Converged (|f_n-f_(n-1)| ~= 0.)",
             "2":"XCONVERGED: Converged (|x_n-x_(n-1)| ~= 0.)",
             "3":"MAXFUN: Max. number of function evaluations reach.",
             "4":"LSFAIL: Linear search failed.",
             "5":"CONSTANT: All lower bounds are equal to the upper bounds.",
             "6":"NOPROGRESS: Unable to progress.",
             "7":"USERABORT: User requested end of minimization."}

#Exact dispersion constant (e**2/(2*pi*m_e*c))
#used by PRESTO
Dconst_exact = 4.148808e3 #[MHz**2 pc**-1 cm**3 s]

#"Traditional" dispersion constant
#used by PSRCHIVE
Dconst_trad = 0.000241**-1 #[MHz**2 pc**-1 cm**3 s]

#Choose wisely.
Dconst = Dconst_trad

class DataBunch(dict):
    """
    This class is a baller little recipe!  Creates a simple class instance
    db = DataBunch(a=1, b=2,....) that has attributes a and b callable and
    update-able via either syntax db.a or db['a'], etc.
    """
    def __init__(self, **kwds):
        dict.__init__(self, kwds)
        self.__dict__ = self

def gaussian_profile(N, loc, wid, norm=False, abs_wid=False, zeroout=True):
    """
    Taken and tweaked from SMR's pygaussfit.py

    Return a gaussian pulse profile with 'N' bins and an integrated 'flux' of
    1 unit (if norm=True; default norm=False and peak ampltiude = 1).
        'N' = the number of points in the profile
        'loc' = the pulse phase (0-1)
        'wid' = the gaussian pulses full width at half-max (FWHM)
    If abs_wid=True, will use abs(wid).
    If zeroout=True and wid <= 0, return a zero array.
    Note: The FWHM of a gaussian is approx 2.35482 sigma
          (exactly 2*sqrt(2*ln(2))).
    """
    #Maybe should move these checks to gen_gaussian_portrait?
    if abs_wid:
        wid = abs(wid)
    if wid > 0.0:
        pass
    elif wid == 0.0:
        return np.zeros(N, 'd')
    elif wid < 0.0 and zeroout:
        return np.zeros(N, 'd')
    elif wid < 0.0 and not zeroout:
        pass
    else:
        return 0
    sigma = wid / (2 * np.sqrt(2 * np.log(2)))
    mean = loc % 1.0
    locval = np.arange(N, dtype='d') / float(N)
    if (mean < 0.5):
        locval = np.where(np.greater(locval, mean + 0.5), locval - 1.0, locval)
    else:
        locval = np.where(np.less(locval, mean - 0.5), locval + 1.0, locval)
    try:
        zs = (locval - mean) / sigma
        okzinds = np.compress(np.fabs(zs) < 20.0, np.arange(N))   #Why 20?
        okzs = np.take(zs, okzinds)
        retval = np.zeros(N, 'd')
        np.put(retval, okzinds, np.exp(-0.5 * (okzs)**2.0)/(sigma * np.sqrt(2 *
            np.pi)))
        if norm:
            return retval
        #else:
        #    return retval / np.max(retval)
        else:
            if np.max(abs(retval)) == 0.0:
                return retval   #TP hack
            else:
                return retval / np.max(abs(retval))  #TP hack
    except OverflowError:
        print "Problem in gaussian prof:  mean = %f  sigma = %f" %(mean, sigma)
        return np.zeros(N, 'd')

def gen_gaussian_profile(params, N):
    """
    Taken and tweaked from SMR's pygaussfit.py

    Return a model of a DC-component + M gaussians.
    params is a sequence of 1+M*3 values; the first value is the DC component.
    Each remaining group of three represents the gaussians loc (0-1),
    wid (FWHM) (0-1), and amplitude (>0.0). N is the number of points in the
    model.
    """
    ngauss = (len(params) - 1) / 3
    model = np.zeros(N, dtype='d') + params[0]
    for ii in xrange(ngauss):
        loc, wid, amp = params[(1 + ii*3):(4 + ii*3)]
        model += amp * gaussian_profile(N, loc, wid)
    return model

def gen_gaussian_portrait(params, phases, freqs, nu_ref):
    """
    """
    refparams = np.array([params[0]]+ list(params[1::2]))
    locparams = params[2::6]
    widparams = params[4::6]
    ampparams = params[6::6]
    ngauss = len(refparams[1::3])
    nbin = len(phases)
    nchan = len(freqs)
    gport = np.empty([nchan, nbin])
    gparams = np.empty([nchan, len(refparams)])
    #DC term
    gparams[:,0] = refparams[0]
    #Locs
    gparams[:,1::3] = np.outer(freqs - nu_ref, locparams) + np.outer(np.ones(
        nchan), refparams[1::3])
    #Wids
    gparams[:,2::3] = np.outer(freqs - nu_ref, widparams) + np.outer(np.ones(
        nchan), refparams[2::3])
    #Amps
    gparams[:,3::3] = np.exp(np.outer(np.log(freqs) - np.log(nu_ref),
        ampparams) + np.outer(np.ones(nchan), np.log(refparams[3::3])))
    #Amps; I am unsure why I needed this fix at some point
    #gparams[:, 0::3][:, 1:] = np.exp(np.outer(np.log(freqs) - np.log(nu_ref),
    #    ampparams) + np.outer(np.ones(nchan), np.log(refparams[0::3][1:])))
    for nn in range(nchan):
        #Need to contrain so values don't go negative, etc., which is currently
        #done in gaussian_profile
        gport[nn] = gen_gaussian_profile(gparams[nn], nbin)
    return gport

def powlaw(nu, nu0, A, alpha):
    """
    Returns power-law spectrum given by:
    F(nu) = A*(nu/nu0)**alpha
    """
    return A * (nu/nu0)**alpha

def powlaw_integral(nu2, nu1, nu0, A, alpha):
    """
    Returns the integral over a powerlaw of form A*(nu/nu0)**alpha
    from nu1 to nu2
    """
    alpha = np.float(alpha)
    if alpha == -1.0:
        return A * nu0 * np.log(nu2/nu1)
    else:
        C = A * (nu0**-alpha) / (1 + alpha)
        diff = ((nu2**(1+alpha)) - (nu1**(1+alpha)))
        return C * diff

def powlaw_freqs(lo, hi, N, alpha, mid=False):
    """
    Returns frequencies such that a bandwidth from lo to hi frequencies
    split into N chunks contains the same amount of power in each chunk,
    given a power-law across the band with spectral index alpha.  Default
    behavior returns N+1 frequencies (includes both lo and hi freqs); if
    mid=True, will return N frequencies, corresponding to the middle frequency
    in each chunk.
    """
    alpha = np.float(alpha)
    nus = np.zeros(N + 1)
    if alpha == -1.0:
        nus = np.exp(np.linspace(np.log(lo), np.log(hi), N+1))
    else:
        nus = np.power(np.linspace(lo**(1+alpha), hi**(1+alpha), N+1),
                (1+alpha)**-1)
        #Equivalently:
        #for nn in xrange(N+1):
        #    nus[nn] = ((nn / np.float(N)) * (hi**(1+alpha)) + (1 - (nn /
        #        np.float(N))) * (lo**(1+alpha)))**(1 / (1+alpha))
    if mid:
        midnus = np.zeros(N)
        for nn in xrange(N):
            midnus[nn] = 0.5 * (nus[nn] + nus[nn+1])
        nus = midnus
    return nus

def fit_powlaw_function(params, freqs, nu0, weights=None, data=None,
        errs=None):
    """
    """
    prms = np.array([param.value for param in params.itervalues()])
    A = prms[0]
    alpha = prms[1]
    d = []
    f = []
    for ii in xrange(len(weights)):
        if weights[ii]:
            d.append(data[ii])
            f.append(freqs[ii])
        else: pass
    d=np.array(d)
    f=np.array(f)
    return (d - powlaw(f, nu0, A, alpha)) / errs

def fit_gauss_function(params, data=None, errs=None):
    """
    """
    prms = np.array([param.value for param in params.itervalues()])
    return (data - gen_gaussian_profile(prms, len(data))) / errs

def fit_gaussian_portrait_function(params, phases, freqs, nu_ref, data=None,
        errs=None):
    """
    """
    prms = np.array([param.value for param in params.itervalues()])
    deviates = np.ravel((data - gen_gaussian_portrait(prms, phases, freqs,
        nu_ref)) / errs)
    return deviates

def fit_portrait_function(params, model=None, p=None, data=None, d=None,
        errs=None, P=None, freqs=None, nu0=np.inf):
    """
    """
    phase = params[0]
    m = 0.0
    if P == None or freqs == None:
        D = 0.0
        freqs = np.inf * np.ones(len(model))
    else: D = Dconst * params[1] / P
    for nn in xrange(len(freqs)):
        err = errs[nn]
        freq = freqs[nn]
        harmind = np.arange(len(model[nn]))
        phasor = np.exp(harmind * 2.0j * np.pi * (phase + (D * (freq**-2.0 -
            nu0**-2.0))))
        mm = np.real(data[nn,:] * np.conj(model[nn,:]) * phasor).sum()
        m += (mm**2.0) * err / p[nn]
    return d - m

def fit_portrait_function_deriv(params, model=None, p=None, data=None, d=None,
        errs=None, P=None, freqs=None, nu0=np.inf):
    """
    """
    phase = params[0]
    D = Dconst * params[1] / P
    d_phi,d_DM = 0.0, 0.0
    for nn in xrange(len(freqs)):
        err = errs[nn]
        freq = freqs[nn]
        harmind = np.arange(len(model[nn]))
        phasor = np.exp(harmind * 2.0j * np.pi * (phase + (D * (freq**-2.0 -
            nu0**-2.0))))
        g1 = np.real(data[nn,:] * np.conj(model[nn,:]) * phasor).sum()
        gp2 = np.real(2j * np.pi * harmind * data[nn,:] *
                np.conj(model[nn,:]) * phasor).sum()
        gd2 = np.real(2j * np.pi * harmind * (freq**-2.0 - nu0**-2.0) *
                (Dconst/P) * data[nn,:] * np.conj(model[nn,:]) * phasor).sum()
        d_phi += -2 * g1 * gp2 * err / p[nn]
        d_DM += -2 * g1 * gd2 * err / p[nn]
    return np.array([d_phi, d_DM])

def fit_portrait_function_2deriv(params, model=None, p=None, data=None, d=None,
        errs=None, P=None, freqs=None, nu0=np.inf):
    #Need Covariance matrix...
    """
    """
    phase = params[0]
    D = Dconst * params[1] / P
    d2_phi, d2_DM = 0.0, 0.0
    for nn in xrange(len(freqs)):
        err = errs[nn]
        freq = freqs[nn]
        harmind = np.arange(len(model[nn]))
        phasor = np.exp(harmind * 2.0j * np.pi * (phase + (D * (freq**-2.0 -
            nu0**-2.0))))
        g1 = np.real(data[nn,:] * np.conj(model[nn,:]) * phasor).sum()
        gp2 = np.real(2.0j * np.pi * harmind * data[nn,:] *
                np.conj(model[nn,:]) * phasor).sum()
        gd2 = np.real(2.0j * np.pi * harmind * (freq**-2.0 - nu0**-2.0) *
                (Dconst/P) * data[nn,:] * np.conj(model[nn,:]) * phasor).sum()
        gp3 = np.real(pow(2.0j * np.pi * harmind, 2.0) * data[nn,:] *
                np.conj(model[nn,:]) * phasor).sum()
        gd3 = np.real(pow(2.0j * np.pi * harmind *
            (freq**-2.0 - nu0**-2.0) * (Dconst/P), 2.0) * data[nn,:] *
            np.conj(model[nn,:]) * phasor).sum()
        d2_phi += -2.0 * err * (pow(gp2, 2.0) + (g1 * gp3)) / p[nn]
        d2_DM += -2.0 * err * (pow(gd2, 2.0) + (g1 * gd3)) / p[nn]
    return np.array([d2_phi, d2_DM])

def estimate_portrait(phase, DM, data, scales, P, freqs, nu0=np.inf):
    #here, all vars have additional epoch-index except nu0
    #i.e. all have to be arrays of at least len 1; errs are precision
    """
    """
    #Next lines should be done just as in fit_portrait
    dFFT = fft.rfft(data, axis=2)
    #Below is Precision FIX
    unnorm_errs = np.real(dFFT[:, :, -len(dFFT[0,0])/4:]).std(axis=2)**-2.0
    #norm_dFFT = np.transpose((unnorm_errs**0.5) * np.transpose(dFFT))
    #norm_errs = np.real(norm_dFFT[:, :, -len(norm_dFFT[0,0])/4:]
    #        ).std(axis=2)**-2.
    errs = unnorm_errs
    D = Dconst * DM / P
    freqs2 = freqs**-2.0 - nu0**-2.0
    phiD = np.outer(D, freqs2)
    phiprime = np.outer(phase, np.ones(len(freqs))) + phiD
    weight = np.sum(pow(scales, 2.0) * errs, axis=0)**-1
    phasor = np.array([np.exp(2.0j * np.pi * kk * phiprime) for kk in xrange(
        len(dFFT[0,0]))]).transpose(1,2,0)
    p = np.sum(np.transpose(np.transpose(scales * errs) * np.transpose(phasor *
        dFFT)), axis=0)
    wp = np.transpose(weight * np.transpose(p))
    return wp

def wiener_filter(prof, noise):
    #FIX does not work
    """
    prof is noisy template
    noise is standard deviation of the gaussian noise in the data
    """
    FFT = fft.rfft(prof)
    #Check Normalization below
    pows = np.real(FFT * np.conj(FFT)) / len(prof)
    return pows / (pows + (noise**2))
    #return (pows - (noise**2)) / pows

def brickwall_filter(n, kc):
    """
    """
    fk = np.zeros(n)
    fk[:kc] = 1.0
    return fk

def find_kc(prof, noise):
    """
    """
    wf = wiener_filter(prof, noise)
    N = len(wf)
    X2 = np.zeros(N)
    for ii in xrange(N):
        X2[ii] = np.sum((wf - brickwall_filter(N, ii))**2)
    return X2.argmin()

def fit_powlaw(data, freqs, nu0, weights, init_params, errs):
    """
    """
    nparam = len(init_params)
    #Generate the parameter structure
    params = lm.Parameters()
    params.add('amp', init_params[0], vary=True, min=None, max=None)
    params.add('alpha', init_params[1], vary=True, min=None, max=None)
    other_args = {'freqs':freqs, 'nu0':nu0, 'weights':weights, 'data':data,
            'errs':errs}
    #Now fit it
    results = lm.minimize(fit_powlaw_function, params, kws=other_args)
    fitted_params = np.array([param.value for param in
        results.params.itervalues()])
    dof = results.nfree
    chi_sq = results.chisqr
    redchi_sq = results.redchi
    residuals = results.residual
    fit_errs = np.array([param.stderr for param in
        results.params.itervalues()])
    return fitted_params, fit_errs, chi_sq, dof, residuals

def fit_gaussian_profile(data, init_params, errs, quiet=True):
    """
    """
    nparam = len(init_params)
    ngauss = (len(init_params) - 1) / 3
    #Generate the parameter structure
    params = lm.Parameters()
    for ii in xrange(nparam):
        if ii == 0:
            params.add('dc', init_params[ii], vary=True, min=None, max=None,
                    expr=None)
        elif ii in range(nparam)[1::3]:
            params.add('loc%s'%str((ii-1)/3 + 1), init_params[ii], vary=True,
                    min=None, max=None, expr=None)
        elif ii in range(nparam)[2::3]:
            params.add('wid%s'%str((ii-1)/3 + 1), init_params[ii], vary=True,
                    min=0.0, max=None, expr=None)
        elif ii in range(nparam)[3::3]:
            params.add('amp%s'%str((ii-1)/3 + 1), init_params[ii], vary=True,
                    min=0.0, max=None, expr=None)
        else:
            print "Undefined index %d."%ii
            sys.exit()
    other_args = {'data':data, 'errs':errs}
    #Now fit it
    results = lm.minimize(fit_gauss_function, params, kws=other_args)
    fitted_params = np.array([param.value for param in
        results.params.itervalues()])
    dof = results.nfree
    redchi_sq = results.redchi
    residuals = results.residual
    if not quiet:
        print "---------------------------------------------------------------"
        print "Multi-Gaussian Profile Fit Results"
        print "---------------------------------------------------------------"
        print "lmfit status:", results.message
        print "gaussians:", ngauss
        print "DOF:", dof
        print "reduced chi-sq: %.2f" % redchi_sq
        print "residuals mean: %.3g" % np.mean(residuals)
        print "residuals stdev: %.3g" % np.std(residuals)
        print "---------------------------------------------------------------"
    return fitted_params, redchi_sq, dof, residuals

def fit_gaussian_portrait(data, errs, init_params, fix_params, phases, freqs,
        nu_ref, quiet=True):
    """
    """
    nparam = len(init_params)
    ngauss = (len(init_params) - 1) / 6
    fixloc,fixwid,fixamp = fix_params
    #Generate the parameter structure
    params = lm.Parameters()
    for ii in xrange(nparam):
        if ii == 0:         #DC, limited by 0
            params.add('dc', init_params[ii], vary=True, min=None, max=None,
                    expr=None)
        elif ii%6 == 1:     #loc limits
            params.add('loc%s'%str((ii-1)/6 + 1), init_params[ii], vary=True,
                    min=None, max=None, expr=None)
        elif ii%6 == 2:     #loc slope limits
            params.add('m_loc%s'%str((ii-1)/6 + 1), init_params[ii],
                    vary=not(fixloc), min=None, max=None, expr=None)
        elif ii%6 == 3:     #wid limits, limited by 0
            params.add('wid%s'%str((ii-1)/6 + 1), init_params[ii], vary=True,
                    min=0.0, max=None, expr=None)
        elif ii%6 == 4:     #wid slope limits
            params.add('m_wid%s'%str((ii-1)/6 + 1), init_params[ii],
                    vary=not(fixwid), min=None, max=None, expr=None)
        elif ii%6 == 5:     #amp limits, limited by 0
            params.add('amp%s'%str((ii-1)/6 + 1), init_params[ii], vary=True,
                    min=0.0, max=None, expr=None)
        elif ii%6 == 0:     #amp index limits
            params.add('alpha%s'%str((ii-1)/6 + 1), init_params[ii],
                    vary=not(fixamp), min=None, max=None, expr=None)
        else:
            print "Undefined index %d."%ii
            sys.exit()
    other_args = {'data':data, 'errs':errs, 'phases':phases, 'freqs':freqs,
            'nu_ref':nu_ref}
    #Now fit it
    results = lm.minimize(fit_gaussian_portrait_function, params,
            kws=other_args)
    fitted_params = np.array([param.value for param in
        results.params.itervalues()])
    dof = results.nfree
    chi_sq = results.chisqr
    redchi_sq = results.redchi
    residuals = results.residual
    model = gen_gaussian_portrait(fitted_params, phases, freqs, nu_ref)
    if not quiet:
        print "---------------------------------------------------------------"
        print "Gaussian Portrait Fit"
        print "---------------------------------------------------------------"
        print "lmfit status:", results.message
        print "gaussians:", ngauss
        print "DOF:", dof
        print "reduced chi-sq: %.2f" %redchi_sq
        print "residuals mean: %.3g" %np.mean(residuals)
        print "residuals stdev: %.3g" %np.std(residuals)
        print "---------------------------------------------------------------"
    return fitted_params, chi_sq, dof

def fit_portrait(data, model, init_params, P=None, freqs=None, nu0=np.inf,
        scales=True, quiet=True):
    """
    """
    #tau = precision = 1/variance
    #FIX Need to use better filtering instead of frac in get_noise
    #FIX get_noise is not right
    #errs = get_noise(data, tau=True, chans=True, fd=True, frac=4) 
    dFFT = fft.rfft(data, axis=1)
    mFFT = fft.rfft(model, axis=1)
    #Precision FIX
    unnorm_errs = np.real(dFFT[:, -len(dFFT[0])/4:]).std(axis=1)**-2.0
    norm_dFFT = np.transpose((unnorm_errs**0.5) * np.transpose(dFFT))
    norm_errs = np.real(norm_dFFT[:, -len(norm_dFFT[0])/4:]).std(axis=1)**-2.0
    errs = unnorm_errs
    d = np.real(np.sum(np.transpose(errs * np.transpose(dFFT *
        np.conj(dFFT)))))
    p = np.real(np.sum(mFFT * np.conj(mFFT), axis=1))
    #other_args = {'model':mFFT, 'p':p, 'data':dFFT, 'd':d, 'errs':errs, 'P':P,
    #        'freqs':freqs, 'nu0':nu0}
    #BEWARE BELOW! Order matters!
    other_args = (mFFT, p, dFFT, d, errs, P, freqs, nu0)
    minimize = opt.minimize
    #fmin_tnc seems to work best, fastest
    method = 'TNC'
    #Bounds on phase, DM
    bounds = [(None,None),(None,None)]
    start = time.time()
    results = minimize(fit_portrait_function, init_params, args=other_args,
            method=method, jac=fit_portrait_function_deriv, bounds=bounds,
            options={'disp':False})
    duration = time.time() - start
    phi = results.x[0]
    DM = results.x[1]
    nfeval = results.nfev
    return_code = results.status
    rcstring = RCSTRINGS["%s"%str(return_code)]
    #If the fit fails...????
    if results.success is not True:
        sys.stderr.write("Fit failed with return code %d -- %s\n"
                %(results.status, rcstring))
    if not quiet and results.success is True:
        sys.stderr.write("Fit suceeded with return code %d -- %s\n"
                %(results.status, rcstring))
    param_errs = list(pow(fit_portrait_function_2deriv(np.array([phi, DM]),
        mFFT, p, dFFT, d, errs, P, freqs, nu0), -0.5))
    DoF = len(data.ravel()) - (len(freqs) + 2)
    red_chi2 = results.fun / DoF
    if scales:
        scales = get_scales(data, model, phi, DM, P, freqs, nu0)
        #Errors on scales, if ever needed
        param_errs += list(pow(2 * p * errs, -0.5))
        return (phi, DM, nfeval, return_code, scales, np.array(param_errs),
                red_chi2, duration)
    else: return (phi, DM, nfeval, return_code, np.array(param_errs), red_chi2,
            duration)

def first_guess(data, model, nguess=1000):
    """
    """
    crosscorr = np.empty(nguess)
    #phaseguess = np.linspace(0, 1.0, nguess)
    phaseguess = np.linspace(-0.5, 0.5, nguess)
    for ii in range(nguess):
        phase = phaseguess[ii]
        crosscorr[ii] = np.correlate(fft_rotate(np.sum(data, axis=0),
            phase * len(np.sum(data, axis=0))), np.sum(model, axis=0))
    phaseguess = phaseguess[crosscorr.argmax()]
    return phaseguess

def read_model(modelfile, phases, freqs, quiet=False):
    """
    """
    nbin = len(phases)
    nchan = len(freqs)
    modeldata = open(modelfile, "r").readlines()
    ngauss = len(modeldata) - 3
    params = np.zeros(ngauss*6 + 1)
    name = modeldata.pop(0)[:-1]
    nu_ref = float(modeldata.pop(0))
    params[0] = float(modeldata.pop(0))
    for gg in xrange(ngauss):
        comp = map(float, modeldata[gg].split())
        params[1 + gg*6 : 7 + (gg*6)] = comp
    model = gen_gaussian_portrait(params, phases, freqs, nu_ref)
    if not quiet:
        print "Model Name: %s"%name
        print "Made %d component model with %d profile bins,"%(
                ngauss, nbin)
        print "%d frequency channels, %.0f MHz bandwidth, centered near %.3f MHz,"%(nchan, (freqs[-1] - freqs[0]) + ((freqs[-1] - freqs[-2])), freqs.mean())
        print "with model parameters referenced at %.3f MHz."%nu_ref
    return name, ngauss, model

def get_noise(data, frac=4, tau=False, chans=False, fd=False):
    #FIX: Make sure to use on portraits w/o zapped freq. channels
    #i.e. portxs
    #FIX: MAKE SIMPLER!!!
    #FIX: Implement k_max from wiener/brick-wall filter fit
    #FIX This is not right 
    """
    """
    shape = data.shape
    if len(shape) == 1:
        prof = data
    elif shape[0] == 1:
        prof = data[0]
    elif shape[1] == 1:
        prof = data[:,0]
    else: pass
    try:
        FFT = fft.rfft(prof)
        if fd:
            if tau: return np.std(np.real(FFT)[-len(FFT)/frac:])**-2
            #if tau: return (np.std(np.real(FFT)[-len(FFT)/frac:])**-2,
            #        np.std(np.imag(FFT)[-len(FFT)/frac:])**-2)
            else: return np.std(np.real(FFT)[-len(FFT)/frac:])
            #else: return (np.std(np.real(FFT)[-len(FFT)/frac:]), np.std(
            #    np.imag(FFT)[-len(FFT)/frac:]))
        else:
            #!!!CHECK NORMALIZATION BELOW
            pows = np.real(FFT * np.conj(FFT)) / len(prof)
            if tau:
                return (np.mean(pows[-len(pows)/frac:]))**-1
            else:
                return np.sqrt(np.mean(pows[-len(pows)/frac:]))
    except(NameError):
        noise = np.zeros(len(data))
        if fd:
            for nn in range(len(noise)):
                    prof = data[nn]
                    FFT = fft.rfft(prof)
                    noise[nn] = np.std(np.real(FFT)[-len(FFT)/frac:])
            if chans:
                if tau: return noise**-2
                else: return noise
            else:
                if tau:
                    #not statistically rigorous
                    return np.median(noise)**-2
                else:
                    return np.median(noise)
        else:
            for nn in range(len(noise)):
                prof = data[nn]
                FFT = fft.rfft(prof)
                #!!!CHECK NORMALIZATION BELOW
                pows = np.real(FFT * np.conj(FFT)) / len(prof)
                noise[nn] = np.sqrt(np.mean(pows[-len(pows)/frac:]))
            if chans:
                if tau:
                    return noise**-2
                else:
                    return noise
            else:
                if tau:
                    #not statistically rigorous
                    return np.median(noise)**-2
                else:
                    return np.median(noise)

def get_scales(data, model, phase, DM, P, freqs, nu0):
    """
    """
    scales = np.zeros(len(model))
    dFFT = fft.rfft(data, axis=1)
    mFFT = fft.rfft(model, axis=1)
    p = np.real(np.sum(mFFT * np.conj(mFFT), axis=1))
    D = DM * Dconst / P
    #FIX vectorize
    for kk in range(len(mFFT[0])):
        scales += np.real(dFFT[:,kk] * np.conj(mFFT[:,kk]) * np.exp(2j *
            np.pi * kk * (phase + (D * (pow(freqs,-2) - pow(nu0,-2)))))) / p
    return scales

def rotate_portrait(port, phase, DM=None, P=None, freqs=None, nu0=np.inf):
    """
    Positive values of phase and DM rotate to earlier phase.
    """
    pFFT = fft.rfft(port, axis=1)
    for nn in xrange(len(pFFT)):
        if DM is None and freqs is None:
            pFFT[nn,:] *= np.exp(np.arange(len(pFFT[nn])) * 2.0j * np.pi *
                    phase)
        else:
            D = DM * Dconst / P
            freq = freqs[nn]
            phasor = np.exp(np.arange(len(pFFT[nn])) * 2.0j * np.pi * (phase +
                (D * (freq**-2.0 - nu0**-2.0))))
            pFFT[nn,:] *= phasor
    return fft.irfft(pFFT)

def write_model(filenm, name, model_params, nu_ref):
    """
    """
    outfile = open(filenm, "a")
    outfile.write("%s\n"%name)
    outfile.write("%.8f\n"%nu_ref)
    outfile.write("%.8f\n"%model_params[0])
    ngauss = (len(model_params) - 1) / 6
    for nn in xrange(ngauss):
        comp = model_params[(1 + nn*6):(7 + nn*6)]
        outfile.write("%.8f\t %.8f\t %.8f\t %.8f\t %.8f\t %.8f\n"%(comp[0],
            comp[1], comp[2], comp[3], comp[4] ,comp[5]))
    outfile.close()
    print "%s written."%filenm

def load_data(filenm, dedisperse=False, dededisperse=False, tscrunch=False,
        pscrunch=False, rm_baseline=True, flux_prof=False, quiet=False):
    """
    Will read and return data using PSRCHIVE.
    The returned archive is 'refreshed'.
    """
    #Load archive
    arch = pr.Archive_load(filenm)
    source = arch.get_source()
    if not quiet:
        print "\nReading data from %s on source %s..."%(filenm, source)
    #Center of the band
    nu0 = arch.get_centre_frequency()
    #For the negative BW cases.  Good fix
    #bw = abs(arch.get_bandwidth())
    bw = arch.get_bandwidth()
    nchan = arch.get_nchan()
    #Centers of frequency channels
    freqs = np.array([arch.get_Integration(0).get_centre_frequency(ii) for ii
        in range(nchan)])
    #Again, for the negative BW cases.  Good fix?
    #freqs.sort()
    #By-hand frequency calculation, equivalent to above from PSRCHIVE
    #chanwidth = bw / nchan
    #lofreq = nu0 - (bw/2)
    #freqs = np.linspace(lofreq + (chanwidth/2.0), lofreq + bw -
    #        (chanwidth/2.0), nchan)
    nbin = arch.get_nbin()
    #Centers of phase bins
    phases = np.linspace(0.0 + (nbin*2)**-1, 1.0 - (nbin*2)**-1, nbin)
    #These are NOT the bin centers...
    #phases = np.arange(nbin, dtype='d') / nbin
    #De/dedisperse?
    if dedisperse: arch.dedisperse()
    if dededisperse: arch.dededisperse()
    #Maybe use better basline subtraction??
    if rm_baseline: arch.remove_baseline()
    #pscrunch?
    if pscrunch: arch.pscrunch()
    #tscrunch?
    if tscrunch: arch.tscrunch()
    nsub = arch.get_nsubint()
    #Get data
    #PSRCHIVE indices [subint:pol:chan:bin]
    subints = arch.get_data()[:,:,:,:]
    npol = arch.get_npol()
    Ps = np.array([arch.get_Integration(ii).get_folding_period() for ii in
        xrange(nsub)],dtype=np.double)
    epochs = [arch.get_Integration(ii).get_epoch() for ii in xrange(nsub)]
    #Get weights
    weights = arch.get_weights()
    weights_norm = np.where(weights == 0.0, np.zeros(weights.shape),
            np.ones(weights.shape))
    #np.einsum is AWESOME
    masks = np.einsum('ij,k', weights_norm, np.ones(nbin))
    masks = np.einsum('j,ikl', np.ones(npol), masks)
    #These are the data free of zapped channels and subints
    subintsx = [np.compress(weights_norm[ii], subints[ii], axis=1) for ii in
            xrange(nsub)]
    #The channel center frequencies for the non-zapped subints
    freqsxs = [np.compress(weights_norm[ii], freqs) for ii in xrange(nsub)]
    #The rest is now ignoring npol...
    arch.pscrunch()
    #Estimate noise -- FIX needs improvement
    noise_std = np.array([get_noise(subints[ii,0]) for ii in xrange(nsub)])
    if flux_prof:
        #Flux profile
        #The below is about equal to bscrunch to ~6 places
        arch.dedisperse()
        arch.tscrunch()
        flux_prof = arch.get_data().mean(axis=3)[0][0]
        #Non-zapped data
        flux_profx = np.compress(arch.get_weights()[0], flux_prof)
    else:
        flux_prof = np.array([])
        flux_profx = np.array([])
    #Get pulse profile
    arch.tscrunch()
    arch.fscrunch()
    prof = arch.get_data()[0,0,0]
    #Number unzapped channels, subints
    nchanx = int(round(np.mean([subintsx[ii].shape[1] for ii in
        xrange(nsub)])))
    nsubx = int(np.compress([subintsx[ii].shape[1] for ii in xrange(nsub)],
            np.ones(nsub)).sum())
    if not quiet:
        print "\tcenter freq. [MHz] = %.5f\n\
        bandwidth [MHz]    = %.1f\n\
        # bins in prof     = %d\n\
        # channels         = %d\n\
        # chan (mean)      = %d\n\
        # subints          = %d\n\
        # unzapped subint  = %d"%(nu0, bw, nbin, nchan, nchanx, nsub, nsubx)
    #Returns refreshed arch; could be changed...
    arch.refresh()
    #Return getitem/attribute-accessible class!
    data = DataBunch(arch=arch, bw=bw, flux_prof=flux_prof,
            flux_profx=flux_profx, freqs=freqs, freqsxs=freqsxs,
            masks=masks, epochs=epochs, nbin=nbin, nchan=nchan,
            nchanx=nchanx, noise_std=noise_std, nsub=nsub, nsubx=nsubx,
            nu0=nu0, phases=phases, prof=prof, Ps=Ps, source=source,
            subints=subints, subintsx=subintsx, weights=weights_norm)
    return data

def plot_lognorm(mu, tau, lo=0.0, hi=5.0, npts=500, plot=1, show=0):
    """
    """
    import pymc as pm
    pts = np.empty(npts)
    xs = np.linspace(lo, hi, npts)
    for ii in xrange(npts):
        pts[ii] = np.exp(pm.lognormal_like(xs[ii], mu, tau))
    if plot:
        plt.plot(xs, pts)
    if show:
        plt.show()
    return xs, pts

def plot_gamma(alpha, beta, lo=0.0, hi=5.0, npts=500, plot=1, show=0):
    """
    """
    import pymc as pm
    pts = np.empty(npts)
    xs = np.linspace(lo, hi, npts)
    for ii in xrange(npts):
        pts[ii] = np.exp(pm.gamma_like(xs[ii], alpha, beta))
    if plot:
        plt.plot(xs, pts)
    if show:
        plt.show()
    return xs, pts

def DM_delay(DM, freq, freq2=np.inf, P=None):
    """
    Calculates the delay [s] of emitted frequency freq [MHz] from 
    dispersion measure DM [cm**-3 pc] relative to freq2 [default=inf].
    If a period P [s] is provided, the delay is returned in phase, 
    otherwise in seconds.
    """
    delay = Dconst * DM * ((freq**-2) - (freq2**-2))
    if P:
        return delay / P
    else:
        return delay

def write_princeton_toa(toa_MJDi, toa_MJDf, toaerr, freq, DM, obs='@',
        name=' ' * 13):
    """
    Ripped and altered from PRESTO

    Princeton Format

    columns     item
    1-1     Observatory (one-character code) '@' is barycenter
    2-2     must be blank
    16-24   Observing frequency (MHz)
    25-44   TOA (decimal point must be in column 30 or column 31)
    45-53   TOA uncertainty (microseconds)
    69-78   DM correction (pc cm^-3)
    """
    #Splice together the fractional and integer MJDs
    toa = "%5d"%int(toa_MJDi) + ("%.13f"%toa_MJDf)[1:]
    if DM != 0.0:
        print obs + " %13s %8.3f %s %8.3f              %9.5f"%(name, freq, toa,
                toaerr, DM)
    else:
        print obs + " %13s %8.3f %s %8.3f"%(name, freq, toa, toaerr)

def doppler_correct_freqs(freqs, doppler_factor):
    """
    Input topocentric frequencies, output barycentric frequencies.
    doppler_factor = nu_source / nu_observed = sqrt( (1+beta) / (1-beta)),
    for beta = v/c, and v is positive for increasing source distance.
    NB: PSRCHIVE defines doppler_factor as the inverse of the above.
    """
    return doppler_factor * freqs

def fft_rotate(arr, bins):
    """
    Ripped and altered from PRESTO

    Return array 'arr' rotated by 'bins' places to the left.
    The rotation is done in the Fourier domain using the Shift Theorem.            'bins' can be fractional.
    The resulting vector will have the same length as the original.
    """
    arr = np.asarray(arr)
    freqs = np.arange(arr.size/2 + 1, dtype=np.float)
    phasor = np.exp(complex(0.0, 2*np.pi) * freqs * bins / float(arr.size))
    return np.fft.irfft(phasor * np.fft.rfft(arr), arr.size)

def show_port(port, phases=None, freqs=None, title=None, rvrsd=False,
        colorbar=True, savefig=False, aspect="auto", interpolation="none",
        origin="lower", extent=None, **kwargs):
    """
    """
    if freqs is None:
        freqs = np.arange(len(port))
        ylabel = "Channel Number"
    else:
        ylabel = "Frequency [MHz]"
    if phases is None:
        phases = np.arange(len(port[0]))
        xlabel = "Bin Number"
    else:
        xlabel = "Phase [rot]"
    if extent is None:
        extent = (phases[0], phases[-1], freqs[0], freqs[-1])
    if rvrsd:
        port = port[::-1]
        if extent is None:
            extent = (phases[0], phases[-1], freqs[-1], freqs[0])
    fig = plt.figure()
    plt.imshow(port, aspect=aspect, origin=origin, extent=extent,
            interpolation=interpolation, **kwargs)
    if colorbar: plt.colorbar()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if title: plt.title(title)
    if savefig:
        plt.savefig(savefig, format='png')
        plt.close()
    else:
        plt.show()

def show_residual_plot(port, model, resids=None, phases=None, freqs=None,
        titles=(None,None,None), rvrsd=False, colorbar=True, savefig=False,
        aspect="auto", interpolation="none", origin="lower", extent=None,
        **kwargs):
    """
    """
    if freqs is None:
        freqs = np.arange(len(port))
        ylabel = "Channel Number"
    else:
        ylabel = "Frequency [MHz]"
    if phases is None:
        phases = np.arange(len(port[0]))
        xlabel = "Bin Number"
    else:
        xlabel = "Phase [rot]"
    if extent is None:
        extent = (phases[0], phases[-1], freqs[0], freqs[-1])
    if rvrsd:
        port = port[::-1]
        model = model[::-1]
        if extent is None:
            extent = (phases[0], phases[-1], freqs[-1], freqs[0])
    fig = plt.figure()
    plt.subplot(221)
    plt.imshow(port, aspect=aspect, origin=origin, extent=extent,
            interpolation=interpolation, **kwargs)
    if colorbar: plt.colorbar()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if titles[0] is None:
        plt.title("")
    else:
        plt.title(titles[0])
    plt.subplot(222)
    plt.imshow(model, aspect=aspect, origin=origin, extent=extent,
            interpolation=interpolation, **kwargs)
    if colorbar: plt.colorbar()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if titles[1] is None:
        plt.title("")
    else:
        plt.title(titles[1])
    plt.subplot(223)
    if resids is None: resids = port - model
    plt.imshow(resids, aspect=aspect, origin=origin, extent=extent,
            interpolation=interpolation, **kwargs)
    if colorbar: plt.colorbar()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if titles[2] is None:
        plt.title("")
    else:
        plt.title(titles[2])
    plt.subplot(224)
    weights = port.mean(axis=1)
    portx = np.compress(weights, resids, axis=0)
    residsx = np.compress(weights, resids, axis=0)
    text =  "Residuals mean ~ %.3f\nResiduals std ~  %.3f\nData std ~       %.3f"%(residsx.mean(), residsx.std(), get_noise(portx))
    plt.text(0.5, 0.5, text, ha="center", va="center")
    if savefig:
        plt.savefig(savefig, format='png')
        plt.close()
    else:
        plt.show()

#This does not work yet; just for reference
def unpack_dict(data):
    """
    Dictionary has to be named 'data'...
    """
    for key in data.keys():
        exec(key + " = data['" + key + "']")

def make_fake_pulsar(datafile, modelfile, parfile, nsub, npol, nchan, nbin,
        nu0, bw, phase, noise_std):
    """
    Needs scintillation, RFI, weights, etc.  Most info in the written arch will
    be false.  Should implement as a Class?
    """
    DM = 0.0
    P = 0.0
    parfile = open(parfile,'r').readlines()
    for xx in range(len(parfile)):
        line = parfile[xx].split()
        if line[0] == 'DM':
            DM = float(line[1])
        elif line[0] == 'F0':
            P = 1/np.double(line[1])
        elif line[0] == 'P0':
            P = np.double(line[1])
        else:
            pass
        if DM and P:
            break
    chanwidth = bw / nchan
    lofreq = nu0 - (bw/2)
    freqs = np.linspace(lofreq + (chanwidth/2.0), lofreq + bw -
            (chanwidth/2.0), nchan)
    phases = np.linspace(0.0 + (nbin*2)**-1, 1.0 - (nbin*2)**-1, nbin)
    name, ngauss, model = read_model(modelfile, phases, freqs, quiet=False)
    port = rotate_portrait(model, -phase, -DM, P, freqs, nu0) + np.reshape(
            np.random.normal(0.0, noise_std, nchan*nbin), (nchan, nbin))
    arch = pr.Archive_load(datafile)
    arch.set_ephemeris(parfile)
    if nsub == 1: arch.tscrunch()
    if npol == 1: arch.pscrunch()
    for yy in xrange(nchan):
        for xx in xrange(nbin):
            arch.get_Integration(0).get_Profile(0,yy)[xx] = port[yy,xx]
    I = arch.get_Integration(0)
    #arch.set_dispersion_measure(DM)
    arch.dededisperse()
    arch.set_dedispersed(False)
    arch.unload()
    print "\nUnloaded %s.\n"%datafile
