"""Single source of truth for external compute-platform hierarchy and local chip bindings.

The dictionary lists local binding identities, not guarantees of converter support.
Remote provider IDs and classifications are always synchronized from ChangLian.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_ROOT_PARENT_IDS = frozenset({"", "0", "-1"})


def local_chip_key(value: Any) -> str:
    """Stable matching key: rk-3568 and RK3568 are the same local chip."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()

# SDK templates describe supported Adapter fields, never shell commands or business vendors.
CONVERSION_TEMPLATES = (
    {"id":"rknn","name":"瑞芯微 RKNN","adapter":"rockchip","version":1,"implemented":True,"default_precision":"fp16"},
    {"id":"atlas-atc","name":"华为 Atlas ATC","adapter":"ascend","version":1,"implemented":True,"default_precision":"fp16"},
    {"id":"huawei","name":"华为（待关联真实适配器）","adapter":"","version":1,"implemented":False},
    {"id":"tpu-mlir","name":"算能 TPU-MLIR","adapter":"sophon","version":1,"implemented":True,"default_precision":"fp16"},
    {"id":"cambricon","name":"寒武纪（待适配）","adapter":"","version":1,"implemented":False},
)


def conversion_templates():
    fields={
        "tpu-mlir":[{"key":"opset","label":"ONNX Opset","type":"number","default":12,"locked":True},
                    {"key":"simplify","label":"ONNX Simplify","type":"checkbox","default":False,"locked":True},
                    {"key":"num_core","label":"核心数","type":"number","default":1,"locked":True},
                    {"key":"dynamic","label":"动态Shape","type":"checkbox","default":False,"locked":True}],
        "rknn":[{"key":"mean","label":"RKNN Mean（三通道）","type":"text","default":"0,0,0"},
                {"key":"rknn_std","label":"RKNN Std（三通道）","type":"text","default":"255,255,255"}],
        "atlas-atc":[{"key":"input_name","label":"ONNX输入名","type":"text","default":"images"}],
    }
    return [{**item,"advanced_fields":[dict(f) for f in fields.get(item["id"],[])]} for item in CONVERSION_TEMPLATES]


def validate_conversion_catalog(payload):
    """One local identity catalog; external provider classifications are not part of it."""
    import json
    if not isinstance(payload, Mapping) or set(payload)-{"vendors","chips","revision"}:
        raise ValueError("字典只允许vendors/chips/revision")
    result = {"vendors":[], "chips":[]}
    templates = {x["id"] for x in CONVERSION_TEMPLATES}
    for kind, allowed in (
        ("vendors", {"id","name","template_id","enabled"}),
        ("chips", {"id","vendor_id","name","code","sdk_code","enabled","constraint_id"}),
    ):
        rows = payload.get(kind, [])
        if not isinstance(rows,list) or len(rows)>1000: raise ValueError("字典必须为有限数组")
        ids, codes = set(), set()
        for source in rows:
            if not isinstance(source,Mapping) or set(source)-allowed: raise ValueError("字典字段非法，不支持任意SDK命令")
            row = json.loads(json.dumps(source))
            for key in ("id","vendor_id","code","sdk_code","constraint_id") if kind=="chips" else ("id","template_id"):
                value = str(row.get(key) or "")
                if not (kind=="chips" and key in {"sdk_code","constraint_id"} and not value) and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}",value): raise ValueError(f"字典{key}格式非法")
                row[key]=value
            if row["id"] in ids: raise ValueError("字典ID重复")
            ids.add(row["id"])
            if not str(row.get("name") or "").strip() or len(str(row["name"]))>120: raise ValueError("字典名称缺失或过长")
            if type(row.get("enabled", True)) is not bool: raise ValueError("enabled必须为布尔值")
            row.setdefault("enabled",True)
            if kind=="vendors" and row["template_id"] not in templates: raise ValueError("模板不存在")
            if kind=="chips":
                if row["vendor_id"] not in {v["id"] for v in result["vendors"]}: raise ValueError("芯片所属厂商不存在")
                identity=(row["vendor_id"],row["code"].lower())
                sdk_identity=(row["vendor_id"],row["sdk_code"].lower())
                if identity in codes or (row["sdk_code"] and sdk_identity in codes): raise ValueError("芯片编码重复")
                codes.add(identity)
                if row["sdk_code"]: codes.add(sdk_identity)
            result[kind].append(row)
    return result


