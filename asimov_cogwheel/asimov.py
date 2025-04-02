"""
Interfaces with asimov
"""
import importlib
import configparser
import os
from asimov import logger, config
from asimov.utils import set_directory
from asimov.pipeline import Pipeline, PipelineException, PipelineLogger

import htcondor
from htcondor import dags

class Cogwheel(Pipeline):
    """
    The Cogwheel Pipeline.

    """

    with importlib.resources.path("cogwheel", "asimov_template.yml") as template_file:
        config_template = template_file

    name = "cogwheel"

    def __init__(self, production, category=None):
        super().__init__(production, category)
        self.logger = logger

        if not production.pipeline.lower() == self.name:
            raise PipelineException


    def build_dag(self):
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

        executable = "cogwheelpipe"
        
        data_command = f"data --settings {ini}"        
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

        analysis_command = f"inference --settings {ini}"
        analysis_description = htcondor.Submit(
            executable=executable,
            arguments=analysis_command,
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
        analysis_layer = data_layer.child_layer(
            name='cogwheelpipe-inference',
            submit_description=analysis_description,
        )

        dag_file = dags.write_dag(dag, rundir)

        logger.info(f"DAG file written to {dag_file}")


    def submit_dag(self, dryrun=False):
        """
        Submit the constructed DAG file.
        """
        dag_file = "cogwheelpipe.dag"
        with set_directory(self.production.rundir):
            dag_submit = htcondor.Submit.from_dag(
                str(dag_file), {'force': 1}
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
