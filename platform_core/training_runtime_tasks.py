from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .task_runtime import TaskKind
from .training_checkpoint_resume_tasks import CheckpointResumeRecoveryHandler
from .training_label_tasks import _install_scoped_training_hooks


FINALIZING_COMMIT_STAGE = "finalizing_commit"


class ProductionTrainingHandler(CheckpointResumeRecoveryHandler):
    """Canonical production training handler.

    The inherited chain owns training, same-task last.pt resume, isolated final
    validation and explicit checkpoint revalidation. This final composition
    layer publishes the one missing durable phase: version/result persistence.
    Frontend stage text therefore comes from backend task truth rather than a
    presentation-only guess.
    """

    def _finalize_completed_job(
        self,
        context,
        payload: Mapping[str, Any],
        project: Path,
        job: Mapping[str, Any],
        *,
        recovered: bool = False,
    ):
        context.heartbeat(
            progress=98,
            stage=FINALIZING_COMMIT_STAGE,
            current_item="模型验证通过，正在归档训练结果与算法版本",
        )
        return super()._finalize_completed_job(
            context,
            payload,
            project,
            job,
            recovered=recovered,
        )


def worker_registration(data_dir: Path):
    _install_scoped_training_hooks()
    return {
        "handlers": {TaskKind.TRAINING: ProductionTrainingHandler(data_dir)},
        "capabilities": {"training.ultralytics", "training.paddle"},
    }