def resolve_chip_capability(catalog, *, vendor_id, chip_id, resource):
    """Shared SDK/chip admission facts for dictionary projection and conversion resolve."""
    vendors={v["id"]:v for v in catalog.get("vendors",[])}
    vendor=vendors.get(vendor_id)
    chip=next((c for c in catalog.get("chips",[]) if c["id"]==chip_id and c["vendor_id"]==vendor_id),None)
    template=next((t for t in conversion_templates() if vendor and t["id"]==vendor.get("template_id")),{})
    result={"ready":False,"status":"not_convertible","errors":[],"params":{},"parameter_sources":{},
            "vendor_id":vendor_id,"chip_id":chip_id,"template":dict(template),"allowed_precisions":[]}
    def reject(status,message):
        result.update(status=status,errors=[message])
        return result
    if vendor and not chip_id:
        return reject("pending_detection","请选择目标芯片")
    if not vendor or not vendor.get("enabled",True) or not chip or not chip.get("enabled",True):
        return reject("not_convertible","本地厂商或芯片不存在、已停用或归属不符")
    target=template.get("adapter")
    if not template.get("implemented") or not target:
        return reject("not_adapted","厂商模板尚无可执行Adapter")
    if not chip.get("sdk_code"):
        return reject("pending_configuration","尚未配置可信SDK目标编码；请核对高级配置与实际SDK检测")
    if resource.get("kind")!=target or resource.get("status")!="ready" or target not in resource.get("targets",[]):
        return reject("service_unavailable","对应转换资源未就绪或服务不可用")
    sdk=chip["sdk_code"].lower() if target!="ascend" else chip["sdk_code"]
    remote=resource.get("remote_health") or {}
    supported=resource.get("supported_chips",[]) if target!="ascend" else (
        resource.get("detected_soc_versions") or (remote.get("tools") or {}).get("soc_versions") or remote.get("soc_versions") or [])
    if sdk not in supported:
        return reject("not_convertible","当前SDK未声明支持所选目标芯片")
    if target=="sophon":
        from .sophon_runtime import sophon_chip_capabilities
        probe=resource.get("sophon_probe") or (resource.get("remote_health",{}).get("tools") or {}).get("sophon") or {}
        result["sdk_version"]=str(probe.get("version") or "")
        caps=sophon_chip_capabilities(probe)
        if "chip_capabilities" in probe:
            caps={code:{**cap,"precisions":[p for p in cap["precisions"] if p in (probe["chip_capabilities"].get(code) or {}).get("precisions",[])]}
                  for code,cap in caps.items() if (probe["chip_capabilities"].get(code) or {}).get("precisions")}
        cap=caps.get(sdk) or {}
        if not cap or not str(probe.get("version") or "").strip():
            return reject("pending_detection","缺少版本相关SDK/芯片精度兼容证据，请重新检测工具环境")
        allowed=cap["precisions"]
        effective="tpu-mlir-1.30.2" if cap.get("evidence")=="tpu-mlir-v1.30.2-regression/chip.py" else "sophon-fp16-verified"
    elif target=="rockchip":
        allowed=[p for p in resource.get("supported_precisions",[]) if p in {"fp16","int8"}]
        effective="rknn-verified"
    else:
        allowed=["fp16","fp32"]
        effective="atc-detected"
    result["constraint_id"]=effective
    result["allowed_precisions"]=list(allowed)
    if not allowed: return reject("pending_detection","所选芯片未确认合法精度")
    result.update(ready=True,status="convertible")
    return result


