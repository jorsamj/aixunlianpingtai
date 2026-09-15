from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


cache = Path("platform_core/training_bundle_cache.py")
replace_once(cache, "CACHE_SCHEMA_VERSION = 1\n", "CACHE_SCHEMA_VERSION = 2\n", "cache schema")
replace_once(
    cache,
    '''def _resolve_relative(root: Path, reference: str) -> Path:\n    relative = _portable_relative(reference)\n    base = root.resolve()\n    resolved = (base / relative).resolve()\n    if resolved != base and base not in resolved.parents:\n        raise ValueError("relative portable bundle reference required")\n    return resolved\n''',
    '''def _resolve_relative(root: Path, reference: str) -> Path:\n    relative = _portable_relative(reference)\n    base = root.resolve()\n    # Inspect the lexical path before Path.resolve() can hide an in-bundle\n    # symlink/reparse component that happens to target another in-bundle file.\n    current = base\n    for part in relative.parts:\n        current = current / part\n        if _is_link_like(current):\n            raise ValueError("portable bundle reference must not traverse a link or reparse point")\n    resolved = (base / relative).resolve()\n    if resolved != base and base not in resolved.parents:\n        raise ValueError("relative portable bundle reference required")\n    return resolved\n''',
    "lexical link guard",
)
replace_once(
    cache,
    '''        expected_snapshot = str(manifest.get("snapshot_sha256") or "")\n        if (\n            _has_link_component(bundle, snapshot_path)\n            or not snapshot_path.is_file()\n            or not expected_snapshot\n            or _sha256(snapshot_path) != expected_snapshot\n            or _has_link_component(bundle, data_yaml)\n            or not data_yaml.is_file()\n        ):\n            return None\n''',
    '''        expected_snapshot = str(manifest.get("snapshot_sha256") or "")\n        expected_data_yaml = str(marker.get("data_yaml_sha256") or "")\n        if (\n            _has_link_component(bundle, snapshot_path)\n            or not snapshot_path.is_file()\n            or not expected_snapshot\n            or _sha256(snapshot_path) != expected_snapshot\n            or _has_link_component(bundle, data_yaml)\n            or not data_yaml.is_file()\n            or not expected_data_yaml\n            or _sha256(data_yaml) != expected_data_yaml\n        ):\n            return None\n''',
    "data yaml integrity",
)
replace_once(
    cache,
    '''                    expected_size = int(member.get("size_bytes") or 0)\n                    if (\n                        _has_link_component(bundle, image_path)\n                        or not image_path.is_file()\n                        or expected_size <= 0\n                        or image_path.stat().st_size != expected_size\n                        or _has_link_component(bundle, label_path)\n                        or not label_path.is_file()\n                    ):\n                        return None\n''',
    '''                    expected_size = int(member.get("size_bytes") or 0)\n                    expected_label_sha = str(member.get("label_sha256") or "")\n                    if (\n                        _has_link_component(bundle, image_path)\n                        or not image_path.is_file()\n                        or expected_size <= 0\n                        or image_path.stat().st_size != expected_size\n                        or _has_link_component(bundle, label_path)\n                        or not label_path.is_file()\n                        or not expected_label_sha\n                        or _sha256(label_path) != expected_label_sha\n                    ):\n                        return None\n''',
    "label integrity",
)
replace_once(
    cache,
    '''                marker = {\n                    "schema_version": CACHE_SCHEMA_VERSION,\n                    "snapshot_id": sid,\n                    "manifest_sha256": _sha256(manifest_path),\n                    "verified_files": int(verified_files),\n                    "published_at": datetime.now(timezone.utc).isoformat(),\n                }\n''',
    '''                data_yaml_path = _resolve_relative(\n                    bundle, str(manifest.get("data_yaml_ref") or "")\n                )\n                if not data_yaml_path.is_file():\n                    raise ValueError("verified bundle data YAML is missing")\n                marker = {\n                    "schema_version": CACHE_SCHEMA_VERSION,\n                    "snapshot_id": sid,\n                    "manifest_sha256": _sha256(manifest_path),\n                    "data_yaml_sha256": _sha256(data_yaml_path),\n                    "verified_files": int(verified_files),\n                    "published_at": datetime.now(timezone.utc).isoformat(),\n                }\n''',
    "cache marker yaml hash",
)

