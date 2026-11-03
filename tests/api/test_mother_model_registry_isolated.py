"""Standard-library-only proof that PT registration never runs untrusted code."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from platform_core.mother_model_assets import (
    asset_selection, initial_asset, list_assets, put_asset,
    verify_checkpoint_in_sandbox,
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


if __name__ == "__main__":
    unittest.main()