def resolve_conversion_contract(catalog, *, vendor_id, chip_id, resource, version, params, training_job=None):
    """The same backend contract drives preview and job admission; no execution here."""
    from .conversion import derive_version_conversion_defaults, validate_target
    result=resolve_chip_capability(catalog,vendor_id=vendor_id,chip_id=chip_id,resource=resource)
    if not result["ready"]: return result
    result.update(ready=False,status="not_convertible")
    template=result["template"];target=template["adapter"]
    chip=next(c for c in catalog["chips"] if c["id"]==chip_id)
    sdk=chip["sdk_code"].lower() if target!="ascend" else chip["sdk_code"]
    allowed=result["allowed_precisions"]
    def reject(status,message):
        result.update(status=status,errors=[message])
        return result
    defaults=derive_version_conversion_defaults(version,training_job)
    values={key:params[key] for key in params}
    input_contract=version.get("model_input_contract") or {}
    if not isinstance(input_contract,Mapping):
        return reject("not_convertible","冻结模型输入合同损坏")
    inherited_preprocessing=input_contract.get("preprocessing")
    if inherited_preprocessing and "preprocessing" not in values:
        if not isinstance(inherited_preprocessing,Mapping):
            return reject("not_convertible","冻结预处理合同损坏")
        values["preprocessing"]=dict(inherited_preprocessing)
    if input_contract.get("postprocessing"):
        if not isinstance(input_contract["postprocessing"],Mapping):
            return reject("not_convertible","冻结后处理合同损坏")
        values["model_output_contract"]=dict(input_contract["postprocessing"])
    for field in template["advanced_fields"]:
        values.setdefault(field["key"],field["default"])
    source_precision = str(defaults.get("training_precision") or "").lower()
    recommended = source_precision if source_precision in allowed else template.get("default_precision")
    precision=str(params.get("precision") or (recommended if recommended in allowed else allowed[0])).lower()
    result["precision_adjusted"] = bool(not params.get("precision") and source_precision in {"fp16", "fp32"} and precision != source_precision)
    result["precision_adjustment_reason"] = "已根据芯片能力调整转换精度" if result["precision_adjusted"] else ""
    if precision not in allowed: return reject("not_convertible","所选精度不受此芯片及SDK支持："+precision)
    if precision=="int8" and target=="sophon": return reject("not_convertible","Sophon INT8仍须冻结校准与质量验收，不允许通过字典绕过")
    if not any(key in values for key in ("input_height","input_width","input_size")):
        values.update(input_height=defaults["input_height"],input_width=defaults["input_width"])
    values.update(chip=sdk,precision=precision,local_vendor_id=vendor_id,local_chip_id=chip_id,
                  sdk_chip_code=sdk,template_id=template["id"],template_version=template["version"],
                  constraint_id=result["constraint_id"],resource_id=str(resource.get("id") or ""),
                  sdk_version=result.get("sdk_version",str(resource.get("version") or "")),source_training_precision=defaults.get("training_precision"))
    if target=="ascend": values["soc_version"]=sdk
    try: values=validate_target(target,values,require_calibration=False)
    except ValueError as error: return reject("not_convertible",str(error))
    result.update(ready=True,status="convertible",params=values,
                  calibration_required=precision=="int8",
                  parameter_sources={"precision":"用户自定义" if params.get("precision") else "源训练实际精度" if source_precision in allowed and len(allowed)>1 else "SDK/芯片约束",
                                     "input_shape":"用户自定义" if any(k in params for k in ("input_size","input_width","input_height")) else defaults["input_size_source"],
                                     "batch":"SDK/芯片约束","preprocessing":"用户自定义" if params.get("preprocessing") else "训练成果继承" if inherited_preprocessing else "厂商默认"})
    return result



