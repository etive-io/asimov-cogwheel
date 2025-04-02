Configuration files for cogwheelpipe
====================================

In order to allow cogwheel to be configured in a way which asimov understands we have introduced simple configuration files for cogwheel pipe which allow the inference code to be configured in a way which is easy to reproduce.

This page provides a guide as to the format of this configuration file.

The configuration file is written in YAML format, and we will sometimes use "inline YAML" to describe it here.
That means that the following hierarchical dictionary in YAML format

::

   waveform:
     approximant: IMRPhenomXPHM

Is written as ``waveform: approximant: IMRPhenomXPHM`` in this document, in order to make things a little more concise.

Event-specific Settings
-----------------------

These settings are specific to a given gravitational wave signal.

``event: name``
  The name of the gravitational wave event, for example

  ::

     event:
       name: GW150914

  This value can be set to automatically obtain data for a given event.

``event: fiducial parameters``
  The fiducial parameters, or "best guess" parameters for the event.
  For example
  
  ::

     event:
       fiducial parameters:
         chirp mass: 30
  
Waveform settings
-----------------

These settings control the waveform approximant used in the analysis.

``waveform: approximant``
  The name of the waveform approximant to be used in the analysis, for example

  ::

     waveform:
       approximant: IMRPhenomXPHM

Sampler settings
----------------

These settings control the behaviour of the sampler.

``sampler: live points``
  The number of live points to use when sampling.
  If not specified directly a default of ``1000`` is used.


Likelihood settings
-------------------

These settings control the behaviour of the likelihood function.

``likelihood: marginalisation``
  Enable marginalisation over extrinsic parameters.

  You may need to alter your prior in order to use a marginalisation.
  
  For example, for distance marginalisation:

  ::
     likelihood:
       marginalisation:
         - distance

Prior settings
--------------

``prior: class``
  Use a specified prior class for the analysis.

  For example

  ::
     prior:
       class: CartesianintrinsicIASPrior

``prior: distributions``
  Set specific values for prior distributions.

  For example:

  ::
     prior:
       distributions:
         chirp mass:
	   minimum: 10
	   maximum: 40
