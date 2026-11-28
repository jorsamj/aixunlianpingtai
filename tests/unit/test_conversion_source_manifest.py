"""Immutable model source manifest: digest stability, tamper evidence, fail-closed."""
import json

import pytest

from platform_core.conversion import (
    SOURCE_MANIFEST_MUTABLE_FIELDS,
    build_source_manifest,
    canonical_json_bytes,
    source_manifest_digest,
    source_manifest_summary,
    validate_target,
    verify_source_manifest_digest,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
ONNX_SHA = "c" * 64


def _source(**overrides):
    value = {"sha256": SHA_A, "size_bytes": 1024, "file_name": "best.pt",
             "algorithm_id": "a1", "version_id": "v1", "artifact_id": "art-1",
             "label_codes": ["smoke", "fire"],
             "label_schema": [{"class_id": 0, "code": "smoke"}, {"class_id": 1, "code": "fire"}],
             "training_lineage": {"task_id": "t1", "parameters": {"actual": {"imgsz": 640}}},
             "sha256_recheck": {"status": "matched", "recorded_sha256": SHA_A, "reason": ""}}
    value.update(overrides)
    return value


def _export(**overrides):
    value = {"opset": 12, "dynamic": False, "simplify": False, "batch": 1,
             "imgsz": [384, 640], "precision": "fp16", "half": False,
             "reused_existing_onnx": False}
    value.update(overrides)
    return value


def _tool(**overrides):
    value = {"name": "ultralytics-export", "version": "8.4.127", "python_path": "python",
             "dependencies": {"torch": "2.12.1+cpu", "ultralytics": "8.4.127",
                              "onnx": "1.22.0", "onnxruntime": "1.29.0"}}
    value.update(overrides)
    return value


def _onnx(**overrides):
    value = {"name": "model.onnx", "sha256": ONNX_SHA, "size_bytes": 2_000_000,
             "opset_imports": {"": 12}, "input_shapes": [[1, 3, 384, 640]],
             "input_types": ["tensor(float)"], "input_names": ["images"],
             "output_shapes": [[1, 84, 8400]], "output_types": ["tensor(float)"],
             "output_names": ["output0"], "output_inferred_shapes": [[1, 84, 8400]],
             "output_dtypes": ["float32"], "floating_tensor_types": ["FLOAT"]}
    value.update(overrides)
    return value


def _outputs():
    return [{"name": "model.onnx", "sha256": ONNX_SHA, "size_bytes": 2_000_000},
            {"name": "model.bmodel", "sha256": SHA_B, "size_bytes": 512}]


def _manifest(**overrides):
    arguments = dict(source=_source(), export=_export(), tool=_tool(),
                     onnx=_onnx(), outputs=_outputs())
    arguments.update(overrides)
    return build_source_manifest(**arguments)


def test_digest_is_stable_for_field_insertion_order_and_repeatable():
    first = _manifest()
    second = build_source_manifest(
        source=dict(reversed(list(_source().items()))),
        export=dict(reversed(list(_export().items()))),
        tool=dict(reversed(list(_tool().items()))),
        onnx=dict(reversed(list(_onnx().items()))),
        outputs=[dict(reversed(list(record.items()))) for record in _outputs()],
    )
    assert source_manifest_digest(first) == source_manifest_digest(second)
    # Output list order stays part of the identity (a reordered list is a
    # different evidence ordering, unlike JSON object key order).
    reordered = _manifest(outputs=list(reversed(_outputs())))
    assert source_manifest_digest(reordered) != source_manifest_digest(first)
    assert verify_source_manifest_digest({**first, "manifest_digest": source_manifest_digest(first)})["valid"]
    # The digest of the bare document is stable across calls (no clocks/ids).
    assert source_manifest_digest(_manifest()) == source_manifest_digest(_manifest())


def test_mutable_delivery_state_never_changes_digest():
    manifest = _manifest()
    digest = source_manifest_digest(manifest)
    mutable = {
        "status": "hardware_verified", "hardware_verified": True,
        "created_at": "2026-11-24T00:00:00+00:00", "job_id": "job-1",
        "validation_status": "hardware_verified", "runtime_verified": True,
        "hardware_verification": {"chip": "rk3568", "verified_at": "now"},
        "numeric_status": "consistent", "publication_status": "blocked_hardware_unverified",
        "numeric_validation": {"verdict": "consistent"}, "execution_evidence": {"x": 1},
        "sophon_validation": {"structure": "passed"}, "manifest_digest": "d" * 64,
        "manifest_integrity": {"status": "digest_verified"}, "legacy_manifest": True,
    }
    for key in mutable:
        assert key in SOURCE_MANIFEST_MUTABLE_FIELDS, key
    changed = {**manifest, **mutable}
    assert source_manifest_digest(changed) == digest
    assert source_manifest_digest(manifest) == digest


@pytest.mark.parametrize("mutate", [
    lambda document: document["source"].__setitem__("sha256", SHA_B),
    lambda document: document["source"].__setitem__("size_bytes", 2048),
    lambda document: document["onnx"].__setitem__("sha256", SHA_A),
    lambda document: document["outputs"][1].__setitem__("sha256", SHA_A),
    lambda document: document["export"].__setitem__("opset", 13),
    lambda document: document["tool"].__setitem__("version", "9.9.9"),
])
def test_tampered_source_or_onnx_identity_changes_digest(mutate):
    manifest = _manifest()
    digest = source_manifest_digest(manifest)
    mutate(manifest)
    assert source_manifest_digest(manifest) != digest
    assert verify_source_manifest_digest({**manifest, "manifest_digest": digest})["valid"] is False


def test_recorded_digest_must_match_recomputation():
    manifest = _manifest()
    digest = source_manifest_digest(manifest)
    checked = verify_source_manifest_digest({**manifest, "manifest_digest": digest})
    assert checked["present"] and checked["valid"] and checked["reason"] == ""
    tampered = {**manifest, "manifest_digest": "f" * 64}
    wrong = verify_source_manifest_digest(tampered)
    assert wrong["present"] and wrong["valid"] is False and "不一致" in wrong["reason"]
    legacy = verify_source_manifest_digest(manifest)
    assert legacy["present"] is False and legacy["valid"] is False and "旧历史" in legacy["reason"]


@pytest.mark.parametrize("field", ["source", "export", "tool", "outputs"])
def test_missing_required_contract_fails_closed(field):
    arguments = dict(source=_source(), export=_export(), tool=_tool(),
                     onnx=_onnx(), outputs=_outputs())
    if field == "outputs":
        arguments["outputs"] = []
    else:
        arguments.pop(field)
    with pytest.raises((TypeError, ValueError)):
        build_source_manifest(**arguments)


@pytest.mark.parametrize("section,key,value", [
    ("source", "sha256", ""), ("source", "sha256", "not-a-digest"),
    ("source", "size_bytes", 0), ("source", "file_name", ""),
    ("export", "imgsz", [384]),
    ("outputs", "sha256", "0" * 63),
])
def test_invalid_identity_fields_fail_closed(section, key, value):
    if section == "outputs":
        outputs = _outputs()
        outputs[0][key] = value
        with pytest.raises(ValueError):
            _manifest(outputs=outputs)
        return
    document = {"source": _source(), "export": _export(), "tool": _tool(),
                "onnx": _onnx(), "outputs": _outputs()}
    document[section][key] = value
    with pytest.raises(ValueError):
        build_source_manifest(**document)


def test_missing_tool_name_and_empty_onnx_root_fail_closed():
    with pytest.raises(ValueError, match="tool.name"):
        _manifest(tool=_tool(name=""))
    with pytest.raises(ValueError, match="onnx.sha256"):
        _manifest(onnx=_onnx(sha256=""))


def test_onnx_absent_is_explicit_not_a_silent_default():
    manifest = _manifest(onnx=None)
    assert manifest["onnx"]["status"] == "not_available"
    assert "reason" in manifest["onnx"]
    assert source_manifest_digest(manifest) == source_manifest_digest(_manifest(onnx=None))


def test_canonical_json_is_stable_for_boundary_numbers_and_unicode():
    value = {"z": 2 ** 63 - 1, "a": 1 / 255, "unicode": "畅联云-模型",
             "nested": [{"b": -0.0, "a": 1e-300}, [None, True]], "big": [i for i in range(2000)]}
    first, second = canonical_json_bytes(value), canonical_json_bytes(
        {"big": list(range(2000)), "nested": [{"a": 1e-300, "b": -0.0}, [None, True]],
         "unicode": "畅联云-模型", "a": 1 / 255, "z": 2 ** 63 - 1})
    assert first == second
    assert b" " not in first and b"\n" not in first
    assert "畅联云-模型".encode("utf-8") in first
    with pytest.raises(ValueError):
        canonical_json_bytes({"bad": float("nan")})
    with pytest.raises(ValueError):
        canonical_json_bytes({"bad": object()})


def test_large_outputs_are_digested_and_summary_is_bounded():
    outputs = [{"name": f"part-{index}.onnx", "sha256": f"{index:064x}", "size_bytes": index + 1}
               for index in range(200)]
    manifest = _manifest(outputs=outputs)
    digest = source_manifest_digest(manifest)
    assert len(digest) == 64
    summary = source_manifest_summary({**manifest, "manifest_digest": digest})
    assert len(summary["outputs"]) == 64 and summary["outputs_truncated"] is True
    assert summary["manifest_digest"] == digest
    assert summary["onnx"]["input_shapes"] == [[1, 3, 384, 640]]
    # Bounded summary stays JSON-serializable without source-of-truth drift.
    assert json.loads(json.dumps(summary, sort_keys=True))["source"]["sha256"] == SHA_A
    oversized = [{"name": f"part-{index}.onnx", "sha256": "0" * 64, "size_bytes": 1}
                 for index in range(513)]
    with pytest.raises(ValueError, match="512"):
        _manifest(outputs=oversized)


def test_huge_training_lineage_is_bounded_but_identity_changes_are_evident():
    small = _manifest()
    huge = _manifest(source=_source(training_lineage={"payload": "x" * 200_000}))
    assert huge["source"]["training_lineage"]["status"] == "truncated"
    assert huge["source"]["training_lineage"]["sha256"]
    assert source_manifest_digest(huge) != source_manifest_digest(small)
    different = _manifest(source=_source(training_lineage={"payload": "x" * 200_001}))
    assert source_manifest_digest(different) != source_manifest_digest(huge)


def test_new_conversion_requests_freeze_the_manifest_schema():
    for target, params in (
        ("onnx", {}),
        ("sophon", {"chip": "bm1684x", "precision": "fp16"}),
        ("rockchip", {"chip": "rk3568", "precision": "fp16"}),
        ("ascend", {"soc_version": "Ascend310P3", "precision": "fp16"}),
        ("tensorrt", {"precision": "fp16", "target_environment": "gpu/cuda/trt"}),
    ):
        resolved = validate_target(target, params)
        assert resolved["source_manifest_schema"] == 1, target
    # `validate_target` still rejects invalid contracts exactly as before.
    with pytest.raises(ValueError):
        validate_target("rockchip", {"chip": "rk3588", "precision": "fp16"})
