from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "app.py"
RUNTIME_ROUTER_PATH = ROOT / "platform_core" / "training_recovery_api.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_production_app_mounts_runtime_router_exactly_once():
    tree = _tree(APP_PATH)
    imported = 0
    mounts = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "platform_core.training_recovery_api":
            imported += sum(alias.name == "training_recovery_router" for alias in node.names)
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "include_router"
            and isinstance(func.value, ast.Name)
            and func.value.id == "app"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "training_recovery_router"
        ):
            mounts.append(node.args[0])

    assert imported == 1
    assert len(mounts) == 1
    router_call = mounts[0]
    assert len(router_call.args) == 3
    assert [arg.id for arg in router_call.args if isinstance(arg, ast.Name)] == [
        "get_project",
        "shared_task_repository",
        "shared_task_artifacts",
    ]
    keywords = {item.arg: item.value for item in router_call.keywords if item.arg}
    assert set(keywords) == {"agent_execution_payload_resolver"}
    assert isinstance(keywords["agent_execution_payload_resolver"], ast.Name)
    assert keywords["agent_execution_payload_resolver"].id == "_resolve_agent_execution_payload"


def test_v63_subrouters_keep_single_composition_owner():
    app_source = APP_PATH.read_text(encoding="utf-8")
    runtime_source = RUNTIME_ROUTER_PATH.read_text(encoding="utf-8")

    # Production app owns one additive mount only. It must not separately mount
    # these subrouters, which would create duplicate routes and lifecycle owners.
    assert "service_node_router" not in app_source
    assert "central_scheduler_router" not in app_source
    assert "agent_executor_router" not in app_source

    assert runtime_source.count("root.include_router(service_node_router(task_repository))") == 1
    assert runtime_source.count(
        "root.include_router(central_scheduler_router(task_repository, task_artifacts))"
    ) == 1
    assert runtime_source.count("root.include_router(agent_executor_router(") == 1
    assert runtime_source.count(
        "execution_payload_resolver=agent_execution_payload_resolver"
    ) == 1


def test_production_runtime_mount_contract_keeps_formal_version_unchanged():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "42.24.0"
