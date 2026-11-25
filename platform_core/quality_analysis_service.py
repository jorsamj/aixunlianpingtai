"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from fastapi import HTTPException
from .quality_analysis_contracts import V44QualityReq, V45ErrorCauseReq

import hashlib
from pathlib import Path
from platform_core.quality import compute_quality
from platform_core.ai_configuration_contracts import V35ModelConfigReq

@dataclass(frozen=True)
class QualityAnalysisDependencies:
    MODEL_CONFIGS_FILE: Callable[..., Any]
    _training_success_rate_stats: Callable[..., Any]
    _v35_call_model: Callable[..., Any]
    _v35_is_vision_provider: Callable[..., Any]
    _v35_items: Callable[..., Any]
    _v44_labels_in_ann: Callable[..., Any]
    _write_job_json: Callable[..., Any]
    get_project: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    list_jobs: Callable[..., Any]
    load_images: Callable[..., Any]
    material_store: Callable[..., Any]
    normalize_box_for_project: Callable[..., Any]
    normalize_label: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_annotation: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    read_json: Callable[..., Any]
    resolve_material_path: Callable[..., Any]
    sync_jobs_index: Callable[..., Any]
    v35_test_model_config: Callable[..., Any]
    v35_test_saved_model_annotation: Callable[..., Any]


