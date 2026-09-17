from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    path = ROOT / "app.py"
    text = path.read_text(encoding="utf-8")
    if "external_algorithm_publish_router" in text:
        return

    archive_old = '''    try:\n        job["auto_conversion"]=version.get("auto_conversion");write_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)\n    except Exception:pass\n    return version\n'''
    archive_new = '''    try:\n        job["auto_conversion"]=version.get("auto_conversion");write_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)\n    except Exception:pass\n    request_external_auto_publish_if_enabled(\n        data_dir=DATA_DIR,\n        algorithms_path=algorithms_file(project_id),\n        algorithm_id=algorithm_id,\n        version_id=version_id,\n        now=now_iso(),\n    )\n    return version\n'''
    text = replace_once(text, archive_old, archive_new, "training archive publish request")

    bottom_old = '''from platform_core.external_algorithm_platform import (\n    assert_algorithm_mutable,\n    assert_local_algorithm_create_allowed,\n    external_algorithm_platform_router,\n)\nfrom platform_core.material_batches import material_batch_router\n\napp.include_router(external_algorithm_platform_router(\n    data_dir=DATA_DIR,\n    get_project=get_project,\n    algorithms_file=algorithms_file,\n    secret_store_factory=_v35_secret_store,\n))\napp.include_router(material_batch_router(\n    get_project, material_store, shared_task_repository, shared_task_artifacts,\n))\n'''
    bottom_new = '''from platform_core.external_algorithm_platform import (\n    assert_algorithm_mutable,\n    assert_local_algorithm_create_allowed,\n    external_algorithm_platform_router,\n)\nfrom platform_core.external_algorithm_publish import (\n    external_algorithm_publish_router,\n    request_external_auto_publish_if_enabled,\n)\nfrom platform_core.material_batches import material_batch_router\n\napp.include_router(external_algorithm_platform_router(\n    data_dir=DATA_DIR,\n    get_project=get_project,\n    algorithms_file=algorithms_file,\n    secret_store_factory=_v35_secret_store,\n))\napp.include_router(external_algorithm_publish_router(\n    data_dir=DATA_DIR,\n    get_project=get_project,\n    project_dir=project_dir,\n    algorithms_file=algorithms_file,\n    external_secret_store_factory=_v35_secret_store,\n    storage_sources_factory=storage_source_repository,\n    storage_credentials_factory=storage_credentials,\n))\napp.include_router(material_batch_router(\n    get_project, material_store, shared_task_repository, shared_task_artifacts,\n))\n'''
    text = replace_once(text, bottom_old, bottom_new, "external publish router")
    path.write_text(text, encoding="utf-8")


def patch_main() -> None:
    path = ROOT / "static" / "main.mjs"
    text = path.read_text(encoding="utf-8")
    if "installExternalAlgorithmPublishRuntime" in text:
        return
    import_old = "import {installExternalAlgorithmPlatformRuntime} from './modules/external-algorithm-platform.js?v=63001';\n"
    import_new = import_old + "import {installExternalAlgorithmPublishRuntime} from './modules/external-algorithm-publish.js?v=64001';\n"
    text = replace_once(text, import_old, import_new, "publish runtime import")

    install_old = '''window.PlatformCore.runtime.externalAlgorithmPlatformRuntime = externalAlgorithmPlatformRuntime;\n\nconst trainingRecoveryRuntime = installTrainingRecoveryRuntime({\n'''
    install_new = '''window.PlatformCore.runtime.externalAlgorithmPlatformRuntime = externalAlgorithmPlatformRuntime;\n\nconst externalAlgorithmPublishRuntime = installExternalAlgorithmPublishRuntime({\n  getState: () => state,\n  projectId: () => state.project?.id,\n  notify,\n  algorithmListRuntime,\n});\nwindow.PlatformCore.runtime.externalAlgorithmPublishRuntime = externalAlgorithmPublishRuntime;\n\nconst trainingRecoveryRuntime = installTrainingRecoveryRuntime({\n'''
    text = replace_once(text, install_old, install_new, "publish runtime install")
    path.write_text(text, encoding="utf-8")


def patch_index() -> None:
    path = ROOT / "static" / "index.html"
    text = path.read_text(encoding="utf-8")
    old = '<script type="module" src="/static/main.mjs?v=42.25.100"></script>'
    new = '<script type="module" src="/static/main.mjs?v=42.25.101"></script>'
    if new not in text:
        text = replace_once(text, old, new, "main module cache key")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_app()
    patch_main()
    patch_index()
    print("external algorithm publish phase2 wiring applied")
