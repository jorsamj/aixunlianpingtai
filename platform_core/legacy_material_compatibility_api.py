"""Removable operator routes; all writes stay in the canonical material owner."""
from fastapi import APIRouter, Body, HTTPException, Query, Request


def legacy_material_compatibility_router(service_provider, actor_provider):
    router = APIRouter(prefix="/api/v62/projects/{project_id}/legacy-material-compatibility")

    def service(request, project_id):
        actor = actor_provider(request, project_id)
        if not str((actor or {}).get("actor_id") or "").strip():
            raise HTTPException(401, detail="请先登录平台")
        return service_provider(project_id)

    def public(result):
        result = {key: value for key, value in result.items() if not key.startswith("_")}
        if "items" in result:
            result["items"] = [{key: value for key, value in item.items()
                                if key in {"image_id", "status", "issues", "candidate", "material_owner", "proposed", "ground_truth", "gt_status", "categories"}}
                               for item in result["items"]]
        return result

    def execute(operation):
        try:
            return {"ok": True, **public(operation())}
        except KeyError as error:
            raise HTTPException(404, detail="项目或素材不存在") from error
        except ValueError as error:
            raise HTTPException(422, detail="数据无法安全确认，请重新只读检查本批；不支持的数据不会修改") from error
        except RuntimeError as error:
            raise HTTPException(409, detail="工具已关闭，或素材/GT版本已变化；请重新检查并预览，不要重复创建迁移") from error
        except OSError as error:
            raise HTTPException(503, detail="读取或备份未完成；原数据保持，使用同一批次身份安全重试") from error

    def ids(payload):
        values = payload.get("image_ids")
        if (not isinstance(values, list) or not 1 <= len(values) <= 50
                or any(not isinstance(value, str) or not value for value in values)):
            raise HTTPException(422, detail="每批需要1至50个明确的图片身份")
        return values

    @router.get("/scan")
    def scan(project_id: str, request: Request, cursor: str = "", limit: int = Query(50, ge=1, le=50),
             expected_catalog: str = Query("", max_length=64)):
        selected = service(request, project_id)
        return execute(lambda: selected.scan(cursor=cursor, limit=limit, **({"expected_catalog": expected_catalog} if expected_catalog else {})))

    @router.post("/preview")
    def preview(project_id: str, request: Request, payload: dict = Body(...)):
        selected = service(request, project_id)
        image_ids = ids(payload)
        return execute(lambda: selected.preview(image_ids))

    @router.post("/apply")
    def apply(project_id: str, request: Request, payload: dict = Body(...)):
        selected = service(request, project_id)
        image_ids = ids(payload)
        if (payload.get("confirm") != "migrate_legacy_material_metadata"
                or not isinstance(payload.get("expected_fingerprint"), str)
                or not isinstance(payload.get("task_id"), str)):
            raise HTTPException(422, detail="请先预览并明确确认本批元数据迁移")
        return execute(lambda: selected.apply(image_ids, expected_fingerprint=payload["expected_fingerprint"],
                                             task_id=payload["task_id"], confirmed=True))

    return router