class QualityAnalysisService:
    def __init__(self, dependencies: QualityAnalysisDependencies):
        self.dependencies = dependencies

    def v44_quality_center(self, project_id: str):
        dq=self._v44_dataset_quality(project_id)
        algs=self.dependencies.list_algorithms_internal(project_id);alg_rows=[]
        for a in algs:
            vers=a.get("versions") or [];v=vers[0] if vers else {};rep=v.get("report") or {}
            def metric(name):
                for k,val in rep.items():
                    if name in str(k).lower().replace(' ',''):
                        try: return float(val)
                        except Exception: pass
                return None
            p=metric('precision');r=metric('recall');m=metric('map50')
            vals=[x*100 if x is not None and x<=1 else x for x in [p,r,m] if x is not None]
            score=round(sum(vals)/len(vals),1) if vals else None
            alg_rows.append({"id":a.get("id"),"name":a.get("name"),"version":v.get("version_name") or "", "precision":p,"recall":r,"map50":m,"score":score})
        jobs=self.dependencies.list_jobs(project_id)
        training_stats=self.dependencies._training_success_rate_stats(jobs)
        terminal_training_count=training_stats["ended_count"]
        train_success_rate=training_stats["success_rate"]
        trained_count=sum(1 for x in alg_rows if x['score'] is not None)
        def avg_metric(k):
            vals=[]
            for x in alg_rows:
                v=x.get(k)
                if v is not None: vals.append(v*100 if v<=1 else v)
            return round(sum(vals)/max(1,len(vals)),1)
        version_coverage=round(sum(1 for a in algs if a.get('versions'))/max(1,len(algs))*100,1)
        alg_quality={"algorithms":alg_rows,"trained_count":trained_count,"avg_score":round(sum(x['score'] for x in alg_rows if x['score'] is not None)/max(1,trained_count),1),"avg_precision":avg_metric('precision'),"avg_recall":avg_metric('recall'),"avg_map50":avg_metric('map50'),"train_success_rate":train_success_rate,"train_success_count":training_stats["success_count"],"train_failure_count":training_stats["failure_count"],"train_completed_count":terminal_training_count,"version_coverage":version_coverage}
        return {"ok":True,"dataset":dq,"algorithm":alg_quality,"time":self.dependencies.now_iso()}

    def v44_data_quality(self, project_id: str, payload: V44QualityReq):
        return {"ok":True,"quality":self._v44_dataset_quality(project_id,payload)}

    def v44_test_saved_model_config(self, config_id: str):
        cfg=next((x for x in self.dependencies._v35_items(self.dependencies.MODEL_CONFIGS_FILE()) if x.get('id')==config_id),None)
        if not cfg: raise HTTPException(status_code=404,detail='模型配置不存在')
        return self.dependencies.v35_test_saved_model_annotation(config_id) if self.dependencies._v35_is_vision_provider(cfg) else self.dependencies.v35_test_model_config(V35ModelConfigReq(**cfg))

    def v45_error_cause_analysis(self, project_id: str, job_id: str, payload: V45ErrorCauseReq):
        """VLM只做错误原因辅助归因。检测是否正确仍由预测框与人工Ground Truth通过IoU/类别客观计算。"""
        self.dependencies.get_project(project_id)
        jf=self.dependencies.project_dir(project_id)/'jobs'/job_id/'job.json'; job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail='训练任务不存在')
        cfg=next((x for x in self.dependencies._v35_items(self.dependencies.MODEL_CONFIGS_FILE()) if x.get('id')==payload.model_config_id),None)
        if not cfg: raise HTTPException(status_code=404,detail='模型配置不存在')
        report=job.get('training_report') or {}; errors=[x for x in (report.get('error_samples') or []) if not x.get('analysis_error')][:max(1,min(30,int(payload.limit or 12)))]
        if not errors: raise HTTPException(status_code=400,detail='当前报告没有可分析的错误样本')
        snapshot=Path(job.get('dataset_snapshot') or job.get('dataset_dir') or '')
        if not snapshot.is_dir():
            # v42.4 job没有单独字段时，从data.yaml父目录回推
            sy=Path(job.get('data_yaml') or '')
            if sy.is_file(): snapshot=sy.parent
        results=[]
        for e in errors:
            name=str(e.get('image') or '')
            ip=None
            for part in ('val','train','test'):
                candidate=snapshot/'images'/part/name
                if candidate.is_file(): ip=candidate;break
            if not ip:
                results.append({'image':name,'error':'找不到训练快照图片'});continue
            prompt=(f"你是视觉算法错误归因助手。程序已根据人工Ground Truth和IoU客观确认该图片存在检测错误。"
                f"漏检标签：{','.join(e.get('false_negative_labels') or []) or '无'}；误检标签：{','.join(e.get('false_positive_labels') or []) or '无'}。"
                "请不要重新判断对错，只分析可能导致模型错误的视觉原因，例如小目标、遮挡、夜间、逆光、模糊、相似干扰物、目标边界不清等。"
                "只返回JSON：{\"cause\":\"主要原因\",\"scene\":[\"场景标签\"],\"data_suggestion\":\"建议补充什么训练数据\"}。")
            try:
                raw=self.dependencies._v35_call_model(cfg,ip,{},prompt,0.0)
                results.append({'image':name,'result':raw})
            except Exception as ex:
                results.append({'image':name,'error':str(ex)})
        report['ai_error_analysis']={'model_config_id':payload.model_config_id,'model_name':cfg.get('name'),'generated_at':self.dependencies.now_iso(),'items':results}
        job['training_report']=report;self.dependencies._write_job_json(jf,job); self.dependencies.sync_jobs_index(project_id)
        return {'ok':True,'analysis':report['ai_error_analysis']}

    def v44_supplement_training_data(self, project_id: str, job_id: str):
        jf=self.dependencies.project_dir(project_id)/'jobs'/job_id/'job.json';job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail='训练任务不存在')
        weak=set((job.get('training_report') or {}).get('weak_labels') or [])
        if not weak: raise HTTPException(status_code=400,detail='当前报告没有识别出弱标签')
        limit=int((job.get('quality_gate') or {}).get('supplement_count') or 50);images=self.dependencies.load_images(project_id);eligible=[]
        for img in images:
            if (img.get('split') or 'unassigned')!='unassigned': continue
            labs=self.dependencies._v44_labels_in_ann(self.dependencies.read_annotation(project_id,img['id']))
            if labs.intersection(weak): eligible.append(str(img['id']))
        eligible_set=set(eligible); updated=self.dependencies.now_iso()
        def apply_supplement(rows):
            changed=[]
            for img in rows:
                if len(changed)>=limit: break
                if str(img.get('id')) not in eligible_set: continue
                if (img.get('split') or 'unassigned')!='unassigned': continue
                img['split']='train';img['updated_at']=updated;changed.append(str(img.get('id')))
            return changed
        changed=self.dependencies.material_store(project_id).mutate(apply_supplement)
        job['supplemented_image_ids']=changed;job['supplemented_at']=self.dependencies.now_iso();self.dependencies._write_job_json(jf,job);self.dependencies.sync_jobs_index(project_id)
        return {"ok":True,"changed":len(changed),"weak_labels":sorted(weak)}

    def _v44_image_quality(self, project_id: str, images: List[Dict[str, Any]]) -> Dict[str, Any]:
        hashes={};low_res=0;total_bytes=0;res_buckets={"small":0,"medium":0,"large":0}
        for img in images[:1500]:
            try:
                path=self.dependencies.resolve_material_path(project_id,img)
                total_bytes+=path.stat().st_size
                if min(int(img.get("width") or 0),int(img.get("height") or 0))<320: low_res+=1
                area=int(img.get("width") or 0)*int(img.get("height") or 0)
                res_buckets["small" if area<640*480 else "medium" if area<1920*1080 else "large"]+=1
                h=hashlib.sha1(path.read_bytes()).hexdigest();hashes[h]=hashes.get(h,0)+1
            except Exception: pass
        dup=sum(max(0,n-1) for n in hashes.values())
        return {"duplicate_images":dup,"low_resolution":low_res,"total_size_bytes":total_bytes,"resolution_buckets":res_buckets}

    def _v44_dataset_quality(self, project_id: str, req: Optional[V44QualityReq]=None) -> Dict[str, Any]:
        project=self.dependencies.get_project(project_id);req=req or V44QualityReq()
        split=(req.split or "").lower();wanted={self.dependencies.normalize_label(x) for x in (req.labels or []) if self.dependencies.normalize_label(x)};wanted_ids={str(x) for x in (req.image_ids or []) if str(x)}
        if req.snapshot_id:
            snapshot_file=self.dependencies.project_dir(project_id)/"snapshots"/f"{req.snapshot_id}.json"
            if not snapshot_file.is_file():raise HTTPException(status_code=404,detail="训练 Snapshot 不存在")
            snapshot=self.dependencies.read_json(snapshot_file,{})
            wanted_ids={str(x) for x in (snapshot.get("train_image_ids") or [])+(snapshot.get("val_image_ids") or []) if str(x)}
        if wanted_ids:
            images=[]
            materials=self.dependencies.material_store(project_id)
            ordered_ids=sorted(wanted_ids)
            for offset in range(0,len(ordered_ids),500):
                images.extend(materials.get_many(ordered_ids[offset:offset+500]))
        else:
            images=self.dependencies.load_images(project_id)
        annotation_ids=[str(img.get("id") or "") for img in images if str(img.get("id") or "")]
        annotations: Dict[str, Dict[str, Any]]={}
        for offset in range(0,len(annotation_ids),500):
            annotations.update(self.dependencies.read_annotations_many(project_id,annotation_ids[offset:offset+500]))
        candidates=[]
        for img in sorted(images,key=lambda row:str(row.get("id") or "")):
            sp=(img.get("split") or "unassigned").lower();sp=sp if sp in {"unassigned","train","val","test"} else "unassigned"
            ann=annotations.get(str(img.get("id") or "")) or {};clean=[];invalid=0
            for box in ann.get("boxes",[]):
                normalized=self.dependencies.normalize_box_for_project(project_id,img,box,create_label=False,project_state=project)
                if normalized:clean.append(normalized)
                else:invalid+=1
            labels={box["label"] for box in clean}
            if split and sp!=split:continue
            if wanted and not labels.intersection(wanted):continue
            candidates.append({**img,"split":sp,"boxes":clean,"valid_box_count":len(clean),"invalid_box_count":invalid})
        if req.max_samples and req.max_samples>0:candidates=candidates[:int(req.max_samples)]
        total_bytes=0;resolution_buckets={"small":0,"medium":0,"large":0};label_images={label:0 for label in project.get("labels",[])}
        for row in candidates:
            try:
                path=self.dependencies.resolve_material_path(project_id,row)
                row["content_hash"]=hashlib.sha1(path.read_bytes()).hexdigest();total_bytes+=path.stat().st_size
            except Exception:pass
            area=int(row.get("width") or 0)*int(row.get("height") or 0);resolution_buckets["small" if area<640*480 else "medium" if area<1920*1080 else "large"]+=1
            for label in {box["label"] for box in row.get("boxes") or []}:label_images[label]=label_images.get(label,0)+1
        quality=compute_quality(candidates,min_width=640,min_height=480)
        quality["dimensions"]=dict(quality["scores"])
        names={"annotation_completeness":"标注完整度","box_validity":"标注有效性","label_balance":"标签均衡度","duplicate_control":"重复控制","resolution_quality":"分辨率质量","split_coverage":"划分完整度"}
        quality["scores"]={names[key]:value for key,value in quality["scores"].items()}
        quality["label_images"]=label_images;quality["total_size_bytes"]=total_bytes;quality["resolution_buckets"]=resolution_buckets
        quality["split_counts"]={key:int(quality.get("split_counts",{}).get(key,0)) for key in ("unassigned","train","val","test")}
        return quality
