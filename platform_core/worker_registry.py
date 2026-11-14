from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from .task_runtime import TaskKind


ROLE_MODULES = {
    "discovery": "platform_core.resource_discovery.tasks",
    "storage": "platform_core.storage.rescan_tasks",
    "materials": "platform_core.material_batches",
    "video": "platform_core.video_tasks",
    "training": "platform_core.training_runtime_tasks",
    "training-prep": "platform_core.remote_training_tasks",
    "annotation": "platform_core.annotation_task_service",
    "conversion": "platform_core.deployment.conversion_tasks",
    "deployment-test": "platform_core.deployment.inference_tasks",
}


@dataclass(frozen=True)
class WorkerRegistration:
    handlers: dict[TaskKind, object]
    capabilities: frozenset[str]
    roles: frozenset[str]


def resolve_worker_registration(data_dir: Path, roles: set[str]) -> WorkerRegistration:
    selected = set(ROLE_MODULES) if "all" in roles else set(roles)
    unknown = selected - set(ROLE_MODULES)
    if unknown:
        raise ValueError(f"unknown worker roles: {', '.join(sorted(unknown))}")
    handlers = {}
    capabilities: set[str] = set()
    registered_roles: set[str] = set()
    for role in sorted(selected):
        module_name = ROLE_MODULES[role]
        try:
            available = importlib.util.find_spec(module_name) is not None
        except ModuleNotFoundError:
            available = False
        if not available:
            continue
        module = importlib.import_module(module_name)
        registration = module.worker_registration(data_dir)
        handlers.update(registration["handlers"])
        capabilities.update(registration["capabilities"])
        registered_roles.add(role)
    if any(not isinstance(kind, TaskKind) for kind in handlers):
        raise TypeError("worker handler keys must be TaskKind values")
    return WorkerRegistration(
        handlers=handlers,
        capabilities=frozenset(capabilities),
        roles=frozenset(registered_roles),
    )


def build_worker_registration(data_dir: Path, roles: set[str]):
    registration = resolve_worker_registration(data_dir, roles)
    return dict(registration.handlers), set(registration.capabilities)
