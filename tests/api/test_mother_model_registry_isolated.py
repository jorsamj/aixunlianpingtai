"""Standard-library-only proof that PT registration never runs untrusted code."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from platform_core.mother_model_assets import (
    asset_selection, initial_asset, list_assets, put_asset,
    verify_checkpoint_in_sandbox, verifier_environment_status,
    public_asset_status, _run_bounded_probe,
)


class MotherModelRegistryTests(unittest.TestCase):
    def test_fake_pt_is_recorded_but_never_selectable(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            path = home / "models" / "bad.pt"
            path.parent.mkdir()
            path.write_bytes(b"untrusted pickle-shaped bytes" * 100)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            asset = initial_asset(home, path, digest)
            self.assertEqual(asset["validation_status"], "UNVERIFIED")
            self.assertFalse(asset["trainable"])
            self.assertIsNone(asset_selection(home, asset["asset_id"]))
            self.assertEqual(verify_checkpoint_in_sandbox(path)["validation_status"], "INVALID")

    def test_index_is_idempotent_and_rejects_modified_hash_even_if_marked_verified(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            path = home / "models" / "valid.pt"
            path.parent.mkdir()
            path.write_bytes(b"w" * 2048)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            first = initial_asset(home, path, digest)
            self.assertEqual(initial_asset(home, path, digest)["asset_id"], first["asset_id"])
            self.assertEqual(len(list_assets(home)), 1)
            put_asset(home, {"asset_id": first["asset_id"], "validation_status": "VERIFIED", "trainable": True})
            self.assertIsNotNone(asset_selection(home, first["asset_id"]))
            path.write_bytes(b"x" * 2048)
            self.assertIsNone(asset_selection(home, first["asset_id"]))

    def test_torch_zip_with_nonempty_pickle_requires_sandbox(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "weights.pt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("archive/data.pkl", b"Y" * 2048)
            with patch("platform_core.mother_model_assets.shutil.which", return_value=None):
                inspected = verify_checkpoint_in_sandbox(path)
            self.assertEqual(inspected["validation_status"], "SANDBOX_UNAVAILABLE")
            self.assertFalse(inspected["trainable"])

    @unittest.skipUnless(sys.platform == "linux", "Linux bwrap paths only")
    def test_verifier_environment_reports_missing_tool_and_hidden_runtime(self):
        with patch("platform_core.mother_model_assets.shutil.which", return_value=None):
            self.assertEqual(verifier_environment_status()["code"], "PT_SANDBOX_NOT_CONFIGURED")
        with patch("platform_core.mother_model_assets.shutil.which", return_value="/usr/bin/bwrap"):
            with patch.dict("os.environ", {"MC_MOTHER_MODEL_VERIFY_PYTHON": sys.executable}):
                result = verifier_environment_status()
                self.assertIn(result["status"], {"CONFIGURED", "UNAVAILABLE"})
            with tempfile.TemporaryDirectory() as tmp:
                python = Path(tmp) / "python"
                python.write_bytes(b"executable")
                python.chmod(0o755)
                self.assertEqual(verifier_environment_status(python_executable=str(python))["code"],
                                 "PT_PYTHON_RUNTIME_NOT_ISOLATABLE")

    def test_checking_state_recovers_to_retry_without_mutating_asset(self):
        original = {"validation_status": "CHECKING", "validation_started_at": 10, "trainable": False}
        self.assertEqual(public_asset_status(original, now=190)["validation_status"], "CHECKING")
        projected = public_asset_status(original, now=200)
        self.assertEqual(projected["validation_status"], "INTERRUPTED")
        self.assertEqual(projected["validation_error"], "PT_VERIFY_INTERRUPTED")
        self.assertEqual(original["validation_status"], "CHECKING")

    @unittest.skipUnless(sys.platform == "linux", "POSIX selectors/process groups only")
    def test_harmless_probe_output_is_bounded_and_timeout_kills_child(self):
        returncode, stdout, stderr = _run_bounded_probe([sys.executable, "-I", "-c", "print('OK')"], timeout=5)
        self.assertEqual((returncode, stdout.strip(), stderr), (0, "OK", ""))
        with self.assertRaises(OverflowError):
            _run_bounded_probe([sys.executable, "-I", "-c", "print('a'*200000)"], timeout=5)
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_bounded_probe([sys.executable, "-I", "-c", "import time; time.sleep(5)"], timeout=1)

    def test_verifier_classifies_missing_dependency_and_namespace_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights.pt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("archive/data.pkl", b"Y" * 2048)
            ready = {"status": "CONFIGURED", "code": ""}
            with patch("platform_core.mother_model_assets.verifier_environment_status", return_value=ready), \
                 patch("platform_core.mother_model_assets.shutil.which", return_value="/usr/bin/bwrap"), \
                 patch("platform_core.mother_model_assets._run_bounded_probe", return_value=(44, "MODEL_PROBE_ENV:PT_VERIFY_DEPENDENCY_MISSING", "")):
                result = verify_checkpoint_in_sandbox(path)
            self.assertEqual(result["validation_error"], "PT_VERIFY_DEPENDENCY_MISSING")
            self.assertEqual(result["validation_status"], "SANDBOX_UNAVAILABLE")
            with patch("platform_core.mother_model_assets.verifier_environment_status", return_value=ready), \
                 patch("platform_core.mother_model_assets.shutil.which", return_value="/usr/bin/bwrap"), \
                 patch("platform_core.mother_model_assets._run_bounded_probe", return_value=(1, "", "bwrap: namespace operation not permitted")):
                result = verify_checkpoint_in_sandbox(path)
            self.assertEqual(result["validation_error"], "PT_SANDBOX_NOT_EXECUTABLE")
            self.assertFalse(result["trainable"])

    def test_synthetic_detector_requires_real_sandbox_success_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights.pt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("archive/data.pkl", b"Y" * 2048)
            output='MODEL_PROBE_JSON:{"names":["person","tangzhe"],"nc":2,"task":"detect","architecture":"DetectionModel","framework":"ultralytics"}'
            with patch.dict("os.environ", {"MC_MOTHER_MODEL_VERIFY_PYTHON": "/opt/changlian-model-verifier-v1/bin/python"}), \
                 patch("platform_core.mother_model_assets.verifier_environment_status", return_value={"status":"CONFIGURED"}), \
                 patch("platform_core.mother_model_assets.shutil.which", return_value="/usr/bin/bwrap"), \
                 patch("platform_core.mother_model_assets._run_bounded_probe", return_value=(0, output, "")) as runner:
                result=verify_checkpoint_in_sandbox(path)
            self.assertEqual(result["validation_status"], "VERIFIED")
            self.assertEqual(result["names"], ["person", "tangzhe"])
            command=runner.call_args.args[0]
            self.assertIn("--unshare-all", command)
            self.assertIn("--clearenv", command)
            self.assertIn("-I", command)
            self.assertIn("/opt/changlian-model-verifier-v1/bin/python", command)  # Preserve venv prefix.


if __name__ == "__main__":
    unittest.main()
