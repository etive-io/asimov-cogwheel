"""Tests for asimov_cogwheel.asimov."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Mock runtime dependencies that are not available in the dev/CI environment.
# htcondor must be in sys.modules before any asimov import because asimov
# loads all registered pipeline entry-points at import time, and some of
# those plugins import htcondor at module scope. cogwheel/gwpy/lalsuite are
# heavy scientific dependencies not needed to exercise the asimov glue code.
# ---------------------------------------------------------------------------
for _mod in (
    "htcondor",
    "htcondor.dags",
    "htcondor2",
    "otter",
    "cogwheel",
    "cogwheel.data",
    "cogwheel.sampling",
    "cogwheel.likelihood",
    "cogwheel.posterior",
    "gwpy",
    "gwpy.timeseries",
    "gwpy.frequencyseries",
):
    sys.modules.setdefault(_mod, MagicMock())

# Mock asimov.pipelines (the entry-point registry) before importing
# asimov_cogwheel. When asimov loads, it discovers all registered
# asimov.pipelines entry-points. Because asimov_cogwheel is one of those
# entry-points, loading it while it is mid-initialisation causes a circular
# import AttributeError. A pre-populated stub breaks the cycle without
# affecting the module under test.
_stub_pipelines = MagicMock()
_stub_pipelines.known_pipelines = {}
sys.modules.setdefault("asimov.pipelines", _stub_pipelines)

from asimov.pipeline import PipelineException  # noqa: E402
from asimov_cogwheel.asimov import Cogwheel  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG = {
    ("pipelines", "environment"): "/opt/conda/envs/test",
    ("project", "root"): "/project",
    ("general", "webroot"): "public_html",
    ("condor", "user"): "testuser",
    ("condor", "scheduler"): "test-scheduler.ligo.org",
}


def _config_get(section, option, **kwargs):
    return _CONFIG.get((section, option), "")


def make_production(rundir="/working/GW150914/Prod0", meta=None):
    """Return a MagicMock production with a realistic meta structure for
    Cogwheel."""
    production = MagicMock()
    production.name = "Prod0"
    production.category = "analyses"
    production.pipeline = "cogwheel"
    production.rundir = rundir
    production.event.name = "GW150914"
    production.event.repository.directory = "/repo/GW150914"
    production.event.repository.find_prods.return_value = ["analyses/Prod0.ini"]

    default_meta = {
        "scheduler": {"accounting group": "ligo.dev.o4.cbc.pe.bilby"},
    }
    if meta is not None:
        default_meta.update(meta)
    production.meta = default_meta

    return production


# ---------------------------------------------------------------------------
# TestCogwheelInit
# ---------------------------------------------------------------------------

class TestCogwheelInit(unittest.TestCase):

    def setUp(self):
        self.production = make_production()

    def test_production_attribute(self):
        pipeline = Cogwheel(self.production)
        self.assertIs(pipeline.production, self.production)

    def test_category_defaults_to_production_category(self):
        pipeline = Cogwheel(self.production)
        self.assertEqual(pipeline.category, self.production.category)

    def test_pipeline_mismatch_raises(self):
        self.production.pipeline = "lalinference"
        with self.assertRaises(PipelineException):
            Cogwheel(self.production)

    def test_pipeline_mismatch_is_case_insensitive_check(self):
        self.production.pipeline = "Cogwheel"
        Cogwheel(self.production)  # should not raise

    def test_logger_set(self):
        pipeline = Cogwheel(self.production)
        self.assertIsNotNone(pipeline.logger)

    def test_config_template_is_a_real_bundled_file(self):
        pipeline = Cogwheel(self.production)
        self.assertTrue(os.path.exists(pipeline.config_template))


# ---------------------------------------------------------------------------
# TestCogwheelDetectCompletion
# ---------------------------------------------------------------------------

class TestCogwheelDetectCompletion(unittest.TestCase):

    def setUp(self):
        self.production = make_production()
        self.pipeline = Cogwheel(self.production)

    def test_no_results_file_returns_false(self):
        with patch("asimov_cogwheel.asimov.glob.glob", return_value=[]):
            self.assertFalse(self.pipeline.detect_completion())

    def test_posterior_samples_present_returns_true(self):
        with patch(
            "asimov_cogwheel.asimov.glob.glob",
            return_value=["/working/GW150914/Prod0/posterior_samples.h5"],
        ):
            self.assertTrue(self.pipeline.detect_completion())


# ---------------------------------------------------------------------------
# TestCogwheelBuildDag
# ---------------------------------------------------------------------------

class TestCogwheelBuildDag(unittest.TestCase):

    def setUp(self):
        self.production = make_production(rundir="/working/GW150914/Prod0")

        self.mock_config = patch("asimov_cogwheel.asimov.config").start()
        self.mock_config.get.side_effect = _config_get

        self.mock_dags = patch("asimov_cogwheel.asimov.dags").start()
        self.mock_dag_instance = MagicMock()
        self.mock_dags.DAG.return_value = self.mock_dag_instance

        self.mock_htcondor = patch("asimov_cogwheel.asimov.htcondor").start()

        self.addCleanup(patch.stopall)
        self.pipeline = Cogwheel(self.production)

    def test_writes_dag_with_three_chained_layers(self):
        self.pipeline.build_dag(dryrun=False)

        data_layer = self.mock_dag_instance.layer
        self.assertEqual(data_layer.call_args.kwargs["name"], "cogwheelpipe-data")

        analysis_layer = data_layer.return_value.child_layer
        self.assertEqual(
            analysis_layer.call_args.kwargs["name"], "cogwheelpipe-inference"
        )

        results_layer = analysis_layer.return_value.child_layer
        self.assertEqual(
            results_layer.call_args.kwargs["name"], "cogwheelpipe-results"
        )

    def test_submit_descriptions_use_correct_subcommands(self):
        self.pipeline.build_dag(dryrun=False)

        submit_calls = self.mock_htcondor.Submit.call_args_list
        arguments = [call.kwargs["arguments"] for call in submit_calls]

        self.assertTrue(any(arg.startswith("data --config") for arg in arguments))
        self.assertTrue(
            any(arg.startswith("inference --config") for arg in arguments)
        )
        self.assertTrue(
            any(arg.startswith("results --config") for arg in arguments)
        )

    def test_submit_descriptions_use_cogwheelpipe_executable(self):
        self.pipeline.build_dag(dryrun=False)

        submit_calls = self.mock_htcondor.Submit.call_args_list
        for call in submit_calls:
            self.assertTrue(call.kwargs["executable"].endswith("cogwheelpipe"))

    def test_accounting_group_defaults_when_missing_from_meta(self):
        self.production.meta = {}
        self.pipeline.build_dag(dryrun=False)

        submit_calls = self.mock_htcondor.Submit.call_args_list
        for call in submit_calls:
            self.assertEqual(call.kwargs["accounting_group"], "default")

    def test_accounting_group_read_from_meta_when_present(self):
        self.pipeline.build_dag(dryrun=False)

        submit_calls = self.mock_htcondor.Submit.call_args_list
        for call in submit_calls:
            self.assertEqual(
                call.kwargs["accounting_group"], "ligo.dev.o4.cbc.pe.bilby"
            )

    def test_rundir_set_from_production_when_present(self):
        self.pipeline.build_dag(dryrun=False)
        self.assertEqual(self.production.rundir, "/working/GW150914/Prod0")

    def test_rundir_defaults_when_not_set_on_production(self):
        self.production.rundir = None
        self.pipeline.build_dag(dryrun=False)
        self.assertIn(self.production.event.name, self.production.rundir)
        self.assertIn(self.production.name, self.production.rundir)

    def test_dag_written_to_rundir(self):
        self.pipeline.build_dag(dryrun=False)
        self.mock_dags.write_dag.assert_called_once()
        call_args = self.mock_dags.write_dag.call_args
        self.assertEqual(call_args[0][1], "/working/GW150914/Prod0")
        self.assertEqual(call_args.kwargs["dag_file_name"], "cogwheel.dag")


# ---------------------------------------------------------------------------
# TestCogwheelSubmitDag
#
# Regression test: asimov/cli/manage.py's `submit` command does
# `cluster_id = pipe.submit_dag(dryrun=dryrun)` and then
# `production.job_id = int(job_id_value)` -- it relies on submit_dag()'s
# *return value*, not just a `self.clusterid` side-effect assignment.
# Without a `return`, this crashes with
# TypeError: int() argument must be ... not 'NoneType'.
# ---------------------------------------------------------------------------

class TestCogwheelSubmitDag(unittest.TestCase):

    def setUp(self):
        self.production = make_production(rundir="/working/GW150914/Prod0")

        self.mock_config = patch("asimov_cogwheel.asimov.config").start()
        self.mock_config.get.side_effect = _config_get

        self.mock_set_directory = patch(
            "asimov_cogwheel.asimov.set_directory"
        ).start()
        self.mock_set_directory.return_value.__enter__ = MagicMock()
        self.mock_set_directory.return_value.__exit__ = MagicMock(return_value=False)

        self.mock_htcondor = patch("asimov_cogwheel.asimov.htcondor").start()
        self.mock_htcondor.Schedd.return_value.submit.return_value.cluster.return_value = 42

        self.addCleanup(patch.stopall)
        self.pipeline = Cogwheel(self.production)

    def test_returns_cluster_id(self):
        result = self.pipeline.submit_dag(dryrun=False)
        self.assertEqual(result, 42)

    def test_sets_clusterid_attribute(self):
        self.pipeline.submit_dag(dryrun=False)
        self.assertEqual(self.pipeline.clusterid, 42)


# ---------------------------------------------------------------------------
# TestCogwheelCollectAssets
# ---------------------------------------------------------------------------

class TestCogwheelCollectAssets(unittest.TestCase):

    def setUp(self):
        self.production = make_production()
        self.pipeline = Cogwheel(self.production)

    def test_returns_samples_key_from_samples_method(self):
        with patch.object(self.pipeline, "samples", return_value=["posterior_samples.h5"]):
            assets = self.pipeline.collect_assets()
        self.assertEqual(assets, {"samples": ["posterior_samples.h5"]})


# ---------------------------------------------------------------------------
# TestCogwheelAfterCompletion
#
# The key regression test: after_completion() used to import a
# PESummaryPipeline class from asimov.pipeline (removed from asimov core as
# of 0.7 -- every pipeline is now an installable plugin) and instantiate it
# directly, fabricating a fake PSD to feed it. PESummary post-processing is
# now a separate downstream analysis wired up via a blueprint's `needs:`
# field, so after_completion() must not reference PESummary at all.
# ---------------------------------------------------------------------------

class TestCogwheelAfterCompletion(unittest.TestCase):

    def setUp(self):
        self.production = make_production()
        self.pipeline = Cogwheel(self.production)

    def test_sets_status_finished(self):
        self.pipeline.after_completion()
        self.assertEqual(self.production.status, "finished")

    def test_calls_event_update_data(self):
        self.pipeline.after_completion()
        self.production.event.update_data.assert_called_once()

    def test_does_not_reference_pesummary_pipeline(self):
        import asimov_cogwheel.asimov as asimov_module

        self.assertFalse(hasattr(asimov_module, "PESummaryPipeline"))

    def test_does_not_fabricate_fake_psds(self):
        self.pipeline.after_completion()
        # production.psds is a MagicMock attribute unless explicitly set;
        # after_completion() must not have assigned a fake value to it.
        self.assertNotEqual(
            self.production.psds, {"L1": "fake.txt", "H1": "fake.txt"}
        )


# ---------------------------------------------------------------------------
# TestCogwheelSamples
# ---------------------------------------------------------------------------

class TestCogwheelSamples(unittest.TestCase):

    def setUp(self):
        self.production = make_production()
        self.pipeline = Cogwheel(self.production)

    def test_relative_path_by_default(self):
        with patch(
            "asimov_cogwheel.asimov.glob.glob",
            return_value=["/working/GW150914/Prod0/posterior_samples.h5"],
        ):
            self.assertEqual(
                self.pipeline.samples(),
                ["/working/GW150914/Prod0/posterior_samples.h5"],
            )

    def test_absolute_path_when_requested(self):
        with patch(
            "asimov_cogwheel.asimov.glob.glob",
            return_value=["/working/GW150914/Prod0/posterior_samples.h5"],
        ):
            result = self.pipeline.samples(absolute=True)
        self.assertEqual(result, [os.path.abspath(
            "/working/GW150914/Prod0/posterior_samples.h5"
        )])


if __name__ == "__main__":
    unittest.main()
