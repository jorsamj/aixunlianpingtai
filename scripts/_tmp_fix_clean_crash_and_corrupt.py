from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, replacement: str) -> str:
    pattern = rf"def {re.escape(name)}\(.*?(?=\n\ndef |\Z)"
    text, count = re.subn(pattern, replacement.rstrip(), text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{name}: expected one function, got {count}")
    return text


# Crash window: selection may already be frozen while upload-batch/material
# decision publication advanced the material repository revision. Reuse that
# prepared intent only when the semantic request still matches; repository_revision
# is a freeze-time concurrency token, not part of the user intent identity.
path = Path("app.py")
text = path.read_text(encoding="utf-8")
text = replace_function(
    text,
    "_v62_prepare_clean_compat",
    '''def _v62_prepare_clean_compat(project_id: str, payload: V47CleanReq, task_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    get_project(project_id)
    requested_id = str(task_id or uuid.uuid4().hex[:12])
    repository = shared_task_repository()
    existing = repository.get(requested_id)
    if existing is not None:
        if existing.project_id != project_id or existing.kind is not TaskKind.MATERIAL_BATCH:
            raise ValueError('清洗任务 ID 已被其他任务占用')
        request = _v47_material_batch_request(requested_id)
        if request.get('operation') != MaterialBatchOperation.CLEAN.value:
            raise ValueError('清洗任务 ID 已被其他批处理占用')
        return _v47_clean_compat_task(existing), False

    batch_payload = _v47_material_batch_payload(project_id, payload)
    prepared_request = _v47_material_batch_request(requested_id)
    if prepared_request:
        def semantic_request(value: Dict[str, Any]) -> Dict[str, Any]:
            value = dict(value or {})
            selection = dict(value.get('selection_spec') or {})
            selection.pop('repository_revision', None)
            return {
                'operation': value.get('operation'),
                'selection_spec': selection,
                'options': dict(value.get('options') or {}),
            }

        if semantic_request(prepared_request) != semantic_request(batch_payload):
            raise ValueError('清洗任务 ID 已关联不同请求')
        prepared = TaskRecord.new(
            requested_id, project_id, TaskKind.MATERIAL_BATCH, 'request.json',
            f'materials:{project_id}', required_capabilities=('materials.batch',),
        )
        return _v47_clean_compat_task(prepared), False

    prepared = prepare_material_batch(
        project_id,
        material_store(project_id),
        shared_task_artifacts(),
        batch_payload,
        task_id=requested_id,
    )
    return _v47_clean_compat_task(prepared), True''',
)
path.write_text(text, encoding="utf-8")


# A decoder failure is a successful cleaning finding when corrupt_check is
# enabled. It belongs in the review result as a corrupt issue, not in the
# worker-failure count. Storage/I/O/runtime failures still remain retryable failures.
path = Path("platform_core/cleaning_batches.py")
text = path.read_text(encoding="utf-8")
old = '''        except InterruptedError:
            raise
        except Exception as error:
            # A lost lease raises here before any writes. Ordinary file access
            # errors belong to this image and must not stop the remaining batch.
            check_active(context, "saving_clean_error", image_id)
            public_error = redact_storage_error(error)
            if result is None:
                # A storage outage or missing blur engine is not a corrupt image.
                corrupt = isinstance(error, ImageDecodeError) and options["corrupt_check"]
                result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                          "status": "failed", "error": public_error, "metrics": {},
                          "issues": [{"code": "corrupt", "name": "图片损坏", "detail": public_error}] if corrupt else [],
                          "suggest_delete": False, "inspected_at": utc_now()}
                _save_result(manifest, image_id, result, index)
            check_active(context, "saving_clean_error", image_id)
            try:
                _transform_many(materials, [image_id], lambda row: {
                    **row, "clean_status": "failed", "clean_result_task_id": context.task.task_id,
                    "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"],
                }, batch_size=1)
            except Exception as save_error:
                append_task_log(context, "clean_status_error", f"image_id={image_id} {redact_storage_error(save_error)}")
            manifest.transition([image_id], "failed", public_error)
            append_task_log(context, "clean_error", f"image_id={image_id} {public_error}")
'''
new = '''        except InterruptedError:
            raise
        except Exception as error:
            # A lost lease raises here before any writes. A decoder failure is a
            # valid cleaning finding when corrupt_check is enabled; provider/I/O
            # and runtime failures remain retryable item failures.
            check_active(context, "saving_clean_error", image_id)
            public_error = redact_storage_error(error)
            corrupt_finding = isinstance(error, ImageDecodeError) and options["corrupt_check"]
            if corrupt_finding:
                result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                          "status": "succeeded", "metrics": {},
                          "issues": [{"code": "corrupt", "name": "图片损坏", "detail": public_error}],
                          "suggest_delete": True, "inspected_at": utc_now()}
                _save_result(manifest, image_id, result, index)
                check_active(context, "saving_clean_result", image_id)
                _transform_many(materials, [image_id], lambda row: {
                    **row, "clean_status": "needs_review", "clean_result_task_id": context.task.task_id,
                    "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"],
                }, batch_size=1)
                manifest.transition([image_id], "succeeded")
                append_task_log(context, "clean_flagged", f"image_id={image_id} issues=corrupt")
            else:
                if result is None:
                    result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                              "status": "failed", "error": public_error, "metrics": {},
                              "issues": [], "suggest_delete": False, "inspected_at": utc_now()}
                    _save_result(manifest, image_id, result, index)
                check_active(context, "saving_clean_error", image_id)
                try:
                    _transform_many(materials, [image_id], lambda row: {
                        **row, "clean_status": "failed", "clean_result_task_id": context.task.task_id,
                        "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"],
                    }, batch_size=1)
                except Exception as save_error:
                    append_task_log(context, "clean_status_error", f"image_id={image_id} {redact_storage_error(save_error)}")
                manifest.transition([image_id], "failed", public_error)
                append_task_log(context, "clean_error", f"image_id={image_id} {public_error}")
'''
text = replace_once(text, old, new, "corrupt cleaning review semantics")
path.write_text(text, encoding="utf-8")
