from pathlib import Path


def test_app_bootstrap_counts_use_algorithm_sql_source_of_truth():
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'algs=list_algorithm_assets(algorithms_file(pid))' in source
    assert 'read_json(project_dir(pid)/"algorithms.json",[])' not in source


def test_app_has_no_legacy_full_graph_algorithm_save_wrapper():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "save_algorithms_internal" not in source
    assert "save_algorithms as save_algorithm_assets" not in source
