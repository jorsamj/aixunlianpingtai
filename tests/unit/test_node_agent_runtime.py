from __future__ import annotations

import pytest

from platform_core.node_agent_runtime import (
    build_heartbeat_payload,
    normalize_agent_capabilities,
    parse_nvidia_smi_gpus,
    parse_nvidia_smi_processes,
)


def test_nvidia_smi_gpu_parser_preserves_resource_truth():
    rows = parse_nvidia_smi_gpus(
        "0, GPU-abc, NVIDIA A800-SXM4-40GB, 40960, 1024, 39936, 17, 45\n"
    )
    assert rows == [{
        "index": 0,
        "id": "cuda:0",
        "uuid": "GPU-abc",
        "name": "NVIDIA A800-SXM4-40GB",
        "memory_total_bytes": 40960 * 1024 * 1024,
        "memory_used_bytes": 1024 * 1024 * 1024,
        "memory_free_bytes": 39936 * 1024 * 1024,
        "utilization_percent": 17,
        "temperature_c": 45,
    }]


def test_nvidia_smi_process_parser_reports_pid_and_vram():
    rows = parse_nvidia_smi_processes("2345, GPU-abc, 512, python\n")
    assert rows[0]["pid"] == 2345
    assert rows[0]["used_memory_bytes"] == 512 * 1024 * 1024
    assert rows[0]["process_name"] == "python"


def test_agent_capability_contract_matches_control_plane():
    assert normalize_agent_capabilities(["training", "material-import", "training"]) == [
        "material-import",
        "training",
    ]
    with pytest.raises(ValueError):
        normalize_agent_capabilities(["training", "unknown"])


def test_heartbeat_payload_keeps_desired_and_observed_state_separate():
    payload = build_heartbeat_payload(
        {
            "host": {
                "hostname": "gpu-node",
                "os_name": "Linux",
                "os_version": "Ubuntu 22.04",
                "architecture": "x86_64",
            },
            "resources": {"cpu": {"logical_cores": 16}},
            "runtime": {"torch_version": "2.5.0+cu124"},
            "process": {"pid": 99},
        },
        capabilities=["training", "conversion"],
        build_id="build-x",
        active_tasks=["train_1", "train_1", "convert_2"],
    )
    assert payload["reported_capabilities"] == ["conversion", "training"]
    assert payload["active_tasks"] == ["train_1", "convert_2"]
    assert payload["resources"]["cpu"]["logical_cores"] == 16
    assert payload["build_id"] == "build-x"
