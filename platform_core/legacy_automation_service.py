"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from fastapi import HTTPException
from .legacy_automation_contracts import V42AlgorithmBlueprintReq, V42CollectReq, V42SourceReq

import threading
import uuid
from datetime import datetime
from platform_core.labels import label_governance_fence
from platform_core.algorithm_catalog_contracts import AlgorithmReq
from platform_core.ai_configuration_contracts import V35ModelConfigReq

@dataclass(frozen=True)
class LegacyAutomationDependencies:
    MODEL_CONFIGS_FILE: Callable[..., Any]
    V42_INDUSTRY_TEMPLATES: Callable[..., Any]
    _parse_dt_value: Callable[..., Any]
    _v35_is_vision_provider: Callable[..., Any]
    _v35_items: Callable[..., Any]
    _v42_get: Callable[..., Any]
    _v42_latest_algorithm_job: Callable[..., Any]
    _v42_list: Callable[..., Any]
    _v42_metrics_from_job: Callable[..., Any]
    _v42_run_collect: Callable[..., Any]
    _v42_save: Callable[..., Any]
    _v42_source_test: Callable[..., Any]
    dataset_quality_report: Callable[..., Any]
    ensure_default_datasets: Callable[..., Any]
    ensure_label: Callable[..., Any]
    get_project: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    load_images: Callable[..., Any]
    normalize_label: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    resolve_material_path: Callable[..., Any]
    v12_create_algorithm: Callable[..., Any]
    v35_test_model_config: Callable[..., Any]
    v35_test_saved_model_annotation: Callable[..., Any]


