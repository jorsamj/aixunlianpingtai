"""v39 catalog HTTP boundary. The host owns auth, repositories and SDK execution."""
from typing import Any, Callable, Dict
from fastapi import APIRouter, HTTPException
from platform_core.errors import PlatformError
from platform_core.model_artifacts import ModelArtifactRepository


def create_conversion_catalog_router(
    repository_provider: Callable[[], ModelArtifactRepository],
    list_resources: Callable[..., dict],
    detect_resource: Callable[[str], dict],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v39/deploy/catalog")
    def v39_conversion_catalog():
        from platform_core.compute_platform_catalog import conversion_templates, conversion_catalog_metadata
        catalog=repository_provider().conversion_catalog()
        metadata=conversion_catalog_metadata(catalog,resources=list_resources(detect_missing=False)["items"])
        from platform_core.conversion_csc import CONTRACT_TARGETS, csc_capabilities
        return {"ok":True, **catalog, **metadata, "templates":conversion_templates(),
                "csc_capabilities_by_target":{target:csc_capabilities(target) for target in CONTRACT_TARGETS},
                "constraint_ids":["tpu-mlir-1.30.2","sophon-fp16-verified","rknn-verified","atc-detected"]}


    @router.put("/api/v39/deploy/catalog")
    def v39_save_conversion_catalog(payload: Dict[str, Any]):
        try:
            saved=repository_provider().save_conversion_catalog(
                {k:v for k,v in payload.items() if k!="expected_revision"}, expected_revision=payload.get("expected_revision"))
            from platform_core.compute_platform_catalog import conversion_catalog_metadata
            return {"ok":True, **saved, **conversion_catalog_metadata(saved,resources=list_resources()["items"])}
        except ValueError as error:
            raise HTTPException(status_code=409 if "revision" in str(error) else 400,detail=str(error)) from error


    @router.get("/api/v39/deploy/catalog/records")
    def v39_catalog_records(entity: str="vendors", query: str="", vendor_id: str="", template_id: str="", enabled: str="", page: int=1, page_size: int=20, sort: str="name", observe_only: bool=False):
        from platform_core.compute_platform_catalog import conversion_catalog_records, conversion_catalog_metadata
        catalog=repository_provider().conversion_catalog()
        try: result=conversion_catalog_records(catalog,entity=entity,query=query,vendor_id=vendor_id,template_id=template_id,enabled=enabled,page=page,page_size=page_size,sort=sort)
        except ValueError as error: raise PlatformError("CATALOG_INVALID_QUERY",str(error),"",status_code=422) from error
        if entity=="chips":
            resources = list_resources(detect_missing=False) if observe_only else list_resources()
            facts=conversion_catalog_metadata({**catalog,"chips":result["items"]},resources=resources["items"])
            result["items"]=[{**r,"capability":facts["chip_capabilities"][r["id"]]} for r in result["items"]]
        return {"ok":True,**result}


    @router.get("/api/v39/deploy/catalog/records/{entity}/{identity}")
    def v39_catalog_record(entity: str, identity: str, observe_only: bool=False):
        from platform_core.compute_platform_catalog import conversion_catalog_records, conversion_catalog_metadata
        if entity not in {"vendors","chips"}: raise PlatformError("CATALOG_INVALID_QUERY","字典类型非法",entity,status_code=422)
        repository=repository_provider()
        references=repository.conversion_catalog_references(entity,identity,diagnostic=True)
        row=references.pop("record")
        catalog=repository.conversion_catalog()
        rows=conversion_catalog_records({**catalog,entity:[row]},entity=entity)["items"]
        item=rows[0]
        if entity=="chips":
            resources = list_resources(detect_missing=False) if observe_only else list_resources()
            item["capability"]=conversion_catalog_metadata({**catalog,"chips":[row]},resources=resources["items"])["chip_capabilities"][identity]
        return {"ok":True,"item":item,"revision":references["revision"],"references":references}


    @router.post("/api/v39/deploy/catalog/operations")
    def v39_catalog_operation(payload: Dict[str, Any]):
        return repository_provider().mutate_conversion_catalog(payload)


    @router.get("/api/v39/deploy/catalog/operations/{operation_id}")
    def v39_catalog_operation_result(operation_id: str):
        return repository_provider().conversion_catalog_operation(operation_id)


    @router.post("/api/v39/deploy/catalog/chips/{identity}/detect")
    def v39_catalog_detect_chip(identity: str, payload: Dict[str, Any]):
        from platform_core.compute_platform_catalog import conversion_templates, conversion_catalog_metadata
        if set(payload)-{"resource_ids"}: raise PlatformError("CATALOG_INVALID_REQUEST","检测参数非法","",status_code=422)
        catalog=repository_provider().conversion_catalog()
        chip=next((c for c in catalog["chips"] if c["id"]==identity),None)
        if not chip: raise PlatformError("CATALOG_NOT_FOUND","芯片不存在",identity,status_code=404)
        vendor=next(v for v in catalog["vendors"] if v["id"]==chip["vendor_id"])
        adapter=next(t["adapter"] for t in conversion_templates() if t["id"]==vendor["template_id"])
        resources=[r for r in list_resources()["items"] if r.get("kind")==adapter]
        ids=payload.get("resource_ids")
        if ids is not None:
            if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids): raise PlatformError("CATALOG_INVALID_REQUEST","资源ID必须为数组","",status_code=422)
            if set(ids)-{r["id"] for r in resources}: raise PlatformError("CATALOG_RESOURCE_MISMATCH","资源不存在或不属于该SDK模板","",status_code=422)
            resources=[r for r in resources if r["id"] in ids]
        if not resources: raise PlatformError("CATALOG_RESOURCE_UNAVAILABLE","暂无该模板的可检测资源","", "请先登记本机、远程或Agent部署资源。",409)
        checked=[detect_resource(r["id"]) for r in resources]
        facts=conversion_catalog_metadata({**catalog,"chips":[chip]},resources=checked)["chip_capabilities"][identity]
        return {"ok":True,"id":identity,"revision":catalog["revision"],"capability":facts,"detected_resource_ids":[r["id"] for r in checked]}

    return router
