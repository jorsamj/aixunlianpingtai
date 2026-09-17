from __future__ import annotations

import os
from typing import Any, Callable, Mapping


DEFAULT_AUTO_WORKER_CAP = 2
AUTO_WORKER_CAP_ENV = "TRAINING_AUTO_MAX_DATALOADER_WORKERS"


def _auto_worker_cap() -> int:
    raw = str(os.environ.get(AUTO_WORKER_CAP_ENV, DEFAULT_AUTO_WORKER_CAP)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{AUTO_WORKER_CAP_ENV} must be an integer between 0 and 32") from error
    if not 0 <= value <= 32:
        raise ValueError(f"{AUTO_WORKER_CAP_ENV} must be an integer between 0 and 32")
    return value


def bounded_resolve_resources(
    original: Callable[[Mapping[str, Any], Mapping[str, Any], Any, Any], dict[str, Any]],
    request: Mapping[str, Any],
    context: Mapping[str, Any],
    model: Any,
    torch: Any,
) -> dict[str, Any]:
    """Apply a host-RAM safety ceiling only to automatic loader resolution.

    Ultralytics reuses training DataLoader settings during its automatic final
    best-checkpoint validation. On GPU-heavy hosts with comparatively small RAM,
    multiple loader processes can amplify shared-memory usage enough for Linux's
    OOM killer to terminate an otherwise completed training run. Manual strategy
    remains exact and is never silently changed here.
    """

    resolved = dict(original(request, context, model, torch))
    if str(resolved.get("resource_strategy") or request.get("resource_strategy") or "auto") != "auto":
        return resolved

    cap = _auto_worker_cap()
    before = max(0, int(resolved.get("resolved_workers") or 0))
    after = min(before, cap)
    resolved["auto_dataloader_worker_cap"] = cap
    if after == before:
        reasons = list(resolved.get("reasons") or [])
        reasons.append(f"Automatic DataLoader worker safety cap={cap}")
        resolved["reasons"] = reasons
        return resolved

    resolved["resolved_workers"] = after
    adjustments = list(resolved.get("adjustments") or [])
    adjustments.append(
        f"workers downscaled {before}->{after} by {AUTO_WORKER_CAP_ENV} host-RAM safety cap"
    )
    resolved["adjustments"] = adjustments
    reasons = list(resolved.get("reasons") or [])
    reasons.append(
        "Automatic DataLoader workers are bounded to reduce multiprocessing/shared-memory "
        "pressure during training and Ultralytics final validation"
    )
    resolved["reasons"] = reasons
    return resolved


def install_resource_hardening() -> None:
    from platform_core import training_metrics

    original = training_metrics.resolve_resources
    if getattr(original, "_mc_auto_worker_hardening", False):
        return

    def hardened(request, context, model, torch):
        return bounded_resolve_resources(original, request, context, model, torch)

    hardened._mc_auto_worker_hardening = True
    training_metrics.resolve_resources = hardened


def main() -> int:
    # Install before importing train_worker. train_worker imports
    # resolve_resources inside main after CUDA visibility has been configured,
    # so this does not initialize CUDA or Ultralytics early.
    install_resource_hardening()
    import train_worker

    result = train_worker.main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
