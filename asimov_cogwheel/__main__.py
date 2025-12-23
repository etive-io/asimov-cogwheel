import logging
import os
import click
from . import __version__
from . import config as pipeconfig

@click.version_option(__version__)
@click.group()
@click.pass_context
def cogwheelpipe(ctx):
    """
    This is the main program which allows the construction of pipelines using cogwheel.
    """
    pass


@click.option("--config", help="A configuration file.")
@cogwheelpipe.command()
def data(config):
    """
    Use cogwheel's own data acquisition routines to download strain data
    from GWOSC.
    
    Note: PSDs are computed from the downloaded data using the Welch method.
    If you want to use externally provided PSDs (e.g., from BayesWave), 
    specify them in the configuration file under the 'psds' section.
    """
    from cogwheel import data
    config = pipeconfig.parse_config(config)
    eventname = config.get('event', {}).get('name', None)
    logger = logging.getLogger("cogwheelpipe.data")
    LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
    logging.basicConfig(level=LOGLEVEL, format="%(asctime)s %(message)s")
    logger.info(f"Using asimov_cogwheel {__version__}")
    logger.info(f"Getting data for {eventname}")
    
    if not data.EventData.get_filename(eventname).exists():
        filenames, detector_names, tgps = data.download_timeseries(eventname)
        ctime = config.get('event', {}).get('event time', None)
        if ctime:
            # Use the config time rather than the one from cogwheel's data files.
            tgps = ctime
        event_data = data.EventData.from_timeseries(
            filenames, eventname, detector_names, tgps, t_before=16., fmax=1024.)
        event_data.to_npz()
    else:
        logger.info("Data has already been downloaded for this event.")


@click.option("--config", help="A configuration file.")
@cogwheelpipe.command()
def inference(config):

    from cogwheel import data
    from cogwheel import sampling
    from cogwheel import likelihood
    from cogwheel.posterior import Posterior

    logger = logging.getLogger("cogwheelpipe.inference")
    LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
    logging.basicConfig(level=LOGLEVEL, format="%(asctime)s %(message)s")
    
    parentdir = "sampling"

    config = pipeconfig.parse_config(config)
    
    eventname = config.get('event', {}).get('name', None)
    mchirp_guess = config.get('event', {}).get('fiducial parameters', {}).get('chirp mass', None)
    approximant = config.get('waveform', {}).get('approximant', None)

    logger.info("Loading strain data")
    if not data.EventData.get_filename(eventname).exists():
        logger.error("No data for this event could be found. You should run `$ cogwheelpipe data` first!")
    else:
        event_data = data.EventData.from_npz(eventname)
    
    # Handle PSD files if specified
    psd_files = config.get('psds', None)
    if psd_files:
        logger.info(f"Using provided PSD files: {psd_files}")
        import numpy as np
        from scipy import interpolate
        from cogwheel.data import highpass_filter
        
        # Get whitening filter parameters from config (applies to all detectors)
        psd_config = config.get('psds', {})
        if isinstance(psd_config, dict) and 'whitening_filter' in psd_config:
            wht_params = psd_config['whitening_filter']
            fmin = wht_params.get('fmin', 15.0)
            df_taper = wht_params.get('df_taper', 1.0)
            logger.info(f"Using whitening filter parameters: fmin={fmin} Hz, df_taper={df_taper} Hz")
        else:
            # Use default cogwheel parameters
            fmin = 15.0  # Minimum frequency (Hz)
            df_taper = 1.0  # Taper width (Hz)
        
        # Get the detector index mapping
        detector_indices = {det: i for i, det in enumerate(event_data.detector_names)}
        
        for ifo, psd_file in psd_files.items():
            # Skip non-string entries (e.g., whitening_filter dict)
            if not isinstance(psd_file, str):
                continue
                
            if ifo not in detector_indices:
                logger.warning(f"Detector {ifo} not found in event data, skipping PSD file")
                continue
                
            if os.path.exists(psd_file):
                logger.info(f"Loading PSD for {ifo} from {psd_file}")
                
                try:
                    # Load PSD file - expected format is two columns: frequency, PSD value
                    psd_data = np.loadtxt(psd_file)
                    
                    # Validate PSD file format
                    if psd_data.ndim != 2 or psd_data.shape[1] < 2:
                        logger.error(f"Invalid PSD file format for {ifo}: expected 2 columns (frequency, PSD), got shape {psd_data.shape}")
                        continue
                    
                    freq_psd, psd_values = psd_data[:, 0], psd_data[:, 1]
                    
                    # Validate PSD values are positive
                    if np.any(psd_values <= 0):
                        logger.error(f"Invalid PSD values for {ifo}: PSD must be positive. Found {np.sum(psd_values <= 0)} non-positive values.")
                        continue
                    
                    # Compute ASD from PSD
                    asd_values = np.sqrt(psd_values)
                    
                except (ValueError, IOError, OSError) as e:
                    logger.error(f"Failed to load PSD file for {ifo} from {psd_file}: {e}")
                    continue
                
                # Interpolate ASD to match event_data frequencies
                asd_interp = interpolate.interp1d(
                    freq_psd, asd_values, 
                    bounds_error=False, 
                    # Use np.inf for frequencies outside PSD range. This effectively 
                    # disables whitening at those frequencies (wht_filter = highpass / asd = 0).
                    # The highpass filter will be 0 below fmin anyway.
                    fill_value=np.inf
                )
                asd_at_event_freqs = asd_interp(event_data.frequencies)
                
                # Create new whitening filter using cogwheel's highpass_filter
                # This ensures consistency with how cogwheel creates filters
                highpass = highpass_filter(event_data.frequencies, fmin, df_taper)
                new_wht_filter = highpass / asd_at_event_freqs
                
                # Update the whitening filter for this detector
                det_index = detector_indices[ifo]
                event_data.wht_filter[det_index] = new_wht_filter
                
                # Update blued_strain since wht_filter changed
                # Note: _set_strain is the internal method that properly updates blued_strain
                # There is no public API for this operation in cogwheel's EventData class
                event_data._set_strain(event_data.strain)
                
                logger.info(f"Successfully updated whitening filter for {ifo} using provided PSD")
            else:
                logger.warning(f"PSD file not found: {psd_file}")
    else:
        logger.info("No PSD files specified, will use default PSD estimation from data")

    # Include likelihood settings
    likelihood_kwargs={}
    if "distance" in config.get("likelihood", {}).get("marginalisation", []):
        logging.info("Using distance marginalisation.")
        lookup_table = likelihood.LookupTable()
        likelihood_kwargs['lookup_table'] = lookup_table

    # Construct prior kwargs
    prior_class = config.get('prior', {})\
                        .get('class', 'CartesianIntrinsicIASPrior')
    distributions = config.get("priors", {}).get("distributions", None)
    prior_kwargs = {}
    mappings = {"chirp mass": "mchirp"}
    if distributions:
        for quantity, values in distributions.items():
            if quantity == "chirp mass":
                prior_kwargs['mchirp'] = [values['minimum'], values['maximum']]
                
    post = Posterior.from_event(event_data,
                                mchirp_guess,
                                approximant,
                                prior_class=prior_class,
                                prior_kwargs=prior_kwargs,
                                likelihood_kwargs=likelihood_kwargs)

    click.echo(f"Sampling from {eventname} with {approximant}")
    
    sampler = sampling.Nautilus(post,
                                run_kwargs=dict(
                                    n_live=int(config.get('sampler').get('live points', 1000))
                                ))

    rundir = sampler.get_rundir(parentdir)
    sampler.run(rundir)  # Will take a while

