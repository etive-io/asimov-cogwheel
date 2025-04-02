"""
Interfaces with asimov
"""
import importlib
import configparser
import os
import glob
from asimov import logger, config
from asimov.utils import set_directory
from asimov.pipeline import Pipeline, PipelineException, PipelineLogger

import htcondor
from htcondor import dags

class Cogwheel(Pipeline):
    """
    The Cogwheel Pipeline.

    """

    with importlib.resources.path("asimov_cogwheel", "asimov_template.yaml") as template_file:
        config_template = template_file

    name = "cogwheel"
    _pipeline_command = "cogwheelpipe"

    def __init__(self, production, category=None):
        super().__init__(production, category)
        self.logger = logger

        if not production.pipeline.lower() == self.name:
            raise PipelineException


    def build_dag(self, dryrun=False):
        """
        Construct a DAG for this pipeline.
        """
        cwd = os.getcwd()
        self.logger.info(f"Working in {cwd}")

        if self.production.event.repository:
            ini = self.production.event.repository.find_prods(
                self.production.name, self.category
            )[0]
            ini = os.path.join(cwd, ini)
        else:
            ini = f"{self.production.name}.ini"

        if self.production.rundir:
            rundir = self.production.rundir
        else:
            rundir = os.path.join(
                os.path.expanduser("~"),
                self.production.event.name,
                self.production.name,
            )
            self.production.rundir = rundir

            
        dag = dags.DAG()

        executable = f"{os.path.join(config.get('pipelines', 'environment'), 'bin', self._pipeline_command)}"
        
        data_command = f"data --config {ini}"        
        data_description = htcondor.Submit(
            executable=executable,
            arguments=data_command,
            log=os.path.join(rundir, 'cogwheelpipe-data.log'),
            output=os.path.join(rundir, 'cogwheelpipe-data.out'),
            error=os.path.join(rundir, 'cogwheelpipe-data.err'),
            request_cpus='1',
            request_memory='2048MB',
            request_disk='10GB',
            getenv="True",
            accounting_group_user=config.get('condor', 'user'),
            accounting_group=self.production.meta['scheduler']["accounting group"]
        )
        data_layer = dag.layer(
            name='cogwheelpipe-data',
            submit_description=data_description
        )

        analysis_command = f"inference --config {ini}"
        analysis_description = htcondor.Submit(
            executable=executable,
            arguments=analysis_command,
            log=os.path.join(rundir, 'cogwheelpipe-inference.log'),
            output=os.path.join(rundir, 'cogwheelpipe-inference.out'),
            error=os.path.join(rundir, 'cogwheelpipe-inference.err'),
            request_cpus='1',
            request_memory='2048MB',
            request_disk='10GB',
            getenv="True",
            accounting_group_user=config.get('condor', 'user'),
            accounting_group=self.production.meta['scheduler']["accounting group"]
        )
        analysis_layer = data_layer.child_layer(
            name='cogwheelpipe-inference',
            submit_description=analysis_description,
        )

        results_command = f"results --config {ini}"
        results_description = htcondor.Submit(
            executable=executable,
            arguments=analysis_command,
            log=os.path.join(rundir, 'cogwheelpipe-results.log'),
            output=os.path.join(rundir, 'cogwheelpipe-results.out'),
            error=os.path.join(rundir, 'cogwheelpipe-results.err'),
            request_cpus='1',
            request_memory='2048MB',
            request_disk='10GB',
            getenv="True",
            accounting_group_user=config.get('condor', 'user'),
            accounting_group=self.production.meta['scheduler']["accounting group"]
        )
        results_layer = analysis_layer.child_layer(
            name='cogwheelpipe-results',
            submit_description=results_description,
        )
        
        dag_file = dags.write_dag(dag, rundir, dag_file_name="cogwheel.dag")

        logger.info(f"DAG file written to {dag_file}")


    def submit_dag(self, dryrun=False):
        """
        Submit the constructed DAG file.
        """
        dag_file = "cogwheel.dag"
        with set_directory(self.production.rundir):
            dag_submit = htcondor.Submit.from_dag(
                str(dag_file),
                {'force': 1,
                 "batch-name": f"cogwheel/{self.production.event.name}/{self.production.name}"}
            )

            try:
                schedulers = htcondor.Collector().locate(
                    htcondor.DaemonTypes.Schedd,
                    config.get("condor", "scheduler"))

            except configparser.NoOptionError:
                schedulers = htcondor.Collector().locate(
                    htcondor.DaemonTypes.Schedd
                )
            schedd = htcondor.Schedd(schedulers)
            cluster_id = schedd.submit(dag_submit).cluster()

        self.clusterid = cluster_id

    def detect_completion(self):
        """
        Check for the production of the posterior file to signal that the job has completed.
        """
        self.logger.info("Checking if the dingo job has completed")

        results_dir = glob.glob(f"{self.production.rundir}/posterior_samples.h5")
        if len(results_dir) > 0:
            self.logger.info("Results files found, the job is finished.")
            return True
        else:
            self.logger.info("No results files found.")
            return False
