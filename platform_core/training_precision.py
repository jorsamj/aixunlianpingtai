"""Canonical training-precision policy for the pinned Ultralytics runtime."""
from __future__ import annotations

SUPPORTED_TRAINING_PRECISIONS = frozenset({"auto", "fp16", "fp32"})


class TrainingPrecisionError(ValueError):
    pass


def normalize_training_precision(value: object) -> str:
    precision = str(value or "auto").strip().lower()
    if precision == "bf16":
        raise TrainingPrecisionError(
            "TRAINING_PRECISION_UNSUPPORTED: BF16 is not supported by the pinned "
            "Ultralytics training runtime; use auto, fp16 or fp32"
        )
    if precision not in SUPPORTED_TRAINING_PRECISIONS:
        raise TrainingPrecisionError(
            f"TRAINING_PRECISION_INVALID: unsupported precision {precision!r}"
        )
    return precision


def ultralytics_amp_value(precision: object, default_amp: bool = True) -> bool:
    """Map platform precision to Ultralytics 8.4.127's boolean amp contract."""
    normalized = normalize_training_precision(precision)
    if normalized == "auto":
        return bool(default_amp)
    if normalized == "fp16":
        return True
    return False


def verify_effective_training_precision(precision: object, trainer_amp: object) -> str:
    """Fail closed if an explicit precision request was not actually honored."""
    normalized = normalize_training_precision(precision)
    effective_amp = bool(trainer_amp)
    if normalized == "fp16" and not effective_amp:
        raise RuntimeError(
            "TRAINING_PRECISION_UNAVAILABLE: FP16 was requested but Ultralytics "
            "disabled AMP for the assigned runtime/device"
        )
    if normalized == "fp32" and effective_amp:
        raise RuntimeError(
            "TRAINING_PRECISION_MISMATCH: FP32 was requested but AMP is active"
        )
    return "fp16" if effective_amp else "fp32"


# Worker-local, fail-closed AMP admission. This module does not import Torch or
# Ultralytics at control-plane import time; the assigned Worker supplies both.
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import logging
import os
from pathlib import Path


@dataclass(frozen=True)
class AmpPreflight:
    enabled: bool
    method: str
    result: str
    reason: str
    reference_model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _local_amp_reference(project_dir: Path, ultralytics) -> Path | None:
    """Find an existing yolo26n.pt, never discover/download a missing asset."""
    project_dir = Path(project_dir).resolve()
    configured = str(os.environ.get("MC_AMP_CHECK_MODEL", "")).strip()
    candidates = []
    if configured:
        p = Path(configured).expanduser()
        candidates.append(p / "yolo26n.pt" if p.is_dir() else p)
    candidates.extend([
        project_dir / "models" / "yolo26n.pt",
        project_dir.parents[1] / "models" / "yolo26n.pt",
        Path.cwd() / "yolo26n.pt",
    ])
    weights_dir = getattr(ultralytics, "SETTINGS", {}).get("weights_dir")
    if weights_dir:
        candidates.append(Path(weights_dir) / "yolo26n.pt")
    for path in candidates:
        if path.name != "yolo26n.pt":
            continue
        if path.is_file():
            return path.resolve()
    return None


@contextmanager
def _reference_directory(path: Path):
    """Only the short preflight inference runs with a different cwd."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _reference_amp_check(torch, ultralytics, train_model, path: Path) -> bool:
    """Run Ultralytics' original check; skipped checks are NOT a pass."""
    from ultralytics import YOLO
    from ultralytics.engine import trainer as trainer_module
    from ultralytics.nn import tasks as tasks_module
    from ultralytics.utils import ASSETS, LOGGER

    if not (Path(ASSETS) / "bus.jpg").is_file():
        raise RuntimeError("AMP_REFERENCE_ASSET_MISSING")
    if not path.is_file() or not os.access(path, os.R_OK):
        raise RuntimeError("AMP_REFERENCE_UNREADABLE")

    # Bound to this reference preflight only: even a rename/delete race must
    # fail locally instead of invoking Ultralytics' asset downloader.
    original_asset_loader = tasks_module.attempt_download_asset
    def local_asset_only(filename, *args, **kwargs):
        local = Path(filename)
        if not local.is_file():
            raise FileNotFoundError("AMP_REFERENCE_DOWNLOAD_BLOCKED: " + str(filename))
        return str(local)

    class SuccessLog(logging.Handler):
        passed = False
        def emit(self, record):
            message = record.getMessage()
            if "AMP:" in message and "checks passed" in message:
                self.passed = True
    success_log = SuccessLog()
    module = train_model.model
    tasks_module.attempt_download_asset = local_asset_only
    LOGGER.addHandler(success_log)
    try:
        # A genuinely local file is loaded and validated BEFORE the reference
        # checker is allowed to run. No network retry is reachable here.
        YOLO(str(path))
        module.to("cuda:0")
        try:
            with _reference_directory(path.parent):
                checked = bool(trainer_module.check_amp(module))
            return checked and success_log.passed
        finally:
            module.cpu()
    finally:
        LOGGER.removeHandler(success_log)
        tasks_module.attempt_download_asset = original_asset_loader


