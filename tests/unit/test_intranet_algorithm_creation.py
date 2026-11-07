"""A local algorithm remains independent when external mirroring is configured."""

from pathlib import Path

from platform_core.algorithms import create_algorithm, list_algorithms, save_algorithms
from platform_core.external_algorithm_platform import assert_algorithm_mutable
from platform_core.errors import PlatformError


def test_external_mirror_and_local_algorithms_coexist_without_network(tmp_path: Path):
    path = tmp_path / "projects" / "p1" / "algorithms.json"
    path.parent.mkdir(parents=True)
    save_algorithms(path, [{
        "id": "external-1",
        "name": "云端只读算法",
        "source_type": "EXTERNAL",
        "provider_type": "CHANGLIAN",
        "master_data_readonly": True,
        "versions": [],
    }])

    created = create_algorithm(path, {
        "name": "本地烟火检测", "industry": "消防安全", "algorithm_type": "yolo_ultralytics"
    }, "2026-11-04T00:00:00Z")
    assert created["source_type"] == "LOCAL"
    assert created["master_data_readonly"] is False
    assert_algorithm_mutable(path, created["id"])
    try:
        assert_algorithm_mutable(path, "external-1")
    except PlatformError as exc:
        assert exc.code == "EXTERNAL_ALGORITHM_READONLY"
    else:
        raise AssertionError("external mirrored algorithm must remain read-only")

    listed = list_algorithms(path)
    assert len(listed) == 2
    assert {row["source_type"] for row in listed} == {"EXTERNAL", "LOCAL"}
