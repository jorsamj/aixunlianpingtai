"""Training creation domain: request contract, validation and HTTP entry points.

The URL contract, the pydantic request model, the pre-flight configuration
validation and the creation orchestration were owned by ``app.py``. They live
here now so the application module only assembles dependencies; the behaviour is
unchanged:

* ``POST /api/v12/projects/{project_id}/train/start`` is the one creation entry
  (``name="v12_start_train"`` so existing route lookups keep working);
* ``POST /api/projects/{project_id}/train/start`` stays a compatibility delegate
  to the same code path, never a second owner;
* validation still fails before any worker starts, with the same status codes
  and messages;
* external-algorithm master data preflight stays deferred to the durable
  TRAINING_PREPARE worker (this module must not re-verify or refresh it).

Orchestration (task creation, snapshot freezing, input preparation) is delegated
to the callable the application injects: this module never imports ``app``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt, model_validator

from .errors import PlatformError
from .training_devices import normalize_training_device
from .training_precision import TrainingPrecisionError, normalize_training_precision


class TrainReq(BaseModel):
    task_id: Optional[str] = None
    # Existing callers retain synchronous preflight. The training workbench
    # opts into durable creation followed by the already mandatory
    # TRAINING_PREPARE admission and snapshot freeze.
    admission_mode: Literal["synchronous", "background"] = "synchronous"
    # An explicit, task-local human assertion. The worker verifies the selected
    # images and formal GT under the lifecycle fence before issuing receipts.
    review_all_training_backgrounds: bool = False
    expected_material_revision: Optional[int] = Field(default=None, ge=0)
    expected_annotation_revision: Optional[int] = Field(default=None, ge=0)
    duplicate_review: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def reject_dataset_group_contract(cls, value):
        if isinstance(value, dict) and (value.get("train_dataset_ids") or value.get("test_dataset_ids")):
            raise ValueError("训练任务只按素材 image_id 选择，不能提交数据集分组")
        if isinstance(value, dict):
            value = dict(value)
            if isinstance(value.get("cache"), bool):
                value["cache"] = "True" if value["cache"] else "False"
            value["device"] = normalize_training_device(value.get("device", "auto"))
            if isinstance(value.get("robustness_policy"), dict):
                allowed = {"mode", "selection", "copies", "presets", "seed"}
                value["robustness_policy"] = {key: item for key, item in value["robustness_policy"].items() if key in allowed}
        return value

    framework: str = "ultralytics"  # ultralytics / paddle
    algorithm: Optional[str] = "yolo11n_det"
    algorithm_asset_id: Optional[str] = ""
    base_version_id: Optional[str] = ""
    model: str = "yolo11n.pt"
    epochs: int = 150
    imgsz: int = 640
    batch: StrictInt = 8
    training_mode: Optional[Literal["quick", "full", "complex", "custom"]] = None
    history_policy: Optional[Literal["new_for_algorithm", "include_history"]] = None
    robustness_policy: Optional[Dict[str, Any]] = None
    resource_strategy: Literal["auto", "manual"] = "auto"
    resource_profile: Literal["balanced", "performance", "stability"] = "performance"
    device: str = "auto"
    gpu_policy: Literal["auto", "exclusive", "shared"] = "exclusive"
    estimated_gpu_memory_bytes: Optional[int] = Field(default=None, gt=0)
    gpu_sharing_evidence: Optional[Dict[str, Any]] = None
    train_ratio: float = 0.8
    include_empty: bool = False
    dataset_id: Optional[str] = None
    target: str = "local"  # local / remote
    server_id: Optional[str] = None
    remote_url: Optional[str] = None
    api_key: Optional[str] = ""
    paddle_command: Optional[str] = ""
    # v20 进阶训练参数，Ultralytics 本机训练生效。
    patience: int = 40
    early_stopping_enabled: bool = False
    time: Optional[float] = None
    precision: Literal["auto", "fp16", "bf16", "fp32"] = "auto"
    workers: StrictInt = 0
    optimizer: str = "auto"
    lr0: float = 0.01
    lrf: float = 0.01
    weight_decay: float = 0.0005
    close_mosaic: int = 10
    mosaic: float = 1.0
    cache: str = "False"
    single_cls: bool = False
    pretrained: bool = True
    rect: bool = False
    amp: bool = True
    cos_lr: bool = False
    freeze: int = 0
    # v42.5 更完整的 Ultralytics 训练配置。保持官方默认值，普通用户可直接使用默认配置。
    momentum: float = 0.937
    warmup_epochs: float = 3.0
    save_period: int = -1
    seed: int = 0
    deterministic: bool = True
    multi_scale: float = 0.0
    hsv_h: float = 0.015
    hsv_s: float = 0.7
    hsv_v: float = 0.4
    degrees: float = 0.0
    translate: float = 0.1
    scale: float = 0.5
    shear: float = 0.0
    perspective: float = 0.0
    flipud: float = 0.0
    fliplr: float = 0.5
    mixup: float = 0.0
    # 飞桨专用：平台会按小数据集/CPU自动生成安全覆盖项。
    paddle_lr: Optional[float] = None
    # 飞桨专用：是否在训练过程中启用 COCO 评估。默认关闭，避免小数据集/类别映射中断训练。
    paddle_eval: bool = False
    # v42.4 数据选择与阶段质量门禁
    train_labels: Optional[List[str]] = None
    val_labels: Optional[List[str]] = None
    train_selection_ref: Optional[str] = None
    test_selection_ref: Optional[str] = None
    validation_selection_ref: Optional[str] = None
    validation_image_ids: Optional[List[str]] = None
    zip_source_job_ids: Optional[List[str]] = None
    zip_selection_digest: Optional[str] = None
    train_image_ids: Optional[List[str]] = None
    val_image_ids: Optional[List[str]] = None
    test_image_ids: Optional[List[str]] = None
    # v42.15：训练页可从训练/试验候选素材中按比例随机留出本次试验集。
    # selected_image_ids 是本次候选池；为空时保持旧版显式 train/val 选择兼容。
    selected_image_ids: Optional[List[str]] = None
    # Durable v2 split contract. When split_mode is present, the API only
    # persists the request; a standalone training worker prepares the snapshot.
    split_mode: Optional[Literal["independent_test_set", "random_test_from_training_pool", "fixed_zip_train_val_test"]] = None
    validation_percent: Optional[float] = 20.0
    random_experiment_split: bool = True
    experiment_percent: Optional[float] = 20.0
    train_max_samples: int = 0
    val_max_samples: int = 0
    eval_interval: int = 0
    eval_metric: str = "map50"
    continue_threshold: float = 0.0
    stop_threshold: float = 0.0
    auto_supplement: bool = False
    iteration_action: Optional[Dict[str, str]] = None
    supplement_candidate_set_id: Optional[str] = ""
    supplement_count: int = 0
    # Reusable Benchmark v1. The browser submits identity only; exact test IDs
    # are resolved from the source version/Snapshot by the control plane.
    benchmark_source_version_id: Optional[str] = ""
    benchmark_scope_id: Optional[str] = ""
    # v42.7 AI mid-training intervention. The AI is advisory within constrained actions; Ground Truth metrics stay authoritative.
    ai_intervention_enabled: bool = False
    ai_intervention_epochs: Optional[List[int]] = None
    ai_model_config_id: Optional[str] = ""
    ai_eval_samples: int = 20
    ai_action_mode: str = "auto"  # auto / advise
    ai_extra_epochs: int = 20
    ai_max_rounds: int = 1
    # v42.8：训练任务队列与训练完成后的自动转换。
    queue_priority: StrictInt = 50
    auto_convert_targets: Optional[List[str]] = None
    external_analysis_id: Optional[str] = None


def validate_train_request(payload: TrainReq):
    """Fail before spawning a training process, so invalid UI values never become opaque worker errors."""
    if int(payload.epochs) < 1:
        raise HTTPException(status_code=400, detail="训练轮次 epochs 必须大于等于 1")
    if int(payload.imgsz) < 32:
        raise HTTPException(status_code=400, detail="图片尺寸 imgsz 不能小于 32")
    if int(payload.batch) == 0 or int(payload.batch) < -1:
        raise HTTPException(status_code=400, detail="batch 只能是正整数或 -1（Ultralytics 自动批大小）")
    if payload.training_mode in {"quick", "full", "complex"} and payload.resource_strategy != "auto":
        raise HTTPException(status_code=400, detail="预设训练模式的资源参数只能在目标 Worker 启动前自动决议")
    if payload.training_mode == "custom" and payload.resource_strategy != "manual":
        raise HTTPException(status_code=400, detail="自定义训练模式必须使用手动资源策略")
    if payload.resource_strategy == "manual" and not 1 <= payload.batch <= 4096:
        raise HTTPException(status_code=400, detail="手动资源策略 batch 必须是 1~4096 的整数；自动估算请选择 auto 策略")
    if int(payload.patience) < 0:
        raise HTTPException(status_code=400, detail="patience 不能小于 0")
    if payload.early_stopping_enabled and int(payload.patience) < 1:
        raise HTTPException(status_code=400, detail="开启智能早停时，patience 必须至少为 1")
    if int(payload.workers) < 0:
        raise HTTPException(status_code=400, detail="workers 不能小于 0")
    allowed_optimizers = {"auto", "sgd", "musgd", "adam", "adamax", "adamw", "nadam", "radam", "rmsprop"}
    if str(payload.optimizer or "auto").strip().lower() not in allowed_optimizers:
        raise HTTPException(status_code=400, detail="不支持的 optimizer。可选：auto / SGD / MuSGD / Adam / Adamax / AdamW / NAdam / RAdam / RMSProp")
    # Historical UI submits 0 for "no limit"; normalize before validation and task freezing.
    if payload.time == 0:
        payload.time = None
    if payload.time is not None and not (0.1 <= float(payload.time) <= 720):
        raise HTTPException(status_code=400, detail="最大训练时长 time 必须在 0.1~720 小时之间")
    if str(payload.gpu_policy or "auto").strip().lower() == "shared":
        raise HTTPException(
            status_code=400,
            detail="当前训练调度采用单卡单任务安全隔离，尚未启用 GPU 共享；请选择自动隔离或独占。",
        )
    try:
        normalize_training_precision(payload.precision)
    except TrainingPrecisionError as error:
        raise HTTPException(
            status_code=400,
            detail="当前训练运行时暂不支持 BF16；请选择自动（推荐）、FP16 或 FP32。",
        ) from error
    if not (0 < float(payload.lr0) <= 1):
        raise HTTPException(status_code=400, detail="lr0 必须在 0~1 之间")
    if not (0 <= float(payload.lrf) <= 1):
        raise HTTPException(status_code=400, detail="lrf 必须在 0~1 之间")
    if float(payload.weight_decay) < 0:
        raise HTTPException(status_code=400, detail="weight_decay 不能小于 0")
    if int(payload.close_mosaic) < 0:
        raise HTTPException(status_code=400, detail="close_mosaic 不能小于 0")
    if not (0 <= float(payload.mosaic) <= 1):
        raise HTTPException(status_code=400, detail="mosaic 必须在 0~1 之间")
    if int(payload.freeze) < 0:
        raise HTTPException(status_code=400, detail="freeze 不能小于 0")
    if not (0 <= float(payload.momentum) <= 1):
        raise HTTPException(status_code=400, detail="momentum 必须在 0~1 之间")
    if float(payload.warmup_epochs) < 0:
        raise HTTPException(status_code=400, detail="warmup_epochs 不能小于 0")
    if float(payload.multi_scale) < 0 or float(payload.multi_scale) > 1:
        raise HTTPException(status_code=400, detail="multi_scale 必须在 0~1 之间")
    for name in ["hsv_h","hsv_s","hsv_v","translate","scale","perspective","flipud","fliplr","mixup"]:
        value=float(getattr(payload,name))
        if value < 0 or value > 1:
            raise HTTPException(status_code=400, detail=f"{name} 必须在 0~1 之间")
    if int(payload.eval_interval) < 0 or int(payload.val_max_samples) < 0:
        raise HTTPException(status_code=400, detail="阶段检查轮次和试验集抽查数量不能小于 0")
    metric = str(payload.eval_metric or "map50").strip().lower()
    if metric not in {"map50", "precision", "recall"}:
        raise HTTPException(status_code=400, detail="目标指标只支持：mAP50 / Precision / Recall")
    continue_threshold = float(payload.continue_threshold or 0)
    stop_threshold = float(payload.stop_threshold or 0)
    if not (0 <= continue_threshold <= 1):
        raise HTTPException(status_code=400, detail="优化参考线必须在 0~1 之间")
    if not (0 <= stop_threshold <= 1):
        raise HTTPException(status_code=400, detail="目标正确率必须在 0~1 之间（例如 90% = 0.9）")
    if stop_threshold > 0 and int(payload.eval_interval) <= 0:
        raise HTTPException(status_code=400, detail="设置目标正确率后，每隔几轮检查 eval_interval 必须大于 0")
    if payload.experiment_percent is not None and not (0 <= float(payload.experiment_percent) <= 100):
        raise HTTPException(status_code=400, detail="试验集比例必须在 0~100 之间")
    if payload.random_experiment_split and payload.selected_image_ids and len(set(payload.selected_image_ids)) >= 2:
        if not (0 < float(payload.experiment_percent) < 100):
            raise HTTPException(status_code=400, detail="启用随机试验集时，比例必须大于 0 且小于 100")
    if continue_threshold and stop_threshold and continue_threshold >= stop_threshold:
        raise HTTPException(status_code=400, detail="优化参考线必须小于目标正确率")
    # v42.8 起训练阶段不再支持 AI 中途介入；质量门禁完全由试验集 Ground Truth 指标决定。
    payload.ai_intervention_enabled = False
    payload.ai_intervention_epochs = []
    payload.ai_model_config_id = ""
    if int(payload.queue_priority) < 1 or int(payload.queue_priority) > 999:
        raise HTTPException(status_code=400, detail="任务优先级必须是 1~999 的整数，1 为最高优先级")
    allowed_auto = {"ascend", "rockchip", "sophon"}
    bad_auto = [x for x in (payload.auto_convert_targets or []) if x not in allowed_auto]
    if bad_auto:
        raise HTTPException(status_code=400, detail="自动转换仅支持：华为 Atlas / 瑞芯微 / 算能")
    cache = str(payload.cache).strip().lower()
    if cache not in {"false", "true", "0", "1", "ram", "disk", "none", ""}:
        raise HTTPException(status_code=400, detail="cache 只支持：关闭 / 内存缓存 / 磁盘缓存")


@dataclass(frozen=True)
class TrainingCreateDependencies:
    """Everything the creation domain needs, supplied by the application.

    The application owns dependency assembly; this module owns the contract and
    never imports ``app`` (no reverse dependency).
    """

    get_project: Callable[[str], Any]
    algorithm_config: Callable[[str], Any]
    list_algorithms: Callable[[str], List[Dict[str, Any]]]
    enqueue: Callable[..., Dict[str, Any]]
    actor_resolver: Callable[[Any, str], Dict[str, Any]]


def start_training(
    project_id: str,
    payload: TrainReq,
    request: Optional[Request] = None,
    *,
    dependencies: TrainingCreateDependencies,
):
    """Create one durable training task from the browser contract.

    The orchestration itself stays with the existing durable owner (injected as
    ``dependencies.enqueue``): this function validates the request, resolves the
    algorithm identity and the reviewer, and keeps the legacy error contract.
    """
    dependencies.get_project(project_id)
    validate_train_request(payload)
    framework = (payload.framework or "ultralytics").strip().lower()
    if framework != "ultralytics":
        raise HTTPException(
            status_code=409,
            detail=(
                "当前 Durable Training 主流程只支持 Ultralytics。"
                "PaddleDetection 尚未接入同一套冻结 Snapshot / COCO bundle / completion 合同。"
            ),
        )
    dependencies.algorithm_config(payload.algorithm or "")
    asset_algorithm = next(
        (
            x
            for x in dependencies.list_algorithms(project_id)
            if x.get("id") == (payload.algorithm_asset_id or "")
        ),
        None,
    )
    if not str(payload.algorithm_asset_id or "").strip():
        raise HTTPException(status_code=400, detail="请选择要迭代训练的算法")
    if asset_algorithm is None:
        raise HTTPException(status_code=404, detail="训练算法不存在或已被删除")
    if not payload.split_mode:
        raise HTTPException(
            status_code=409,
            detail="v12 训练创建必须提交 split_mode 并走 Durable Training 主路径；旧训练路径已禁止绕过冻结标签与 Snapshot 合同",
        )
    try:
        review_actor_id = ""
        if payload.review_all_training_backgrounds:
            if request is None:
                raise HTTPException(status_code=401, detail="批量人工确认需要已登录的用户请求")
            review_actor_id = dependencies.actor_resolver(request, project_id)["actor_id"]
        return dependencies.enqueue(
            project_id, payload, review_actor_id=review_actor_id,
        )
    except HTTPException as error:
        # Keep the existing detailed admission contract and expose its machine
        # code at the same top level as validation/provider errors.
        detail = error.detail
        if isinstance(detail, dict) and detail.get("code"):
            raise PlatformError(
                code=str(detail["code"]), status_code=error.status_code,
                message=str(detail.get("message") or "训练准入检查未通过"),
                detail=json.dumps(detail, ensure_ascii=False),
                solution="请查看完整阻塞原因，修改训练配置后重新检查。",
            ) from error
        raise


def build_training_create_router(dependencies: TrainingCreateDependencies) -> APIRouter:
    """Both creation URLs, bound to the same owner (compatibility stays a view)."""
    router = APIRouter()

    @router.post(
        "/api/v12/projects/{project_id}/train/start", name="v12_start_train"
    )
    def v12_start_train_api(project_id: str, payload: TrainReq, request: Request):
        """Authenticate task-scope consent on the actual HTTP request only."""
        return start_training(project_id, payload, request=request, dependencies=dependencies)

    @router.post("/api/projects/{project_id}/train/start")
    def start_train(project_id: str, payload: TrainReq):
        """Compatibility URL: all training creation is owned by v12 Durable Training."""
        return start_training(project_id, payload, dependencies=dependencies)

    return router


__all__ = [
    "TrainReq",
    "TrainingCreateDependencies",
    "build_training_create_router",
    "start_training",
    "validate_train_request",
]