@click.option("--config", help="A configuration file.")
@cogwheelpipe.command()
def results(config):
    """
    Post process the results file and convert them to PESummary-friendly values.
    """

    from pyarrow import feather

    import numpy as np
    from bilby.gw.conversion import (
        component_masses_to_chirp_mass,
        symmetric_mass_ratio_to_mass_ratio)
    from pesummary.gw.conversions.cosmology import (
        z_from_dL_exact,
        mchirp_source_from_mchirp_z)
    from pesummary.gw.conversions.spins import chi_p
    from pesummary.gw.conversions.mass import component_masses_from_mchirp_q
    from pesummary.gw import reweight
    from pesummary.utils.samples_dict import SamplesDict

    config = pipeconfig.parse_config(config)

    filename = os.path.join(
        "sampling",
        config['prior']['class'],
        config['event']['name'],
        "run_0",
        "samples.feather"
    )
    
    data = feather.read_feather(filename)
    parameters = list(data.columns)
    parameters[0] = "chirp_mass"
    data.columns = parameters
    data['mass_ratio'] = data['m2']/data['m1']
    data['spin_1x'] = data['s1x_n']
    data['spin_1y'] = data['s1y_n']
    data['spin_1z'] = data['s1z']
    data['spin_2x'] = data['s2x_n']
    data['spin_2y'] = data['s2y_n']
    data['spin_2z'] = data['s2z']
    in_range = [0<=value<=1 for value in data['mass_ratio']]
    data['luminosity_distance'] = data.pop("d_luminosity")
    data['redshift'] = z_from_dL_exact(data['luminosity_distance'])
    data['chirp_mass_source'] = mchirp_source_from_mchirp_z(data['chirp_mass'], data['redshift'])
    data['chi_eff'] = (data['spin_1z'] + data['spin_2z'] * data['mass_ratio']) / (1 + data['mass_ratio'])
    data['mass_1'] = data['m1']
    data['mass_2'] = data['m2']
    data['chi_p'] = chi_p(data['mass_1'], data['mass_2'], 
                          data['spin_1x'], data['spin_1y'], 
                          data['spin_2x'], data['spin_2y'])  
    data_dict = SamplesDict(list(data.columns), np.array(data.values).T)
    data_dict.write(file_format="pesummary", package="gw", outdir="./", label=config['label'], hdf5=True)
