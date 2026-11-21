"""Request-local buffering must survive concurrent async plain-image uploads."""

import asyncio

from app import (
    _v50_active_image_batch,
    _v50_begin_image_batch,
    _v50_end_image_batch,
)


def test_async_image_batch_context_isolated_for_same_and_other_projects():
    async def concurrent_upload(project_id, marker):
        assert _v50_active_image_batch(project_id) is None
        _v50_begin_image_batch(project_id)
        try:
            owned = _v50_active_image_batch(project_id)
            assert owned is not None
            owned["request_marker"] = marker
            await asyncio.sleep(0)  # UploadFile.seek yields between files.
            assert _v50_active_image_batch(project_id) is owned
            assert owned["request_marker"] == marker
        finally:
            assert _v50_end_image_batch(save=True) == []
        assert _v50_active_image_batch(project_id) is None

    async def run():
        await asyncio.gather(
            concurrent_upload("project-1", "request-A"),
            concurrent_upload("project-1", "request-B"),
            concurrent_upload("project-2", "request-C"),
        )

    asyncio.run(run())
