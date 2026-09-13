from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


OLD_BATCH_HEAD = '''def _v50_end_image_batch(save: bool = True):
    batch = getattr(_IMAGE_BATCH_CTX, "batch", None)
    _IMAGE_BATCH_CTX.batch = None
    if not save or not batch:
        return []
    project_id = str(batch.get("project_id") or "")
    records = [dict(record) for record in batch.get("records", {}).values()]
    patches = {
        str(image_id): dict(patch)
        for image_id, patch in batch.get("patches", {}).items()
    }
    if not records and not patches:
        return []
'''

NEW_BATCH_HEAD = '''def _v50_end_image_batch(save: bool = True):
    batch = getattr(_IMAGE_BATCH_CTX, "batch", None)
    _IMAGE_BATCH_CTX.batch = None
    if not batch:
        return []
    project_id = str(batch.get("project_id") or "")
    records = [dict(record) for record in batch.get("records", {}).values()]
    patches = {
        str(image_id): dict(patch)
        for image_id, patch in batch.get("patches", {}).items()
    }
    if not save:
        cleanup_errors = _v50_cleanup_buffered_image_batch_files(project_id, records)
        if cleanup_errors:
            raise RuntimeError(
                "批量导入回滚失败：" + "; ".join(cleanup_errors)
            )
        return []
    if not records and not patches:
        return []
'''

OLD_WORKER_FINALIZE = '''                report["labels"] = get_project(project_id).get("labels", [])
            finally:
                # 图片与摘要先按 ID 缓冲，在这里基于最新索引一次性提交。
                _v50_end_image_batch(save=True)
'''

NEW_WORKER_FINALIZE = '''                report["labels"] = get_project(project_id).get("labels", [])
            except BaseException:
                # Importers persist image bytes and annotation truth before the
                # buffered material projection is committed. A failed import must
                # remove those durable side effects instead of publishing a partial
                # dataset under a failed job.
                if _v50_active_image_batch(project_id):
                    _v50_end_image_batch(save=False)
                raise
            else:
                # 图片与摘要先按 ID 缓冲，在这里基于最新索引一次性提交。
                _v50_end_image_batch(save=True)
'''

OLD_HTTP_EXCEPT = '''    except HTTPException as e:
        _v50_end_image_batch(save=True)
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
'''

NEW_HTTP_EXCEPT = '''    except HTTPException as e:
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
'''

OLD_GENERIC_EXCEPT = '''    except Exception as e:
        _v50_end_image_batch(save=True)
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
'''

NEW_GENERIC_EXCEPT = '''    except Exception as e:
        v19_update_job(project_id, job_id, status="failed", stage="导入失败", progress=100,
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP_PATH.read_text(encoding="utf-8")
    text = replace_once(text, OLD_BATCH_HEAD, NEW_BATCH_HEAD, "batch abort cleanup")
    text = replace_once(text, OLD_WORKER_FINALIZE, NEW_WORKER_FINALIZE, "worker finalize")
    text = replace_once(text, OLD_HTTP_EXCEPT, NEW_HTTP_EXCEPT, "HTTP failure path")
    text = replace_once(text, OLD_GENERIC_EXCEPT, NEW_GENERIC_EXCEPT, "generic failure path")
    APP_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
