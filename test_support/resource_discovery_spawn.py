from pathlib import Path


def write_worker_stage(stage_dir, worker_id, stage):
    try:
        Path(stage_dir, f"worker-{worker_id}.stage").write_text(
            str(stage),
            encoding="utf-8",
        )
    except OSError:
        pass


def concurrent_cache_worker(
    path,
    start,
    result_queue,
    stage_dir,
    worker_id,
):
    from platform_core.resource_discovery.cache import DiscoveryCache

    write_worker_stage(stage_dir, worker_id, "entered")
    try:
        if not start.wait(15):
            raise RuntimeError("start gate timeout")

        write_worker_stage(stage_dir, worker_id, "gate_open")

        cache = DiscoveryCache(path)
        write_worker_stage(stage_dir, worker_id, "cache_ready")

        generation = cache.next_generation("environment")
        write_worker_stage(
            stage_dir,
            worker_id,
            f"generation_allocated:{generation}",
        )

        mode = cache.journal_mode()
        write_worker_stage(
            stage_dir,
            worker_id,
            f"journal_mode:{mode}",
        )

        result_queue.put(("ok", worker_id, generation, mode))
        write_worker_stage(stage_dir, worker_id, "reported")

    except BaseException as error:
        write_worker_stage(
            stage_dir,
            worker_id,
            f"error:{type(error).__name__}:{error}",
        )
        result_queue.put(
            ("error", worker_id, type(error).__name__, str(error))
        )


__all__ = ["concurrent_cache_worker", "write_worker_stage"]
