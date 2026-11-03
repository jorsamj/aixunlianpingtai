"""No production services or PyTorch required to verify discovery safety."""

from __future__ import annotations

import tempfile
import unittest
import importlib.util
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "platform_core" / "mother_model_inventory.py"
_SPEC = importlib.util.spec_from_file_location("mother_model_inventory_isolated", _SOURCE)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
AgentMotherModelInventory = _MODULE.AgentMotherModelInventory
project_node_inventory = _MODULE.project_node_inventory
scan_mother_models = _MODULE.scan_mother_models


class MotherModelInventoryTests(unittest.TestCase):
    def test_no_roots_means_no_implicit_machine_scan(self):
        inventory = scan_mother_models(["", "/no-such-model-location"])
        self.assertEqual(inventory["status"], "NOT_CONFIGURED")
        self.assertEqual(inventory["scanned_dirs"], 0)
        self.assertEqual(inventory["items"], [])

    def test_detects_unverified_models_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "allowed"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "secret.pt").write_bytes(b"1" * 2048)
            (root / "ok.PT").write_bytes(b"0" * 2048)
            (root / "empty.pt").touch()
            (root / "other.onnx").write_bytes(b"0" * 2048)
            (root / "link").symlink_to(outside, target_is_directory=True)
            (root / "bad.pt").symlink_to(outside / "secret.pt")

            report = scan_mother_models([root])
            self.assertEqual(report["status"], "COMPLETED")
            self.assertEqual(len(report["items"]), 1)
            self.assertEqual(report["items"][0]["name"], "ok.PT")
            self.assertEqual(report["items"][0]["status"], "DISCOVERED_UNVERIFIED")
            self.assertFalse(report["items"][0]["trainable"])

    def test_limits_depth_and_file_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            (deep / "hidden.pt").write_bytes(b"m" * 2048)
            for index in range(3):
                (root / f"{index}.pt").write_bytes(b"x" * 2048)
            shallow = scan_mother_models([root], max_depth=1)
            self.assertFalse(any(row["name"] == "hidden.pt" for row in shallow["items"]))
            limited = scan_mother_models([root], max_models=2)
            self.assertEqual(len(limited["items"]), 2)
            self.assertTrue(limited["truncated"])

    def test_background_inventory_without_roots_is_nonblocking(self):
        inventory = AgentMotherModelInventory([])
        self.assertEqual(inventory.snapshot()["status"], "NOT_CONFIGURED")

    def test_projection_preserves_offline_status_but_never_trains(self):
        report = {"status": "COMPLETED", "items": [{"name": "a.pt", "path": "/models/a.pt",
                      "size_bytes": 3000, "trainable": True, "status": "VERIFIED"}]}
        nodes = [
            {"connection_mode": "local", "node_id": "controller", "runtime": {"mother_model_inventory": report}},
            {"connection_mode": "agent", "node_id": "gpu1", "online": True,
             "display_name": "GPU node", "runtime": {"mother_model_inventory": report}},
            {"connection_mode": "agent", "node_id": "gpu2", "online": False,
             "runtime": {"mother_model_inventory": report}},
        ]
        projected = project_node_inventory(nodes)
        self.assertEqual(len(projected), 2)
        self.assertEqual(projected[0]["status"], "COMPLETED")
        self.assertEqual(projected[0]["items"][0]["status"], "DISCOVERED_UNVERIFIED")
        self.assertFalse(projected[0]["items"][0]["trainable"])
        self.assertEqual(projected[1]["status"], "OFFLINE")


if __name__ == "__main__":
    unittest.main()