# Configuration suggestions reference existing verified contracts, never resource availability.
_CONVERSION_CHIP_SUGGESTIONS=(
    ("tpu-mlir","BM1684X","bm1684x","sophon-fp16-verified"),
    ("tpu-mlir","BM1688","bm1688","sophon-fp16-verified"),
    ("tpu-mlir","BM1684","bm1684","tpu-mlir-1.30.2"),
    ("rknn","RK3568","rk3568","rknn-verified"),
    ("rknn","RK3576","rk3576","rknn-verified"),
)


def conversion_catalog_metadata(catalog, *, resources):
    """Read-only UI projection of existing resource detection records; no new probes."""
    suggestions=[dict(template_id=t,name=n,sdk_code=s,constraint_id=c)
                 for t,n,s,c in _CONVERSION_CHIP_SUGGESTIONS]
    capabilities={}
    for chip in catalog.get("chips",[]):
        vendor=next((v for v in catalog.get("vendors",[]) if v["id"]==chip["vendor_id"]),{})
        adapter=next((t["adapter"] for t in conversion_templates() if t["id"]==vendor.get("template_id")),"")
        matching=[r for r in resources if r.get("kind")==adapter]
        facts=[]
        for resource in matching:
            fact=resolve_chip_capability(catalog,vendor_id=chip["vendor_id"],chip_id=chip["id"],resource=resource)
            facts.append({**fact,"resource_id":resource.get("id",""),"resource_name":resource.get("name") or resource.get("id",""),
                          "mode":resource.get("mode","local"),"sdk_version":(resource.get("sophon_probe") or {}).get("version") or fact.get("sdk_version",resource.get("version") or ""),
                          "supported_chips":resource.get("supported_chips") or resource.get("detected_soc_versions") or [],
                          "last_checked_at":resource.get("last_checked_at"),"message":resource.get("message", ""),"solution":resource.get("solution") or "请在部署资源中检测对应SDK、解释器及目标芯片支持。"})
        fallback=resolve_chip_capability(catalog,vendor_id=chip["vendor_id"],chip_id=chip["id"],resource={})
        fact=next((f for f in facts if f["ready"]),None) or next((f for f in facts if f["status"]!="service_unavailable"),facts[0] if facts else fallback)
        capabilities[chip["id"]]={"sdk_ready":fact["ready"],"status":fact["status"],"allowed_precisions":fact["allowed_precisions"],
                                  "errors":fact["errors"],"resources":facts,"constraint_id":fact.get("constraint_id","")}
    return {"chip_suggestions":suggestions,"chip_capabilities":capabilities}


