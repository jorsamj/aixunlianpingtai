"""Isolated image-analysis runtime for durable material cleaning.

The Materials Worker owns durable task/selection state. Pillow/OpenCV decoding is
kept in one reusable child process so one pathological image cannot block the
Worker forever. If an analysis exceeds the hard deadline, only the analysis
process is terminated; the parent records that image as failed and continues.
"""
from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
from typing import Callable

from .cleaning import ImageDecodeError, image_metrics


DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 30.0
ANALYSIS_POLL_SECONDS = 0.5


class CleaningAnalysisTimeout(TimeoutError):
    """One image exceeded the bounded cleaning-analysis deadline."""


def _analysis_worker(connection) -> None:
    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                return
            if request is None:
                return
            try:
                metrics = image_metrics(
                    Path(str(request["path"])),
                    require_blur=bool(request.get("require_blur")),
                    content_sha256=str(request.get("content_sha256") or "") or None,
                )
                connection.send({"ok": True, "metrics": metrics})
            except BaseException as error:
                try:
                    connection.send({
                        "ok": False,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    })
                except (BrokenPipeError, EOFError, OSError):
                    return
    except (BrokenPipeError, EOFError, OSError):
        return
    finally:
        try:
            connection.close()
        except OSError:
            pass


class CleaningAnalysisRuntime:
    """One reusable spawned process with per-image hard deadlines."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        poll_seconds: float = ANALYSIS_POLL_SECONDS,
        worker_target=None,
        multiprocessing_context=None,
    ) -> None:
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.poll_seconds = max(0.02, float(poll_seconds))
        self._target = worker_target or _analysis_worker
        self._context = multiprocessing_context or multiprocessing.get_context("spawn")
        self._connection = None
        self._process = None

    def _start(self) -> None:
        if self._process is not None and self._process.is_alive() and self._connection is not None:
            return
        self._terminate()
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=self._target,
            args=(child,),
            name="material-cleaning-analysis",
        )
        process.daemon = False
        try:
            process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        self._connection = parent
        self._process = process

    def _terminate(self) -> None:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        if process is not None and process.is_alive():
            try:
                process.terminate()
            except (OSError, ValueError):
                pass
            process.join(timeout=2.0)
            if process.is_alive():
                kill = getattr(process, "kill", None)
                if callable(kill):
                    try:
                        kill()
                    except (OSError, ValueError):
                        pass
                    process.join(timeout=1.0)
        elif process is not None:
            try:
                process.join(timeout=0.1)
            except (AssertionError, OSError, ValueError):
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def close(self) -> None:
        process, connection = self._process, self._connection
        if process is not None and process.is_alive() and connection is not None:
            try:
                connection.send(None)
                process.join(timeout=1.0)
            except (BrokenPipeError, EOFError, OSError, ValueError):
                pass
        self._terminate()

    def analyze(
        self,
        path: str | Path,
        *,
        require_blur: bool,
        content_sha256: str | None,
        check_active: Callable[[], None] | None = None,
    ) -> dict:
        self._start()
        process, connection = self._process, self._connection
        assert process is not None and connection is not None
        request = {
            "path": str(Path(path)),
            "require_blur": bool(require_blur),
            "content_sha256": str(content_sha256 or ""),
        }
        try:
            connection.send(request)
        except (BrokenPipeError, EOFError, OSError, ValueError) as error:
            self._terminate()
            raise RuntimeError(f"CLEAN_ANALYSIS_WORKER_UNAVAILABLE: {error}") from error

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate()
                raise CleaningAnalysisTimeout(
                    f"CLEAN_ANALYSIS_TIMEOUT: image analysis exceeded {self.timeout_seconds:g}s"
                )
            try:
                ready = connection.poll(min(self.poll_seconds, remaining))
            except (EOFError, OSError, ValueError) as error:
                exit_code = process.exitcode
                self._terminate()
                raise RuntimeError(
                    f"CLEAN_ANALYSIS_WORKER_EXITED: exit_code={exit_code} error={error}"
                ) from error
            if ready:
                try:
                    response = connection.recv()
                except (EOFError, OSError) as error:
                    exit_code = process.exitcode
                    self._terminate()
                    raise RuntimeError(
                        f"CLEAN_ANALYSIS_WORKER_EXITED: exit_code={exit_code} error={error}"
                    ) from error
                break
            if check_active is not None:
                try:
                    check_active()
                except BaseException:
                    self._terminate()
                    raise
            if not process.is_alive():
                exit_code = process.exitcode
                self._terminate()
                raise RuntimeError(f"CLEAN_ANALYSIS_WORKER_EXITED: exit_code={exit_code}")

        if not isinstance(response, dict):
            raise RuntimeError("CLEAN_ANALYSIS_WORKER_INVALID_RESPONSE")
        if response.get("ok"):
            metrics = response.get("metrics")
            if not isinstance(metrics, dict):
                raise RuntimeError("CLEAN_ANALYSIS_WORKER_INVALID_METRICS")
            return metrics

        error_type = str(response.get("error_type") or "RuntimeError")
        message = str(response.get("error") or error_type)
        if error_type == "ImageDecodeError":
            raise ImageDecodeError(message)
        if error_type == "FileNotFoundError":
            raise FileNotFoundError(message)
        if error_type == "PermissionError":
            raise PermissionError(message)
        raise RuntimeError(f"{error_type}: {message}")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()
        return False


__all__ = [
    "ANALYSIS_POLL_SECONDS",
    "CleaningAnalysisRuntime",
    "CleaningAnalysisTimeout",
    "DEFAULT_ANALYSIS_TIMEOUT_SECONDS",
]
