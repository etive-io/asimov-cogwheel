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
    
    parentdir = 'test'  # Directory that will contain parameter estimation runs

    config = pipeconfig.parse_config(config)
    
    eventname = config.get('event', {}).get('name', None)
    mchirp_guess = config.get('event', {}).get('fiducial parameters', {}).get('chirp mass', None)
    approximant = config.get('waveform', {}).get('approximant', None)

    logger.info("Loading strain data")
    if not data.EventData.get_filename(eventname).exists():
        logger.error("No data for this event could be found. You should run `$ cogwheelpipe data` first!")
    else:
        event_data = data.EventData.from_npz(eventname)

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