class LegacyAutomationService:
    def __init__(self, dependencies: LegacyAutomationDependencies):
        self.dependencies = dependencies

    def v42_industry_templates(self, ):
        return {"ok": True, "items": self.dependencies.V42_INDUSTRY_TEMPLATES()}

    def v42_list_algorithm_blueprints(self, project_id: str):
        self.dependencies.get_project(project_id)
        return {"ok": True, "items": self.dependencies._v42_list(project_id, 'algorithm_blueprints')}

    def v42_create_algorithm_blueprint(self, project_id: str, payload: V42AlgorithmBlueprintReq):
        self.dependencies.get_project(project_id)
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail='算法名称不能为空')
        alg = self.dependencies.v12_create_algorithm(project_id, AlgorithmReq(
            name=payload.name.strip(), remark=payload.remark or '', industry=payload.industry or '',
            algorithm_type=payload.algorithm_type or 'yolo_ultralytics'
        ))
        with label_governance_fence(self.dependencies.project_dir(project_id)):
            project = self.dependencies.get_project(project_id)
            for raw in payload.labels or []:
                code = self.dependencies.normalize_label(raw)
                if code:
                    self.dependencies.ensure_label(project, code)
                    project = self.dependencies.get_project(project_id)
        blueprints = self.dependencies._v42_list(project_id, 'algorithm_blueprints')
        item = {
            "id": uuid.uuid4().hex[:12], "algorithm_id": alg.get("id"), "name": payload.name.strip(),
            "industry": payload.industry or '', "algorithm_type": payload.algorithm_type or 'yolo_ultralytics',
            "template_id": payload.template_id or 'custom',
            "labels": [self.dependencies.normalize_label(x) for x in payload.labels if self.dependencies.normalize_label(x)],
            "focus_scenes": payload.focus_scenes or '', "negative_scenes": payload.negative_scenes or '',
            "created_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso()
        }
        blueprints.insert(0, item); self.dependencies._v42_save(project_id, 'algorithm_blueprints', blueprints[:200])
        return {"ok": True, "algorithm": alg, "blueprint": item, "labels": self.dependencies.get_project(project_id).get('labels', [])}

    def v42_list_sources(self, project_id: str):
        self.dependencies.get_project(project_id); return {"ok": True, "items": [self._v42_enrich_source(project_id,x) for x in self.dependencies._v42_list(project_id, 'sources')]}

    def v42_create_source(self, project_id: str, payload: V42SourceReq):
        self.dependencies.get_project(project_id)
        if not payload.name.strip() or not payload.source.strip():
            raise HTTPException(status_code=400, detail='名称和来源地址不能为空')
        if payload.type not in {'folder','rtsp','http_json'}:
            raise HTTPException(status_code=400, detail='来源类型只支持 folder / rtsp / http_json')
        if payload.collect_mode not in {'manual','auto'}:
            raise HTTPException(status_code=400, detail='执行方式只支持 manual / auto')
        if payload.schedule_type not in {'interval','daily'}:
            raise HTTPException(status_code=400, detail='自动执行周期只支持 interval / daily')
        rows = self.dependencies._v42_list(project_id, 'sources')
        item = {"id": uuid.uuid4().hex[:12], **payload.dict(), "status":"unchecked", "message":"未检测", "created_at":self.dependencies.now_iso(), "updated_at":self.dependencies.now_iso()}
        rows.insert(0, item); self.dependencies._v42_save(project_id, 'sources', rows[:100]); return item

    def v42_update_source(self, project_id: str, source_id: str, payload: V42SourceReq):
        rows=self.dependencies._v42_list(project_id,'sources')
        for i,x in enumerate(rows):
            if x.get('id')==source_id:
                rows[i]={**x,**payload.dict(),"updated_at":self.dependencies.now_iso()};self.dependencies._v42_save(project_id,'sources',rows);return rows[i]
        raise HTTPException(status_code=404,detail='素材源不存在')

    def v42_delete_source(self, project_id: str, source_id: str):
        rows=self.dependencies._v42_list(project_id,'sources');self.dependencies._v42_save(project_id,'sources',[x for x in rows if x.get('id')!=source_id]);return {"ok":True}

    def v42_test_source(self, project_id: str, source_id: str):
        rows=self.dependencies._v42_list(project_id,'sources');item=next((x for x in rows if x.get('id')==source_id),None)
        if not item:raise HTTPException(status_code=404,detail='素材源不存在')
        result=self.dependencies._v42_source_test(item)
        for x in rows:
            if x.get('id')==source_id:x.update(status='ready' if result['ok'] else 'failed',message=result['message'],last_checked_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso())
        self.dependencies._v42_save(project_id,'sources',rows)
        if not result['ok']: raise HTTPException(status_code=400,detail=result['message'])
        return {"ok":True,**result}

    def v42_collection_runs(self, project_id: str):return {"ok":True,"items":self.dependencies._v42_list(project_id,'collection_runs')}

    def v42_collect(self, project_id: str, source_id: str, payload: V42CollectReq):
        source=self.dependencies._v42_get(project_id,'sources',source_id)
        if not source:raise HTTPException(status_code=404,detail='素材源不存在')
        run={"id":uuid.uuid4().hex[:12],"source_id":source_id,"source_name":source.get('name'),"dataset_id":payload.dataset_id,"status":"queued","stage":"等待采集","progress":0,"imported":0,"created_at":self.dependencies.now_iso(),"updated_at":self.dependencies.now_iso()}
        rows=self.dependencies._v42_list(project_id,'collection_runs');rows.insert(0,run);self.dependencies._v42_save(project_id,'collection_runs',rows[:100])
        th=threading.Thread(target=self.dependencies._v42_run_collect,args=(project_id,run['id'],source,payload.dict()),daemon=True);th.start();return run

    def v42_test_saved_model_config(self, config_id: str):
        item=next((x for x in self.dependencies._v35_items(self.dependencies.MODEL_CONFIGS_FILE()) if x.get('id')==config_id),None)
        if not item:raise HTTPException(status_code=404,detail='模型配置不存在')
        return self.dependencies.v35_test_saved_model_annotation(config_id) if self.dependencies._v35_is_vision_provider(item) else self.dependencies.v35_test_model_config(V35ModelConfigReq(**item))

    def v42_policies(self, project_id: str):self.dependencies.get_project(project_id);return {"ok":True,"items":self.dependencies._v42_list(project_id,'iteration_policies')}

    def v42_delete_policy(self, project_id:str,policy_id:str):
        rows=self.dependencies._v42_list(project_id,'iteration_policies');self.dependencies._v42_save(project_id,'iteration_policies',[x for x in rows if x.get('id')!=policy_id]);return {"ok":True}

    def v42_online_feedback(self, project_id: str, algorithm_id: Optional[str] = None):
        self.dependencies.get_project(project_id);rows=self.dependencies._v42_list(project_id,'online_feedback')
        if algorithm_id:rows=[x for x in rows if x.get('algorithm_id')==algorithm_id]
        return {"ok":True,"items":rows[:500],"summary":self._v42_audit_summary(project_id,algorithm_id) if algorithm_id else None}

    def v42_dataset_hygiene(self, project_id: str, dataset_id: str, max_scan: int = 1000):
        return {"ok":True,"report":self._v42_hygiene_report(project_id,dataset_id,max_scan)}

    def v42_iteration_runs(self, project_id:str):return {"ok":True,"items":self.dependencies._v42_list(project_id,'iteration_runs')}

    def v42_quality_overview(self, project_id:str):
        self.dependencies.get_project(project_id);datasets=self.dependencies.ensure_default_datasets(project_id);ds=[]
        for d in datasets:
            try:q=self.dependencies.dataset_quality_report(project_id,d.get('id') or 'default',False)
            except Exception as e:q={"image_count":0,"box_count":0,"can_train":False,"warnings":[str(e)]}
            try:hygiene=self._v42_hygiene_report(project_id,d.get('id') or 'default',500)
            except Exception as e:hygiene={"scanned":0,"duplicate_count":0,"blurry_count":0,"low_resolution_count":0,"broken_count":0,"error":str(e)}
            ds.append({"id":d.get('id'),"name":d.get('name'),"quality":q,"hygiene":hygiene})
        algos=[]
        for a in self.dependencies.list_algorithms_internal(project_id):
            jid=self.dependencies._v42_latest_algorithm_job(project_id,a.get('id') or '');metrics=self.dependencies._v42_metrics_from_job(project_id,jid) if jid else {"precision":None,"recall":None,"map50":None,"report":{}}
            algos.append({"id":a.get('id'),"name":a.get('name'),"versions":len(a.get('versions') or []),"job_id":jid,"metrics":metrics,"online_audit":self._v42_audit_summary(project_id,a.get('id') or '')})
        return {"ok":True,"datasets":ds,"algorithms":algos,"sources":self.dependencies._v42_list(project_id,'sources'),"policies":self.dependencies._v42_list(project_id,'iteration_policies'),"runs":self.dependencies._v42_list(project_id,'iteration_runs')[:20]}

    def _v42_source_last_run(self, project_id: str, source_id: str) -> Optional[Dict[str, Any]]:
        runs=[r for r in self.dependencies._v42_list(project_id,'collection_runs') if r.get('source_id')==source_id]
        if not runs:return None
        runs.sort(key=lambda x:str(x.get('created_at') or ''),reverse=True)
        return runs[0]

    def _v42_source_next_run(self, item: Dict[str, Any], last_run: Optional[Dict[str, Any]]=None, now: Optional[datetime]=None) -> Optional[str]:
        if not item.get('enabled', True) or item.get('collect_mode','manual')!='auto':return None
        now=now or datetime.now(); typ=item.get('schedule_type') or 'interval'; raw=str(item.get('schedule_value') or '60').strip()
        if typ=='daily':
            try:
                hh,mm=[int(x) for x in raw.split(':',1)]
                hh=max(0,min(23,hh));mm=max(0,min(59,mm))
            except Exception:
                hh,mm=2,0
            candidate=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
            if candidate<=now:
                from datetime import timedelta
                candidate+=timedelta(days=1)
            return candidate.strftime('%Y-%m-%d %H:%M:%S')
        try: minutes=max(1,int(float(raw)))
        except Exception: minutes=60
        from datetime import timedelta
        base=self.dependencies._parse_dt_value((last_run or {}).get('finished_at') or (last_run or {}).get('created_at') or item.get('created_at')) or now
        candidate=base+timedelta(minutes=minutes)
        # New auto sources should be eligible quickly rather than waiting from an old creation timestamp.
        if not last_run and candidate<now:candidate=now
        return candidate.strftime('%Y-%m-%d %H:%M:%S')

    def _v42_enrich_source(self, project_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
        out=dict(item); last=self._v42_source_last_run(project_id,item.get('id') or '')
        out['last_run']=last
        out['last_completed_at']=(last or {}).get('finished_at') or ''
        out['last_imported']=(last or {}).get('imported',0)
        out['next_run_at']=self._v42_source_next_run(item,last)
        if last and last.get('status') in {'queued','running'}:out['runtime_status']=last.get('status')
        elif item.get('enabled') is False:out['runtime_status']='disabled'
        elif last and last.get('status')=='failed':out['runtime_status']='failed'
        else:out['runtime_status']=item.get('status') or 'unchecked'
        return out

    def _v42_audit_summary(self, project_id: str, algorithm_id: str, limit: int = 500) -> Dict[str, Any]:
        rows=[x for x in self.dependencies._v42_list(project_id,'online_feedback') if x.get('algorithm_id')==algorithm_id][:max(1,limit)]
        total=len(rows);correct=sum(1 for x in rows if bool(x.get('correct')))
        cats={}
        for x in rows:
            if x.get('correct'):continue
            k=str(x.get('category') or '其他问题').strip() or '其他问题';cats[k]=cats.get(k,0)+1
        return {"total":total,"correct":correct,"incorrect":total-correct,"accuracy":(correct/total if total else None),"error_categories":cats,"recent":rows[:30]}

    def _v42_hygiene_report(self, project_id: str, dataset_id: str, max_scan: int = 1000) -> Dict[str, Any]:
        import hashlib
        self.dependencies.get_project(project_id);rows=[]
        for x in self.dependencies.load_images(project_id) or []:
            if str(x.get('dataset_id') or 'default')==str(dataset_id):rows.append(x)
        rows=rows[:max(1,min(5000,max_scan))]
        seen={};dups=[];broken=[];blurry=[];lowres=[];extreme=[]
        try:import cv2
        except Exception:cv2=None
        for x in rows:
            try:
                fp=self.dependencies.resolve_material_path(project_id,x)
                h=hashlib.sha256(fp.read_bytes()).hexdigest()
                if h in seen:dups.append({"id":x.get('id'),"same_as":seen[h]})
                else:seen[h]=x.get('id')
                if cv2 is not None:
                    im=cv2.imread(str(fp))
                    if im is None:broken.append(x.get('id'));continue
                    hh,ww=im.shape[:2]
                    if min(hh,ww)<320:lowres.append(x.get('id'))
                    gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
                    if float(cv2.Laplacian(gray,cv2.CV_64F).var())<45.0:blurry.append(x.get('id'))
                    mean=float(gray.mean())
                    if mean<20 or mean>235:extreme.append(x.get('id'))
            except Exception:broken.append(x.get('id'))
        return {"scanned":len(rows),"duplicates":dups,"duplicate_count":len(dups),"broken":broken,"broken_count":len(broken),"blurry":blurry,"blurry_count":len(blurry),"low_resolution":lowres,"low_resolution_count":len(lowres),"extreme_brightness":extreme,"extreme_brightness_count":len(extreme),"note":"自动质检只标记风险样本，不自动删除，避免误删行业难样本。"}
