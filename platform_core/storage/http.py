"""Keep the canonical source byte lease for the original FileResponse lifetime."""
from contextlib import nullcontext
from pathlib import Path

from filelock import Timeout
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse


class StoredSourceFileResponse(FileResponse):
    def __init__(self, path, *, manager, material, **kwargs):
        super().__init__(path, **kwargs)
        self.manager = manager
        self.material = material

    async def __call__(self, scope, receive, send):
        # The canonical manager provides the lease; legacy test adapters have
        # no physical reclamation implementation and keep their original IO.
        factory = getattr(self.manager, 'source_byte_lease', None)
        lease = factory(self.material, timeout=5) if factory else nullcontext()
        try:
            await run_in_threadpool(lease.__enter__)
        except Timeout:
            return await JSONResponse({'detail':{'code':'SOURCE_BUSY','retryable':True}},
                                      status_code=503)(scope, receive, send)
        try:
            if not Path(self.path).is_file():
                return await JSONResponse({'detail':{'code':'ORIGINAL_IMAGE_MISSING','retryable':False}},
                                          status_code=404)(scope, receive, send)
            await super().__call__(scope, receive, send)
        finally:
            lease.__exit__(None, None, None)
