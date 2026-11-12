"""Lease the existing task workspace only while a verified report file is sent."""
from pathlib import Path

from filelock import FileLock, Timeout
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse

from .training_bundle_cache import _resolve_relative
from .training_workspace_lifecycle import _sha


class TrainingEvidenceFileResponse(FileResponse):
    def __init__(self, path, *, workspace_root, expected_sha256, **kwargs):
        super().__init__(path, **kwargs)
        self.workspace_root = Path(workspace_root)
        self.expected_sha256 = expected_sha256

    async def __call__(self, scope, receive, send):
        lock = FileLock(str(self.workspace_root / "workspace-access.lock"),
                        timeout=5, thread_local=False)
        try:
            await run_in_threadpool(lock.acquire)
        except Timeout:
            return await JSONResponse({"detail": {"code": "WORKSPACE_BUSY", "retryable": True}},
                                      status_code=503)(scope, receive, send)
        try:
            relative = Path(self.path).relative_to(self.workspace_root).as_posix()
            candidate = _resolve_relative(self.workspace_root, relative)
            if not candidate.is_file() and relative.startswith("work/bundle/"):
                candidate = _resolve_relative(self.workspace_root,
                    "evidence/bundle/" + relative[len("work/bundle/"):])
            if (not candidate.is_file()
                    or await run_in_threadpool(_sha, candidate) != self.expected_sha256):
                return await JSONResponse({"detail": {"code": "IMAGE_EVIDENCE_CHANGED", "retryable": False}},
                                          status_code=409)(scope, receive, send)
            self.path = candidate
            await super().__call__(scope, receive, send)
        finally:
            lock.release()
