from pathlib import Path


def test_app_bootstrap_counts_use_algorithm_sql_source_of_truth():
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'algs=list_algorithm_assets(algorithms_file(pid))' in source
    assert 'read_json(project_dir(pid)/"algorithms.json",[])' not in source


def test_app_has_no_legacy_full_graph_algorithm_save_wrapper():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "save_algorithms_internal" not in source
    assert "save_algorithms as save_algorithm_assets" not in source



def test_bootstrap_algorithm_cache_is_revision_guarded_and_does_not_rebuild_everything():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "def _v53_algorithms_with_revision(" in source
    assert "algorithm_store_revision(algorithms_file(project_id))" in source
    assert 'payload["algorithm_revision"] = stable_revision' in source
    assert 'payload["algorithms"] = algorithms' in source

    overlay_start = source.index("def _v53_snapshot_with_live_jobs(")
    build_start = source.index('@performance_stage("bootstrap.revision")', overlay_start)
    overlay = source[overlay_start:build_start]
    # Converting a lean cache to an explicitly requested full compatibility read
    # is allowed; a full cached snapshot still refreshes only changed algorithms.
    assert 'if payload.get("core_only"):' in overlay
    full_overlay = overlay[overlay.index('    cached_revision ='):]
    assert "_v53_build_snapshot(" not in full_overlay
    assert "list_algorithms_internal(project_id)" not in overlay
    assert "_v53_algorithms_with_revision(project_id)" in overlay
    assert "stable_revision == publish_revision" in overlay
    assert "return algorithms, before" in source