def conversion_catalog_records(catalog, *, entity, query="", vendor_id="", template_id="", enabled="", page=1, page_size=20, sort="name"):
    """One server query contract; filtered results never become a replacement catalog."""
    if entity not in {"vendors","chips"}: raise ValueError("字典类型必须为vendors或chips")
    if enabled not in {"","true","false"}: raise ValueError("启停筛选非法")
    if sort not in {"name","name_desc","id"}: raise ValueError("排序非法")
    if type(page) is not int or page<1 or type(page_size) is not int or not 1<=page_size<=100: raise ValueError("分页范围非法")
    vendors={v["id"]:v for v in catalog["vendors"]};templates={t["id"]:t for t in conversion_templates()}
    rows=[]
    for source in catalog[entity]:
        row=dict(source);vendor=row if entity=="vendors" else vendors.get(row["vendor_id"],{})
        if query.strip().casefold() not in str(row["name"]).casefold(): continue
        if vendor_id and entity=="chips" and row["vendor_id"]!=vendor_id: continue
        if template_id and vendor.get("template_id")!=template_id: continue
        if enabled and row.get("enabled",True)!=(enabled=="true"): continue
        template=templates.get(vendor.get("template_id"),{})
        row.update(template_id=vendor.get("template_id",""),template_name=template.get("name",""),implemented=bool(template.get("implemented")))
        if entity=="vendors":
            children=[c for c in catalog["chips"] if c["vendor_id"]==row["id"]]
            row.update(chip_count=len(children),enabled_chip_count=sum(c.get("enabled",True) for c in children))
        rows.append(row)
    rows.sort(key=lambda r:(str(r["id"]) if sort=="id" else str(r["name"]).casefold(),r["id"]),reverse=sort=="name_desc")
    total=len(rows);page=min(page,max(1,(total+page_size-1)//page_size));offset=(page-1)*page_size
    return {"items":rows[offset:offset+page_size],"total":total,"page":page,"page_size":page_size,"revision":catalog["revision"],"templates":conversion_templates()}


def new_conversion_catalog_record(catalog, entity, values):
    """Automatic local identities and only explicit, verified model-name suggestions."""
    import uuid
    allowed={"name","template_id","enabled"} if entity=="vendors" else {"name","vendor_id","code","sdk_code","constraint_id","enabled"}
    if set(values)-allowed: raise ValueError("新增字段非法，稳定ID由系统生成")
    identity=("vendor-" if entity=="vendors" else "chip-")+str(uuid.uuid4())
    row={"id":identity,"enabled":True,**values}
    if entity=="chips":
        vendor=next((v for v in catalog["vendors"] if v["id"]==values.get("vendor_id")),{})
        key=lambda n:re.sub(r"[\s_-]","",str(n or "").strip()).casefold()
        suggestion=next((s for s in _CONVERSION_CHIP_SUGGESTIONS if s[0]==vendor.get("template_id") and key(s[1])==key(values.get("name"))),None)
        row["code"]=row.get("code") or (suggestion[2] if suggestion else identity)
        row["sdk_code"]=row.get("sdk_code") or (suggestion[2] if suggestion else "")
        row["constraint_id"]=row.get("constraint_id") or (suggestion[3] if suggestion else "")
    return row


def compute_platform_catalog(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate the provider's flat parentId graph without changing its owner data."""
    catalog: dict[str, dict[str, Any]] = {}
    for source in rows:
        if not isinstance(source, Mapping):
            raise ValueError("算力环境记录必须是对象")
        row = dict(source)
        node_id = str(row.get("computePlatformId") or row.get("compute_platform_id") or row.get("id") or "").strip()
        if not node_id or node_id in catalog:
            raise ValueError("算力环境 ID 缺失或重复")
        catalog[node_id] = row

    for node_id, row in catalog.items():
        parent = compute_platform_parent(row)
        if parent and parent not in catalog:
            raise ValueError(f"算力环境 {node_id} 的父节点 {parent} 不在完整同步结果中")
        seen = {node_id}
        while parent:
            if parent in seen:
                raise ValueError(f"算力环境 {node_id} 的父子关系存在循环")
            seen.add(parent)
            parent = compute_platform_parent(catalog[parent])
    return catalog


def compute_platform_parent(node: Mapping[str, Any]) -> str:
    value = str(node.get("parentId") if node.get("parentId") is not None else "").strip()
    return "" if value in _ROOT_PARENT_IDS else value


def compute_platform_active(catalog: Mapping[str, Mapping[str, Any]], node_id: str) -> bool:
    current = str(node_id or "").strip()
    if current not in catalog:
        return False
    while current:
        node = catalog[current]
        if str(node.get("delFlag") if node.get("delFlag") is not None else 0).strip() != "0":
            return False
        current = compute_platform_parent(node)
    return True


def compute_platform_is_descendant(
    catalog: Mapping[str, Mapping[str, Any]], node_id: str, ancestor_id: str,
) -> bool:
    """Only a genuine child/grandchild is valid; a parent is not its own child."""
    current = compute_platform_parent(catalog.get(str(node_id), {}))
    while current:
        if current == str(ancestor_id):
            return True
        current = compute_platform_parent(catalog[current])
    return False


def compute_platform_has_children(
    catalog: Mapping[str, Mapping[str, Any]], parent_id: str,
) -> bool:
    return any(compute_platform_parent(row) == str(parent_id) for row in catalog.values())
