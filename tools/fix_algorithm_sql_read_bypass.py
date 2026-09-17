from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
WORKFLOW = ROOT / ".github" / "workflows" / "algorithm-sql-store.yml"
TEST = ROOT / "tests" / "unit" / "test_algorithm_sql_app_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    "    save_algorithms as save_algorithm_assets,\n",
    "",
    "remove legacy full-graph save import",
)
app = replace_once(
    app,
    "def save_algorithms_internal(project_id: str, data: List[Dict[str, Any]]):\n    save_algorithm_assets(algorithms_file(project_id), data)\n\n\n",
    "",
    "remove unused legacy full-graph save wrapper",
)
app = replace_once(
    app,
    '    image_count=material_store(pid).count(); algs=read_json(project_dir(pid)/"algorithms.json",[]); jobs=read_json(project_dir(pid)/"jobs"/"index.json",[])\n',
    '    image_count=material_store(pid).count(); algs=list_algorithm_assets(algorithms_file(pid)); jobs=read_json(project_dir(pid)/"jobs"/"index.json",[])\n',
    "route bootstrap algorithm counts through SQL source of truth",
)
APP.write_text(app, encoding="utf-8")

TEST.write_text(
    '''from pathlib import Path\n\n\ndef test_app_bootstrap_counts_use_algorithm_sql_source_of_truth():\n    source = Path("app.py").read_text(encoding="utf-8")\n\n    assert 'algs=list_algorithm_assets(algorithms_file(pid))' in source\n    assert 'read_json(project_dir(pid)/"algorithms.json",[])' not in source\n\n\ndef test_app_has_no_legacy_full_graph_algorithm_save_wrapper():\n    source = Path("app.py").read_text(encoding="utf-8")\n\n    assert "save_algorithms_internal" not in source\n    assert "save_algorithms as save_algorithm_assets" not in source\n''',
    encoding="utf-8",
)

workflow = WORKFLOW.read_text(encoding="utf-8")
workflow = replace_once(
    workflow,
    "    paths:\n      - platform_core/algorithm_sql_store.py\n",
    "    paths:\n      - app.py\n      - platform_core/algorithm_sql_store.py\n",
    "watch app.py",
)
workflow = replace_once(
    workflow,
    "      - tests/unit/test_algorithm_sql_store.py\n",
    "      - tests/unit/test_algorithm_sql_store.py\n      - tests/unit/test_algorithm_sql_app_contract.py\n",
    "watch app SQL contract test",
)
workflow = replace_once(
    workflow,
    "      - name: Syntax checks\n        run: |\n          python -m py_compile platform_core/algorithm_sql_store.py platform_core/algorithms.py platform_core/external_algorithm_platform.py platform_core/external_algorithm_publish.py\n",
    "      - name: Syntax checks\n        run: |\n          python -m py_compile app.py platform_core/algorithm_sql_store.py platform_core/algorithms.py platform_core/external_algorithm_platform.py platform_core/external_algorithm_publish.py\n",
    "compile app.py",
)
workflow = replace_once(
    workflow,
    "      - name: SQL migration and row CRUD contracts\n        run: PYTHONPATH=. pytest -q --confcutdir=tests/unit tests/unit/test_algorithm_sql_store.py tests/unit/test_algorithms.py\n",
    "      - name: SQL migration and row CRUD contracts\n        run: PYTHONPATH=. pytest -q --confcutdir=tests/unit tests/unit/test_algorithm_sql_store.py tests/unit/test_algorithm_sql_app_contract.py tests/unit/test_algorithms.py\n",
    "run app SQL contract",
)
workflow = replace_once(
    workflow,
    "          grep -q 'AlgorithmSqlStore(Path(path)).attach_version' platform_core/algorithms.py\n",
    "          grep -q 'AlgorithmSqlStore(Path(path)).attach_version' platform_core/algorithms.py\n          grep -q 'algs=list_algorithm_assets(algorithms_file(pid))' app.py\n          ! grep -q 'read_json(project_dir(pid)/\"algorithms.json\",\[\])' app.py\n          ! grep -q 'save_algorithms_internal' app.py\n          ! grep -q 'save_algorithms as save_algorithm_assets' app.py\n",
    "guard app SQL source of truth",
)
WORKFLOW.write_text(workflow, encoding="utf-8")

print("patched app.py, permanent workflow, and SQL app contract test")