def cuda_numeric_amp_probe(torch) -> bool:
    """CUDA FP16 forward/backward numerical test with no weights/network."""
    if not torch.cuda.is_available():
        return False
    device = torch.device("cuda:0")
    with torch.enable_grad():
        x = torch.linspace(-0.6, 0.6, 2 * 3 * 8 * 8, device=device).reshape(2, 3, 8, 8)
        base = torch.linspace(-0.2, 0.2, 4 * 3 * 3 * 3, device=device).reshape(4, 3, 3, 3)
        w = base.clone().detach().requires_grad_(True)
        reference = torch.nn.functional.conv2d(x, w, padding=1)
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            mixed = torch.nn.functional.conv2d(x, w, padding=1)
            loss = mixed.float().square().mean()
        if mixed.dtype != torch.float16:
            return False
        if not bool(torch.isfinite(mixed).all()) or not bool(torch.isfinite(loss)):
            return False
        if not bool(torch.allclose(reference.float(), mixed.float(), rtol=0.03, atol=0.015)):
            return False
        scaler = torch.amp.GradScaler("cuda", enabled=True)
        scaler.scale(loss).backward()
        if w.grad is None or not bool(torch.isfinite(w.grad).all()):
            return False
        optimizer = torch.optim.SGD([w], lr=0.001)
        scaler.step(optimizer)
        scaler.update()
        torch.cuda.synchronize(0)
        return bool(torch.isfinite(w).all())


def preflight_worker_amp(*, requested_amp: bool, torch, ultralytics,
                         train_model, project_dir: Path) -> AmpPreflight:
    """Always run after GPU visibility masking and before model.train()."""
    if not requested_amp:
        return AmpPreflight(False, "disabled", "disabled", "FP32 selected by resource policy")
    if not torch.cuda.is_available():
        return AmpPreflight(False, "cuda_probe", "failed", "WORKER_CUDA_UNAVAILABLE")
    if str(getattr(ultralytics, "__version__", "")) != "8.4.127":
        return AmpPreflight(False, "version_guard", "failed", "ULTRALYTICS_AMP_RUNTIME_VERSION_UNVERIFIED")
    path = _local_amp_reference(Path(project_dir), ultralytics)
    if path is not None:
        try:
            passed = _reference_amp_check(torch, ultralytics, train_model, path)
            return AmpPreflight(passed, "ultralytics_reference", "passed" if passed else "failed",
                                "Ultralytics check_amp completed" if passed else "AMP_REFERENCE_CHECK_FAILED",
                                str(path))
        except Exception as exc:
            return AmpPreflight(False, "ultralytics_reference", "failed",
                                "AMP_REFERENCE_INVALID: " + str(exc), str(path))
    try:
        passed = cuda_numeric_amp_probe(torch)
        return AmpPreflight(passed, "cuda_numeric", "passed" if passed else "failed",
                            "Worker CUDA FP16 forward/backward probe passed" if passed else "CUDA_FP16_PROBE_FAILED")
    except Exception as exc:
        return AmpPreflight(False, "cuda_numeric", "failed", "CUDA_FP16_PROBE_ERROR: " + str(exc))


@contextmanager
def scoped_worker_amp_check(decision: AmpPreflight):
    """Redirect ONLY the Worker train() invocation, restore in finally.

    The return value is backed by a completed numerical/reference preflight,
    not a hardcoded successful check. No application-global patch persists.
    """
    if not decision.enabled:
        yield
        return
    from ultralytics.engine import trainer as trainer_module
    original = trainer_module.check_amp
    calls = []

    def prevalidated_check(model):
        if next(model.parameters()).device.type != "cuda":
            return False
        calls.append(True)
        return bool(decision.enabled)

    trainer_module.check_amp = prevalidated_check
    try:
        yield
        if not calls:
            raise RuntimeError("AMP_RUNTIME_CHECK_HOOK_NOT_USED")
    finally:
        trainer_module.check_amp = original