training = Path("platform_core/training_tasks.py")
replace_once(
    training,
    '''        cache_publish: dict[str, Any]\n        try:\n            cache_entry, cache_stats = TrainingBundleCache(\n                self.data_dir,\n                context.task.project_id,\n            ).publish_verified(\n                manifest_path.parent,\n                snapshot_id,\n                verified_files=int(verification.get("verified_files") or 0),\n            )\n            cache_publish = {\n                "status": "ready",\n                "snapshot_id": cache_entry.snapshot_id,\n                "manifest_sha256": cache_entry.manifest_sha256,\n                **cache_stats,\n            }\n        except Exception as error:\n            # Bundle caching is a performance optimization. A verified training\n            # result must not be converted into failure solely because the\n            # cache filesystem is unavailable.\n            cache_publish = {\n                "status": "publish_failed",\n                "snapshot_id": snapshot_id,\n                "error": str(error),\n            }\n        cache_runtime = context.artifacts.read_json(\n            context.task.task_id,\n            "bundle-cache.json",\n            default={},\n        )\n        bundle_cache_evidence = {\n            **(cache_runtime if isinstance(cache_runtime, dict) else {}),\n            "publish": cache_publish,\n        }\n''',
    '''        cache_runtime = context.artifacts.read_json(\n            context.task.task_id,\n            "bundle-cache.json",\n            default={},\n        )\n        bundle_cache_evidence = {\n            **(cache_runtime if isinstance(cache_runtime, dict) else {}),\n            "publish": {\n                "status": "pending_commit",\n                "snapshot_id": snapshot_id,\n            },\n        }\n''',
    "defer cache publication",
)
replace_once(
    training,
    '''        context.save_checkpoint({"stage": "committed", "snapshot_id": snapshot_id, "result_ref": "result.json"})\n        return final_status, "result.json"\n''',
    '''        # Seed the shared cache only after the official algorithm version has\n        # been attached successfully. A task that fails before this point must\n        # not become the source of a future fast-path training bundle.\n        try:\n            cache_entry, cache_stats = TrainingBundleCache(\n                self.data_dir,\n                context.task.project_id,\n            ).publish_verified(\n                manifest_path.parent,\n                snapshot_id,\n                verified_files=int(verification.get("verified_files") or 0),\n            )\n            cache_publish = {\n                "status": "ready",\n                "snapshot_id": cache_entry.snapshot_id,\n                "manifest_sha256": cache_entry.manifest_sha256,\n                **cache_stats,\n            }\n        except Exception as error:\n            # Cache publication is only a performance optimization; failure here\n            # cannot invalidate a model/version that already passed final truth.\n            cache_publish = {\n                "status": "publish_failed",\n                "snapshot_id": snapshot_id,\n                "error": str(error),\n            }\n        bundle_cache_evidence = {\n            **(cache_runtime if isinstance(cache_runtime, dict) else {}),\n            "publish": cache_publish,\n        }\n        result["bundle_cache"] = bundle_cache_evidence\n        context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)\n        context.save_checkpoint({"stage": "committed", "snapshot_id": snapshot_id, "result_ref": "result.json"})\n        return final_status, "result.json"\n''',
    "publish after version attachment",
)

tests = Path("tests/unit/test_training_bundle_cache.py")
text = tests.read_text(encoding="utf-8")
append = r'''


def test_cache_resolve_rejects_tampered_label(tmp_path):
    snapshot_id = "1" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-label-integrity")
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    (entry.bundle / "dataset/labels/train/img-1.txt").write_text(
        "0 0.1 0.1 0.1 0.1", encoding="utf-8"
    )
    assert cache.resolve(snapshot_id) is None


def test_cache_resolve_rejects_tampered_data_yaml(tmp_path):
    snapshot_id = "2" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-yaml-integrity")
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    (entry.bundle / "dataset/data.yaml").write_text(
        "path: .\ntrain: images/other\n", encoding="utf-8"
    )
    assert cache.resolve(snapshot_id) is None


def test_cache_resolve_rejects_in_bundle_symlink_component(tmp_path):
    snapshot_id = "3" * 64
    source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
    cache = TrainingBundleCache(tmp_path / "data", "project-link-integrity")
    entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

    data_yaml = entry.bundle / "dataset/data.yaml"
    target = entry.bundle / "dataset/data-target.yaml"
    target.write_bytes(data_yaml.read_bytes())
    data_yaml.unlink()
    try:
        data_yaml.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")
    assert cache.resolve(snapshot_id) is None


def test_cache_publication_is_ordered_after_algorithm_version_attachment():
    import inspect

    from platform_core.training_tasks import TrainingHandler

    source = inspect.getsource(TrainingHandler._finalize_completed_job)
    assert source.index("attach_version(") < source.index(").publish_verified(")
    assert source.index(").publish_verified(") < source.index('"stage": "committed"')
'''
if "test_cache_resolve_rejects_tampered_label" in text:
    raise SystemExit("cache hardening tests already present")
tests.write_text(text.rstrip() + append + "\n", encoding="utf-8")

docs = Path("docs/CODEX_CURRENT_STATE.md")
replace_once(
    docs,
    '''Cache entries are published only during successful training finalization, after\nthe existing `verify_portable_dataset()` full image/label SHA256 gate has passed.\nAn incomplete/failed training run therefore cannot seed this cache. Cache\npublication failure is recorded as optimization evidence and cannot turn an\notherwise verified model result into a failed training result.\n''',
    '''Cache entries are published only during successful training finalization, after\nthe existing `verify_portable_dataset()` full image/label SHA256 gate has passed\nand after the official algorithm version has been attached successfully. An\nincomplete/failed training run therefore cannot seed this cache. Cache\npublication failure is recorded as optimization evidence and cannot turn an\notherwise verified model result into a failed training result. Cache-hit\nadmission re-hashes the small Snapshot, label and data-YAML files while large\nimages use their locked size/manifest evidence; finalization still performs the\nfull image SHA256 gate on every run.\n''',
    "cache closure integrity docs",
)
