import hashlib
import sys

import pytest


def test_disabled_configuration_never_requires_engine(tmp_path):
    from platform_core.smart_material_audit import audit_configuration, require_enabled
    assert audit_configuration(tmp_path)["enabled"] is False
    with pytest.raises(ValueError, match="SMART_AUDIT_DISABLED"):
        require_enabled(tmp_path)
    assert "fiftyone" not in sys.modules
    assert not list(tmp_path.iterdir())


def test_manifest_rejects_duplicate_ids_and_unknown_feature(tmp_path):
    from platform_core.smart_material_audit.contract import validate_manifest
    source = tmp_path / "a.png"
    source.write_bytes(b"test-only")
    image = dict(image_id="a", path=str(source), content_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    value = dict(project_id="project", task_id="task", feature="hog-color-v1", images=[image])
    assert validate_manifest(value)["images"] == [image]
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(dict(value, images=[image, image]))
    with pytest.raises(ValueError, match="feature"):
        validate_manifest(dict(value, feature="download-a-model"))


@pytest.mark.parametrize("enabled", ["true", 1, [], {}])
def test_feature_flag_must_be_explicit_boolean(tmp_path, enabled):
    import json
    from platform_core.smart_material_audit import audit_configuration
    (tmp_path / "smart_material_audit.json").write_text(json.dumps({"enabled": enabled}))
    with pytest.raises(ValueError, match="boolean"):
        audit_configuration(tmp_path)


def test_engine_network_guard_rejects_external_dns_without_loading_engine():
    import socket
    from platform_core.smart_material_audit.engine import _local_connections_only
    original = socket.getaddrinfo
    with _local_connections_only():
        with pytest.raises(PermissionError, match="SMART_AUDIT_OFFLINE"):
            socket.getaddrinfo("example.com", 443)
        assert socket.getaddrinfo("127.0.0.1", 12345)
    assert socket.getaddrinfo is original
    assert "fiftyone" not in sys.modules


def test_enabled_analysis_rejects_platform_python_environment(tmp_path):
    import json
    from platform_core.smart_material_audit import require_enabled
    (tmp_path / "smart_material_audit.json").write_text(json.dumps({"enabled": True, "python": sys.executable}))
    with pytest.raises(ValueError, match="独立"):
        require_enabled(tmp_path)
