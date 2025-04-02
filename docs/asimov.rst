Using cogwheel with asimov
==========================

Asimov is able to automate cogwheel analyses using its common analysis description interface.

In order to set up a cogwheel job using asimov you'll need to first create an asimov project, and add an event to your project which you'll perform the analysis on.

We've included some quick instructions for doing this here, but you can find more a more comprehensive `tutorial<https://asimov.docs.ligo.org/asimov/master/getting-started.html>`_ in the asimov documentation.


Blueprints for cogwheel
-----------------------

There are two kinds of blueprint you might want to use to configure cogwheel.
The first will set project-wide defaults for the pipeline, while the second will create individual analyses.
The blueprints for individual analyses can always overwrite the settings from the project-wide defaults.

First, the defaults blueprint should look something like this:

::
   kind: configuration
   pipelines:
     cogwheel:
       scheduler:
	 accounting group: ligo.prod.o4.cbc.pe.bilby
	 request cpus: 1
       likelihood:
         marginalisation:
	   distance: True
       priors:
         class: MarginalizedDistanceLVKPrior
       sampler:
         sampler kwargs:
	   nlive: 1000


Save this file as ``cogwheel.yaml``, and you can then configure your project to default to using these values for a cogwheel analysis by running

::
   $ asimov apply -f cogwheel.yaml


To add a new cogwheel analysis to an event in your project you'll need an analysis blueprint file.
This should look something like this:

::

   kind: analysis
   pipeline: cogwheel
   waveform:
     approximant: IMRPhenomXPHM
   likelihood:
     relative binning:
       fiducial parameters:
         chirp mass: 30
