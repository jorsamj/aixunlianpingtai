import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

from platform_core.training_config import (
    effective_training_config,
    normalize_training_config,
    ultralytics_training_args,
)


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_job(job_file: Path, **kwargs):
    job = read_json(job_file, {})
    job.update(kwargs)
    job["updated_at"] = now_iso()
    write_json(job_file, job)


def as_bool(v):
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def parse_cache(v):
    text = str(v).strip()
    low = text.lower()
    if low in {"false", "0", "no", "off", "none", ""}:
        return False
    if low in {"true", "1", "yes", "on"}:
        return True
    if low in {"ram", "disk"}:
        return low
    raise ValueError("cache 只支持 False / True / ram / disk")


def effective_host_preflight(config):
    """Last host gate before model.train, based on resolved resource values."""
    report = {"workers": int(config["workers"]), "batch": int(config["batch"]), "cache": config["cache"]}
    try:
        import psutil
        available = int(psutil.virtual_memory().available)
        report["available_ram_bytes"] = available
        if available < 1024 * 1024 * 1024:
            raise RuntimeError("HOST_RAM_INSUFFICIENT: less than 1 GiB remains after resource resolution")
    except ImportError:
        report["available_ram_bytes"] = None
    shm = Path("/dev/shm")
    if shm.is_dir():
        free = int(shutil.disk_usage(shm).free)
        report["shm_free_bytes"] = free
        if config["workers"] > 0 and free < 256 * 1024 * 1024:
            raise RuntimeError("SHM_INSUFFICIENT: effective workers require at least 256 MiB /dev/shm")
    else:
        report["shm_free_bytes"] = None
    return report


def resolve_training_model(model_arg: str, pretrained: bool) -> str:
    """When 'pretrained' is off, do not silently keep training from an already-loaded .pt checkpoint."""
    if pretrained:
        return model_arg
    p = Path(model_arg)
    name = p.name if p.name else model_arg
    if name.lower().endswith('.yaml') or name.lower().endswith('.yml'):
        return model_arg
    if name.lower().endswith('.pt'):
        stem = Path(name).stem
        # Official Ultralytics model names can be reconstructed from packaged YAML definitions.
        if re_official_yolo_name(stem):
            return stem + '.yaml'
        raise ValueError(
            "已关闭预训练权重，但当前选择的是自定义 .pt 权重。自定义 .pt 已经包含权重，无法自动变成随机初始化模型；"
            "请重新勾选‘加载所选权重’，或选择官方 YOLO 基础模型后再关闭。"
        )
    return model_arg


def re_official_yolo_name(stem: str) -> bool:
    import re
    # yolo11n / yolo11s / yolo11m / yolo11l / yolo11x and newer official naming families.
    return bool(re.fullmatch(r"yolo(?:v?\d+|\d+)[nslmx](?:-[a-z]+)?", stem.lower()))



def metric_value(metrics, key):
    if not isinstance(metrics, dict):
        return None
    key = (key or "map50").lower()
    aliases = {
        "precision": ["metrics/precision(b)", "precision", "box_precision"],
        "recall": ["metrics/recall(b)", "recall", "box_recall"],
        "map50": ["metrics/map50(b)", "map50", "metrics/mAP50(B)"],
        "map50-95": ["metrics/map50-95(b)", "map", "metrics/mAP50-95(B)"],
    }
    for wanted in aliases.get(key, aliases["map50"]):
        for k, v in metrics.items():
            if str(k).lower() == str(wanted).lower():
                try: return float(v)
                except Exception: pass
    return None


def build_report_from_metrics(metrics_obj, names=None):
    report={"metrics":{},"per_class":[],"weak_labels":[]}
    try:
        d=getattr(metrics_obj,"results_dict",{}) or {}
        for k,v in d.items():
            try: report["metrics"][str(k)]=round(float(v),6)
            except Exception: pass
        box=getattr(metrics_obj,"box",None)
        pvals=list(getattr(box,"p",[]) or []) if box is not None else []
        rvals=list(getattr(box,"r",[]) or []) if box is not None else []
        ap50=list(getattr(box,"ap50",[]) or []) if box is not None else []
        maps=list(getattr(box,"maps",[]) or []) if box is not None else []
        names=names or getattr(metrics_obj,"names",{}) or {}
        n=max(len(pvals),len(rvals),len(ap50),len(maps))
        for i in range(n):
            name=names.get(i,str(i)) if isinstance(names,dict) else (names[i] if i<len(names) else str(i))
            row={"label":str(name),"precision":float(pvals[i]) if i<len(pvals) else None,"recall":float(rvals[i]) if i<len(rvals) else None,"map50":float(ap50[i]) if i<len(ap50) else None,"map50_95":float(maps[i]) if i<len(maps) else None}
            report["per_class"].append(row)
        ranked=sorted(report["per_class"], key=lambda x: (x.get("recall") if x.get("recall") is not None else 2, x.get("map50") if x.get("map50") is not None else 2))
        report["weak_labels"]=[x["label"] for x in ranked[:3] if (x.get("recall") is not None and x["recall"]<0.75) or (x.get("map50") is not None and x["map50"]<0.75)]
    except Exception as e:
        report["report_error"]=str(e)
    return report


def final_evaluate_main():
    """Evaluate a frozen best model in a process that only sees the sealed test bundle."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-evaluate", action="store_true")
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    result = {"status": "failed", "started_at": now_iso(), "metrics": {}}
    try:
        from ultralytics import YOLO
        model = YOLO(args.model)
        metrics = model.val(data=args.data, split=args.split, device=args.device, verbose=False)
        report = build_report_from_metrics(metrics, getattr(model, "names", None))
        result.update(
            status="succeeded",
            finished_at=now_iso(),
            metrics=report.get("metrics") or {},
            per_class=report.get("per_class") or [],
            weak_labels=report.get("weak_labels") or [],
        )
        write_json(output, result)
        return
    except Exception as error:
        result.update(finished_at=now_iso(), error=str(error))
        write_json(output, result)
        raise


def _iou_xyxy(a, b):
    x1=max(a[0],b[0]); y1=max(a[1],b[1]); x2=min(a[2],b[2]); y2=min(a[3],b[3])
    inter=max(0.0,x2-x1)*max(0.0,y2-y1)
    aa=max(0.0,a[2]-a[0])*max(0.0,a[3]-a[1]); bb=max(0.0,b[2]-b[0])*max(0.0,b[3]-b[1])
    return inter/max(1e-9,aa+bb-inter)

def analyze_detection_errors(model, data_yaml, device='cpu', max_images=200, iou_threshold=0.5, conf=0.25):
    """Compare predictions against YOLO ground truth on validation images.
    Returns sample-level FP/FN details; no VLM/LLM judgement is used.
    """
    root=Path(data_yaml).resolve().parent
    img_dir=root/'images'/'val'; lab_dir=root/'labels'/'val'
    if not img_dir.exists(): return []
    names=getattr(model,'names',{}) or {}
    files=[x for x in sorted(img_dir.iterdir()) if x.suffix.lower() in {'.jpg','.jpeg','.png','.bmp','.webp'}][:max(0,int(max_images or 200))]
    errors=[]
    for image_path in files:
        try:
            from PIL import Image
            with Image.open(image_path) as im: w,h=im.size
            gt=[]
            label_path=lab_dir/(image_path.stem+'.txt')
            if label_path.exists():
                for line in label_path.read_text(encoding='utf-8').splitlines():
                    parts=line.strip().split()
                    if len(parts)<5: continue
                    cid=int(float(parts[0])); cx,cy,bw,bh=map(float,parts[1:5])
                    gt.append({'class_id':cid,'box':[(cx-bw/2)*w,(cy-bh/2)*h,(cx+bw/2)*w,(cy+bh/2)*h]})
            rr=model.predict(source=str(image_path),conf=conf,iou=iou_threshold,device=device,verbose=False)
            r=rr[0] if rr else None; pred=[]
            if r is not None and getattr(r,'boxes',None) is not None:
                xyxy=r.boxes.xyxy.detach().cpu().tolist(); cls=r.boxes.cls.detach().cpu().tolist(); cf=r.boxes.conf.detach().cpu().tolist()
                pred=[{'class_id':int(c),'box':list(map(float,b)),'confidence':float(q)} for b,c,q in zip(xyxy,cls,cf)]
            matched_gt=set(); matched_pred=set()
            pairs=[]
            for pi,pd in enumerate(pred):
                for gi,g in enumerate(gt):
                    if pd['class_id']!=g['class_id']: continue
                    iv=_iou_xyxy(pd['box'],g['box'])
                    if iv>=iou_threshold: pairs.append((iv,pi,gi))
            for _,pi,gi in sorted(pairs,reverse=True):
                if pi in matched_pred or gi in matched_gt: continue
                matched_pred.add(pi);matched_gt.add(gi)
            fn=[g for gi,g in enumerate(gt) if gi not in matched_gt];fp=[pd for pi,pd in enumerate(pred) if pi not in matched_pred]
            if fn or fp:
                def nm(cid):
                    if isinstance(names,dict): return str(names.get(cid,cid))
                    return str(names[cid] if cid<len(names) else cid)
                errors.append({'image':image_path.name,'false_negative_count':len(fn),'false_positive_count':len(fp),'false_negative_labels':sorted({nm(x['class_id']) for x in fn}),'false_positive_labels':sorted({nm(x['class_id']) for x in fp})})
        except Exception as e:
            errors.append({'image':image_path.name,'analysis_error':str(e)})
    return errors


def _json_from_ai_response(data):
    if isinstance(data, dict):
        if isinstance(data.get("result"), dict): return data["result"]
        if isinstance(data.get("data"), dict): return data["data"]
        if "action" in data: return data
        for key in ["text", "content", "response", "raw", "message"]:
            if isinstance(data.get(key), str):
                data = data[key]; break
        else:
            return data
    if not isinstance(data, str): return {}
    import re
    m=re.search(r'\{.*\}', data.strip(), flags=re.S)
    if not m: return {}
    try:return json.loads(m.group(0))
    except:return {}


def _call_ai_model(cfg, image_path, prompt):
    import base64, requests
    url=str(cfg.get("detect_url") or cfg.get("base_url") or "").strip()
    if not url: raise RuntimeError("AI模型接口为空")
    headers=dict(cfg.get("headers_json") or {})
    if cfg.get("api_key"): headers.setdefault("Authorization", f"Bearer {cfg.get('api_key')}")
    mode=cfg.get("request_mode") or "json_base64"; image_field=cfg.get("image_field") or "image"; prompt_field=cfg.get("prompt_field") or "prompt"
    if mode=="multipart_file":
        data={prompt_field:prompt}
        if cfg.get("model_name"): data["model"]=cfg.get("model_name")
        with Path(image_path).open("rb") as fp:
            r=requests.post(url,headers=headers,files={image_field:(Path(image_path).name,fp,"application/octet-stream")},data=data,timeout=180)
    else:
        body={image_field:base64.b64encode(Path(image_path).read_bytes()).decode("utf-8"),prompt_field:prompt}
        if cfg.get("model_name"): body["model"]=cfg.get("model_name")
        r=requests.post(url,headers=headers,json=body,timeout=180)
    r.raise_for_status()
    try:return r.json()
    except:return {"raw":r.text}


def _trainer_per_class(trainer):
    out=[]
    try:
        metrics=getattr(getattr(trainer,"validator",None),"metrics",None)
        box=getattr(metrics,"box",None); names=getattr(trainer,"names",{}) or getattr(getattr(trainer,"model",None),"names",{}) or {}
        p=list(getattr(box,"p",[]) or []); r=list(getattr(box,"r",[]) or []); ap50=list(getattr(box,"ap50",[]) or [])
        n=max(len(p),len(r),len(ap50))
        for i in range(n):
            nm=names.get(i,str(i)) if isinstance(names,dict) else (names[i] if i<len(names) else str(i))
            out.append({"label":str(nm),"precision":float(p[i]) if i<len(p) else None,"recall":float(r[i]) if i<len(r) else None,"map50":float(ap50[i]) if i<len(ap50) else None})
    except Exception: pass
    return out


AI_INTERVENTION_ACTIONS = {"continue", "extend_epochs", "recommend_supplement"}


def _normalize_ai_intervention_action(value):
    """Map legacy mutable actions to a next-task recommendation.

    A running training task owns an immutable snapshot. AI may extend epochs on
    that same snapshot or recommend what to add to a future task, but it may
    never pull project-global images into the current task.
    """
    action = str(value or "continue").strip().lower()
    if action == "supplement_and_retrain":
        return "recommend_supplement"
    return action if action in AI_INTERVENTION_ACTIONS else "continue"


def _ai_eval_contact_sheet(data_yaml, count, seed, epoch, work_dir):
    """Deterministically sample validation images and make one VLM-friendly contact sheet.
    Ground-truth metrics are still computed by Ultralytics; this sheet only gives the AI visual context.
    """
    from PIL import Image, ImageOps, ImageDraw
    import random
    val_dir=Path(data_yaml).resolve().parent/"images"/"val"
    files=[x for x in sorted(val_dir.glob("*")) if x.is_file()]
    if not files:
        raise RuntimeError("试验集没有可供AI介入分析的图片")
    n=max(1,min(int(count or 1),len(files),24))
    rng=random.Random(int(seed or 0)+int(epoch)*1009)
    chosen=rng.sample(files,n) if len(files)>n else files[:]
    cols=min(4,max(1,n)); rows=(n+cols-1)//cols; tw,th=240,180
    sheet=Image.new("RGB",(cols*tw,rows*(th+22)),"white")
    draw=ImageDraw.Draw(sheet)
    for i,path in enumerate(chosen):
        with Image.open(path) as im:
            im=im.convert("RGB")
            thumb=ImageOps.contain(im,(tw,th))
            x=(i%cols)*tw+(tw-thumb.width)//2; y=(i//cols)*(th+22)+(th-thumb.height)//2
            sheet.paste(thumb,(x,y))
        draw.text(((i%cols)*tw+5,(i//cols)*(th+22)+th+3),f"{i+1}. {path.name[:28]}",fill=(30,40,55))
    out=Path(work_dir)/f"ai_eval_epoch_{epoch}.jpg"; out.parent.mkdir(parents=True,exist_ok=True); sheet.save(out,quality=88)
    return out,[x.name for x in chosen]


def _run_ai_intervention(cfg, trainer, args, epoch, project_dir):
    per_class=_trainer_per_class(trainer)
    weak=sorted(per_class,key=lambda x:(x.get("recall") if x.get("recall") is not None else 2,x.get("map50") if x.get("map50") is not None else 2))[:3]
    weak_labels=[x["label"] for x in weak if (x.get("recall") is not None and x["recall"]<.8) or (x.get("map50") is not None and x["map50"]<.8)]
    metrics=dict(getattr(trainer,"metrics",{}) or {})
    image,sampled_files=_ai_eval_contact_sheet(args.data,args.ai_eval_samples,args.seed,epoch,Path(project_dir)/"jobs"/args.job_id/"ai_intervention")
    default_prompt=("你是算法训练决策助手。客观指标和人工 Ground Truth 是最终依据，你不能修改标准答案。\n"
                    "当前训练任务的数据快照、Train/Validation/Test 划分和标签映射已经冻结。"
                    "你只能选择 continue、extend_epochs、recommend_supplement 三种动作。\n"
                    "continue：按原计划继续；extend_epochs：仅在当前冻结数据上追加训练轮次；"
                    "recommend_supplement：指出下一次新训练任务建议补充的标签或素材方向，本次任务不会补料、不会改 split、不会改 Ground Truth。\n"
                    "只返回 JSON：{\"action\":\"continue|extend_epochs|recommend_supplement\","
                    "\"reason\":\"通俗原因\",\"target_labels\":[\"标签\"],\"extra_epochs\":20}。")
    tmpl=str(cfg.get("training_intervention_prompt") or "").strip() or default_prompt
    execution_policy=("\n平台强制执行约束：当前训练 snapshot 不可变。禁止在本任务中新增/删除图片、改变 Train/Validation/Test、"
                      "修改标注或类别映射。若你认为应增加数据，只能返回 recommend_supplement；"
                      "历史动作 supplement_and_retrain 会被平台强制转换为 recommend_supplement。")
    summary={
        "epoch":epoch,
        "total_epochs":args.epochs,
        "eval_samples":len(sampled_files),
        "sampled_validation_files":sampled_files,
        "metrics":metrics,
        "per_class":per_class,
        "weak_labels":weak_labels,
        "snapshot_policy":{
            "immutable":True,
            "allowed_current_task_actions":["continue","extend_epochs"],
            "supplement_requires_new_training_task":True,
        },
    }
    prompt=tmpl+execution_policy+"\n当前客观数据："+json.dumps(summary,ensure_ascii=False,default=str)
    raw=_call_ai_model(cfg,image,prompt); dec=_json_from_ai_response(raw)
    action=_normalize_ai_intervention_action(dec.get("action"))
    targets=[str(x) for x in (dec.get("target_labels") or weak_labels) if str(x)]
    extra=max(1,min(200,int(dec.get("extra_epochs") or args.ai_extra_epochs or 20)))
    return {
        "epoch":epoch,
        "action":action,
        "reason":str(dec.get("reason") or "AI未提供原因"),
        "target_labels":targets,
        "extra_epochs":extra,
        "model_name":cfg.get("name") or cfg.get("model_name") or "AI模型",
        "summary":summary,
        "raw":dec,
        "snapshot_immutable":True,
        "requires_new_training_task":action=="recommend_supplement",
    }


def stage_gate_random_eval(trainer, args, epoch):
    """Evaluate the current checkpoint on a fresh deterministic random sample of the trial/val split.
    val_max_samples=0 means all trial data. Sampling changes by epoch but is reproducible for the same seed+epoch.
    Falls back to the normal trainer validation metrics if the extra evaluation cannot run.
    """
    import random, yaml
    root=Path(args.data).resolve().parent
    val_dir=root/'images'/'val'
    files=[x for x in sorted(val_dir.iterdir()) if x.is_file() and x.suffix.lower() in {'.jpg','.jpeg','.png','.bmp','.webp'}] if val_dir.exists() else []
    if not files:
        return dict(getattr(trainer,'metrics',{}) or {}), [], 'normal_validation', '试验集为空，使用训练器当前验证指标'
    limit=max(0,int(args.val_max_samples or 0))
    if limit<=0 or limit>=len(files):
        return dict(getattr(trainer,'metrics',{}) or {}), [x.name for x in files], 'all', ''
    rng=random.Random(int(args.seed or 0)+int(epoch)*104729)
    chosen=rng.sample(files,min(limit,len(files)))
    try:
        # Save the current epoch checkpoint, then run a standalone validation only on this sample.
        try: trainer.save_model()
        except Exception: pass
        last=Path(str(getattr(trainer,'last','') or ''))
        if not last.is_file(): last=Path(str(getattr(trainer,'save_dir','')))/'weights'/'last.pt'
        if not last.is_file():
            return dict(getattr(trainer,'metrics',{}) or {}), [x.name for x in chosen], 'random_fallback', '当前轮次检查点尚未写出，使用训练器当前验证指标'
        work=Path(args.project_dir)/'jobs'/args.job_id/'stage_gate'
        work.mkdir(parents=True,exist_ok=True)
        txt=work/f'epoch_{epoch}_val.txt'
        txt.write_text('\n'.join(str(x.resolve()).replace('\\','/') for x in chosen),encoding='utf-8')
        base=yaml.safe_load(Path(args.data).read_text(encoding='utf-8')) or {}
        base['path']=str(root).replace('\\','/')
        base['val']=str(txt.resolve()).replace('\\','/')
        temp=work/f'epoch_{epoch}_data.yaml';temp.write_text(yaml.safe_dump(base,allow_unicode=True,sort_keys=False),encoding='utf-8')
        from ultralytics import YOLO
        gate_model=YOLO(str(last))
        mm=gate_model.val(data=str(temp),split='val',imgsz=int(args.imgsz),device=args.device,verbose=False)
        metrics=dict(getattr(mm,'results_dict',{}) or {})
        try:
            del gate_model
            import torch
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        except Exception: pass
        return metrics,[x.name for x in chosen],'random',''
    except Exception as e:
        return dict(getattr(trainer,'metrics',{}) or {}),[x.name for x in chosen],'random_fallback',str(e)


def main():
    if "--final-evaluate" in sys.argv:
        final_evaluate_main()
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--requested-model", required=True)
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--imgsz", type=int, required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--assigned-device", required=True)
    parser.add_argument("--requested-device", default="auto")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--patience", type=int, default=100)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--optimizer", default="auto")
    parser.add_argument("--lr0", type=float, default=0.01)
    parser.add_argument("--lrf", type=float, default=0.01)
    parser.add_argument("--weight-decay", type=float, default=0.0005)
    parser.add_argument("--close-mosaic", type=int, default=10)
    parser.add_argument("--mosaic", type=float, default=1.0)
    parser.add_argument("--cache", default="False")
    parser.add_argument("--resource-strategy", choices=("auto", "manual"), default="auto")
    parser.add_argument("--resource-context", default="")
    parser.add_argument("--resource-resolution", default="")
    parser.add_argument("--metrics-db", default="")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--bundle-manifest", required=True)
    parser.add_argument("--preflight-report", required=True)
    parser.add_argument("--single-cls", default="false")
    parser.add_argument("--pretrained", default="true")
    parser.add_argument("--rect", default="false")
    parser.add_argument("--amp", default="true")
    parser.add_argument("--cos-lr", default="false")
    parser.add_argument("--freeze", type=int, default=0)
    parser.add_argument("--momentum", type=float, default=0.937)
    parser.add_argument("--warmup-epochs", type=float, default=3.0)
    parser.add_argument("--save-period", type=int, default=-1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--deterministic", default="true")
    parser.add_argument("--multi-scale", type=float, default=0.0)
    parser.add_argument("--hsv-h", type=float, default=0.015)
    parser.add_argument("--hsv-s", type=float, default=0.7)
    parser.add_argument("--hsv-v", type=float, default=0.4)
    parser.add_argument("--degrees", type=float, default=0.0)
    parser.add_argument("--translate", type=float, default=0.1)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--shear", type=float, default=0.0)
    parser.add_argument("--perspective", type=float, default=0.0)
    parser.add_argument("--flipud", type=float, default=0.0)
    parser.add_argument("--fliplr", type=float, default=0.5)
    parser.add_argument("--mixup", type=float, default=0.0)
    parser.add_argument("--val-max-samples", type=int, default=0)
    parser.add_argument("--eval-interval", type=int, default=0)
    parser.add_argument("--eval-metric", default="map50")
    parser.add_argument("--continue-threshold", type=float, default=0.0)
    parser.add_argument("--stop-threshold", type=float, default=0.0)
    # Deprecated compatibility flags. 42.25 never mutates a running task's snapshot.
    parser.add_argument("--auto-supplement", default="false")
    parser.add_argument("--supplement-count", type=int, default=0)
    parser.add_argument("--ai-intervention", default="false")
    parser.add_argument("--ai-intervention-epochs", default="")
    parser.add_argument("--ai-config", default="")
    parser.add_argument("--ai-eval-samples", type=int, default=20)
    parser.add_argument("--ai-action-mode", default="auto")
    parser.add_argument("--ai-extra-epochs", type=int, default=20)
    parser.add_argument("--ai-max-rounds", type=int, default=1)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    job_file = project_dir / "jobs" / args.job_id / "job.json"
    runs_dir = project_dir / "runs"
    models_dir = project_dir / "models"
    models_dir.mkdir(exist_ok=True)

    pretrained = as_bool(args.pretrained)
    cache_value = parse_cache(args.cache)
    actual_model = resolve_training_model(args.model, pretrained)
    train_args = {
        "data": args.data,
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
        "project": str(runs_dir),
        "name": args.run_name,
        "exist_ok": True,
        "patience": args.patience,
        "workers": args.workers,
        "optimizer": args.optimizer,
        "lr0": args.lr0,
        "lrf": args.lrf,
        "weight_decay": args.weight_decay,
        "close_mosaic": args.close_mosaic,
        "mosaic": args.mosaic,
        "cache": cache_value,
        "single_cls": as_bool(args.single_cls),
        "pretrained": pretrained,
        "rect": as_bool(args.rect),
        "amp": as_bool(args.amp),
        "cos_lr": as_bool(args.cos_lr),
        "momentum": args.momentum, "warmup_epochs": args.warmup_epochs, "save_period": args.save_period,
        "seed": args.seed, "deterministic": as_bool(args.deterministic), "multi_scale": args.multi_scale,
        "hsv_h": args.hsv_h, "hsv_s": args.hsv_s, "hsv_v": args.hsv_v,
        "degrees": args.degrees, "translate": args.translate, "scale": args.scale, "shear": args.shear,
        "perspective": args.perspective, "flipud": args.flipud, "fliplr": args.fliplr, "mixup": args.mixup,
    }
    if args.freeze > 0:
        train_args["freeze"] = args.freeze

    requested_config = normalize_training_config({
        **{key: value for key, value in train_args.items() if key not in {"data", "project", "name", "exist_ok"}},
        "model": args.requested_model,
        "device": args.requested_device,
        "freeze": args.freeze,
    })
    update_job(job_file, status="running", message="验证训练设备与资源",
               requested_config=requested_config, requested_train_params=requested_config,
               actual_model=actual_model)
    print(f"[{now_iso()}] 开始训练", flush=True)
    print(f"模型: {actual_model}", flush=True)
    print(f"数据集: {args.data}", flush=True)
    print("实际训练参数:", flush=True)
    print(json.dumps(train_args, ensure_ascii=False, indent=2, default=str), flush=True)

    telemetry = None
    try:
        from platform_core.training_devices import normalize_training_device
        assigned = normalize_training_device(args.assigned_device)
        requested = normalize_training_device(args.requested_device)
        if assigned == "auto" or normalize_training_device(args.device) != assigned:
            raise RuntimeError("GPU_ASSIGNMENT_REQUIRED: concrete matching assigned device required")
        if requested != "auto" and requested != assigned:
            raise RuntimeError("TRAINING_DEVICE_ASSIGNMENT_MISMATCH")
        resource_context = read_json(Path(args.resource_context), {}) if args.resource_context else {}
        gpu_index = int(assigned[5:]) if assigned.startswith("cuda:") else None
        # Bind the physical GPU before importing Torch. Ultralytics uses logical
        # cuda:0 inside a single-GPU visibility mask, including for assigned cuda:N.
        if gpu_index is not None:
            visible = os.environ.get("CUDA_VISIBLE_DEVICES")
            entries = visible.split(",") if visible is not None else []
            physical = resource_context.get("gpu_uuid") or (entries[gpu_index] if entries else str(gpu_index))
            os.environ["CUDA_VISIBLE_DEVICES"] = str(physical)
            args.device = "0"
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
            args.device = "cpu"
        import ultralytics
        import torch
        from ultralytics import YOLO
        from platform_core.training_metrics import TrainingMetrics, persist_resolution, resolve_resources
        runtime_device = "cuda:0" if gpu_index is not None else "cpu"
        allocation = torch.empty(1, device=runtime_device)
        props = torch.cuda.get_device_properties(0) if gpu_index is not None else None
        raw_uuid = getattr(props, "uuid", None) if props is not None else None
        gpu_uuid = str(raw_uuid) if raw_uuid is not None else None
        expected_uuid = resource_context.get("gpu_uuid")
        if expected_uuid and gpu_uuid and str(expected_uuid).lower().removeprefix("gpu-") != gpu_uuid.lower().removeprefix("gpu-"):
            raise RuntimeError("GPU_IDENTITY_MISMATCH: training process differs from reserved GPU")
        if gpu_index is not None:
            torch.cuda.synchronize(0)
        evidence = dict(requested_device=requested, assigned_device=assigned, actual_device=assigned,
                        runtime_device=str(allocation.device), gpu_index=gpu_index, gpu_uuid=gpu_uuid,
                        gpu_name=str(props.name) if props is not None else None, pid=os.getpid(),
                        python_executable=sys.executable, torch_version=str(torch.__version__),
                        cuda_version=getattr(torch.version, "cuda", None),
                        cuda_available=bool(torch.cuda.is_available()), validated_at=now_iso())
        del allocation
        update_job(job_file, requested_device=requested, assigned_device=assigned, actual_device=assigned,
                   device_evidence=evidence, ultralytics_version=getattr(ultralytics, "__version__", "unknown"))
        model = YOLO(actual_model)
        resolved = resolve_resources({**requested_config, "data": args.data, "device": runtime_device,
                                      "resource_strategy": args.resource_strategy}, resource_context, model, torch)
        resolution_path = Path(args.resource_resolution) if args.resource_resolution else job_file.parent / "resolved-resources.json"
        effective_config, adjustment_reasons = effective_training_config(
            requested_config, assigned_device=assigned, actual_model=actual_model, resolved_resources=resolved,
        )
        try:
            effective_preflight = effective_host_preflight(effective_config)
        except Exception as error:
            failed_report = {
                "schema_version": 1,
                "status": "BLOCKED",
                "ok": False,
                "stage": "effective_resources",
                "requested_config": requested_config,
                "effective_config": effective_config,
                "adjustment_reasons": adjustment_reasons,
                "blockers": [{"code": "EFFECTIVE_RESOURCE_BLOCKED", "message": str(error)}],
                "warnings": [],
            }
            write_json(Path(args.preflight_report), failed_report)
            update_job(
                job_file,
                effective_config=effective_config,
                adjustment_reasons=adjustment_reasons,
                effective_resource_preflight={"ok": False, "error": str(error)},
                preflight={"ok": False, "blockers": [{"code": "EFFECTIVE_RESOURCE_BLOCKED", "message": str(error)}],
                           "warnings": [], "counts": {}},
            )
            raise
        from platform_core.material_repository import MaterialRepository
        from platform_core.training_preflight import authoritative_preflight, require_preflight
        from platform_core.training_tasks import _selected_project_images
        snapshot = read_json(Path(args.snapshot), {})
        selected_ids = [
            str(image_id)
            for role in ("train", "validation", "test")
            for image_id in (snapshot.get("ids") or {}).get(role, [])
        ]
        current_images = _selected_project_images(MaterialRepository(project_dir), project_dir, selected_ids)
        effective_report = authoritative_preflight(
            snapshot,
            current_images,
            {**effective_config, "requested_device": requested, "assigned_device": assigned},
            device_evidence=evidence,
            resource_context=resource_context,
            workspace=Path(args.bundle_manifest).parent,
            bundle_manifest_path=Path(args.bundle_manifest),
        )
        effective_report.update(requested_config=requested_config, effective_config=effective_config,
                                adjustment_reasons=adjustment_reasons, resource_resolution=resolved)
        write_json(Path(args.preflight_report), effective_report)
        update_job(
            job_file,
            effective_config=effective_config,
            adjustment_reasons=adjustment_reasons,
            effective_resource_preflight={"ok": True, **effective_preflight},
            preflight={"ok": bool(effective_report.get("ok")),
                       "blockers": effective_report.get("blockers") or [],
                       "warnings": effective_report.get("warnings") or [],
                       "counts": effective_report.get("counts") or {}},
        )
        require_preflight(effective_report)
        train_args = {
            **ultralytics_training_args(effective_config),
            "data": args.data,
            "project": str(runs_dir),
            "name": args.run_name,
            "exist_ok": True,
        }
        persist_resolution(resolution_path, resolved)
        evidence["effective_args"] = dict(train_args)
        update_job(job_file, resolved_resources=resolved, effective_config=effective_config,
                   adjustment_reasons=adjustment_reasons, actual_config=None,
                   effective_resource_preflight={"ok": True, **effective_preflight},
                   actual_train_params=train_args, device_evidence=evidence)
        telemetry = TrainingMetrics(args.metrics_db or job_file.parent / "training-metrics.sqlite3", resolved,
                                    gpu_uuid=resource_context.get("gpu_uuid"))
        telemetry.start()
        gate_events=[]
        gate_reason=""
        ai_events=[]; ai_plan=None; ai_rounds=0
        ai_enabled=as_bool(args.ai_intervention)
        ai_epochs={int(x) for x in str(args.ai_intervention_epochs or "").split(",") if str(x).strip().isdigit()}
        ai_cfg=read_json(Path(args.ai_config),{}) if ai_enabled and args.ai_config else {}
        def on_fit_epoch_end(trainer):
            nonlocal gate_reason, ai_plan, ai_rounds
            epoch=int(getattr(trainer,"epoch",0))+1
            update_job(
                job_file,
                current_epoch=epoch,
                total_epochs=int(args.epochs),
                progress_percent=round(min(90.0, epoch / max(1, int(args.epochs)) * 90.0), 2),
                message=f"训练中 · Epoch {epoch}/{int(args.epochs)}",
            )
            if ai_enabled and epoch in ai_epochs and ai_rounds < max(1,int(args.ai_max_rounds or 1)) and ai_cfg:
                try:
                    decision=_run_ai_intervention(ai_cfg,trainer,args,epoch,project_dir)
                    ai_events.append(decision); ai_rounds += 1
                    update_job(job_file, ai_intervention_events=ai_events, ai_intervention_last=decision)
                    print(f"[AI介入] Epoch {epoch}: {decision.get('action')} · {decision.get('reason')}",flush=True)
                    if decision.get("action")=="recommend_supplement":
                        update_job(job_file, ai_next_task_recommendation=decision)
                    elif str(args.ai_action_mode).lower()=="auto" and decision.get("action")=="extend_epochs":
                        ai_plan=decision
                except Exception as ex:
                    ev={"epoch":epoch,"action":"error","reason":str(ex),"model_name":ai_cfg.get("name") or "AI模型"}; ai_events.append(ev); update_job(job_file,ai_intervention_events=ai_events,ai_intervention_last=ev)
                    print(f"[AI介入失败] Epoch {epoch}: {ex}",flush=True)
            interval=max(0,int(args.eval_interval or 0))
            if interval<=0 or (epoch % interval)!=0:
                return
            metrics,sampled_files,sample_mode,sample_note=stage_gate_random_eval(trainer,args,epoch)
            value=metric_value(metrics,args.eval_metric)
            ev={"epoch":epoch,"metric":args.eval_metric,"value":value,"time":now_iso(),"sample_count":len(sampled_files),"sample_mode":sample_mode,"sampled_files":sampled_files[:200]}
            if sample_note: ev["sample_note"]=sample_note
            if value is not None:
                if args.stop_threshold>0 and value>=args.stop_threshold:
                    ev["decision"]="target_reached";gate_reason=f"{args.eval_metric} 达到提前完成阈值 {args.stop_threshold:.3f}";trainer.stop=True
                elif args.continue_threshold>0 and value<args.continue_threshold:
                    ev["decision"]="below_gate";gate_reason=f"{args.eval_metric} 低于继续训练阈值 {args.continue_threshold:.3f}";trainer.stop=True
                else:
                    ev["decision"]="continue"
            gate_events.append(ev)
            update_job(job_file, gate_events=gate_events, quality_gate_reason=gate_reason)
            print(f"[质量门禁] epoch={epoch} 抽取={len(sampled_files)}张 {args.eval_metric}={value} decision={ev.get('decision','unknown')}",flush=True)
        try:
            model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
        except Exception as cb_err:
            print(f"[WARN] 阶段质量门禁回调未启用: {cb_err}",flush=True)
        def attach_resource_callbacks(target):
            def verify_runtime(trainer):
                telemetry.on_train_start(trainer)
                if str(trainer.device) != runtime_device:
                    raise RuntimeError(f"TRAINING_DEVICE_RUNTIME_MISMATCH: expected={runtime_device}; actual={trainer.device}")
                actual_config = dict(effective_config)
                for key in actual_config:
                    if key not in {"model", "device"} and hasattr(trainer.args, key):
                        value = getattr(trainer.args, key)
                        if isinstance(value, (str, int, float, bool)) or value is None:
                            actual_config[key] = value
                actual_config.update(model=actual_model, device=assigned)
                evidence.update(runtime_device=str(trainer.device), effective_args=dict(train_args))
                update_job(job_file, actual_device=assigned, device_evidence=evidence,
                           actual_config=actual_config, actual_train_params=train_args)
            target.add_callback("on_train_start", verify_runtime)
            target.add_callback("on_train_epoch_start", telemetry.on_epoch_start)
            target.add_callback("on_fit_epoch_end", telemetry.on_epoch_end)
        attach_resource_callbacks(model)
        retries = 0
        while True:
            try:
                evidence["effective_args"] = dict(train_args)
                update_job(job_file, device_evidence=evidence, actual_train_params=train_args)
                train_result = model.train(**train_args)
                break
            except Exception as train_error:
                is_oom = isinstance(train_error, torch.cuda.OutOfMemoryError) or "cuda out of memory" in str(train_error).lower()
                is_oom = is_oom or "runtime changed batch; explicit worker retry required" in str(train_error)
                if not is_oom:
                    raise
                telemetry.oom = True
                if args.resource_strategy != "auto" or train_args["batch"] <= 1 or retries >= 6:
                    raise
                retries += 1
                train_args["batch"] = max(1, train_args["batch"] // 2)
                train_args["workers"] = min(train_args["workers"], train_args["batch"])
                effective_config.update(batch=train_args["batch"], workers=train_args["workers"])
                resolved.update(resolved_batch=train_args["batch"], resolved_workers=train_args["workers"], oom_retries=retries)
                resolved["reasons"].append(f"CUDA OOM retry {retries}/6: batch stepped down to {train_args['batch']}; same assigned GPU")
                adjustment_reasons.append(resolved["reasons"][-1])
                with telemetry.lock:
                    telemetry.resolved = dict(resolved)
                persist_resolution(resolution_path, resolved)
                update_job(job_file, resolved_resources=resolved, effective_config=effective_config,
                           adjustment_reasons=adjustment_reasons, actual_config=None,
                           actual_train_params=train_args)
                print(f"[资源调整] CUDA OOM；第 {retries}/6 次重试，batch={train_args['batch']}", flush=True)
            # Release traceback-held tensors before building the next bounded attempt.
            del model
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            model = YOLO(actual_model)
            model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
            attach_resource_callbacks(model)
        first_run_dir=runs_dir/args.run_name
        if ai_plan and str(args.ai_action_mode).lower()=="auto" and ai_plan.get("action")=="extend_epochs":
            first_last=first_run_dir/"weights"/"last.pt"; first_best=first_run_dir/"weights"/"best.pt"
            resume_model=first_last if first_last.is_file() else first_best
            if resume_model.is_file():
                extra=max(1,int(ai_plan.get("extra_epochs") or args.ai_extra_epochs or 20))
                phase={
                    "action":"extend_epochs",
                    "reason":ai_plan.get("reason"),
                    "target_labels":ai_plan.get("target_labels") or [],
                    "extra_epochs":extra,
                    "data_yaml":args.data,
                    "snapshot_immutable":True,
                    "started_at":now_iso(),
                }
                update_job(job_file,ai_continuation=phase,message="AI建议已执行：在冻结数据上追加训练")
                print(f"[AI执行] extend_epochs · 追加 {extra} 轮 · 训练快照保持不变",flush=True)
                cont_args=dict(train_args);cont_args.update({"data":args.data,"epochs":extra,"name":args.run_name+f"_ai{ai_rounds}","project":str(runs_dir),"exist_ok":True})
                model=YOLO(str(resume_model)); train_result=model.train(**cont_args); phase["finished_at"]=now_iso(); update_job(job_file,ai_continuation=phase)
        run_dir = Path(getattr(model.trainer,"save_dir",runs_dir/args.run_name))
        best = run_dir / "weights" / "best.pt"
        last = run_dir / "weights" / "last.pt"
        copied = []
        verified = []
        for src, suffix in [(best, "best"), (last, "last")]:
            if not src.exists():
                continue
            dst = models_dir / f"{args.run_name}_{suffix}.pt"
            shutil.copy2(src, dst)
            copied.append(str(dst))
            # A file existing is not enough: load it back with Ultralytics to catch truncated/corrupt weights.
            try:
                YOLO(str(dst))
                verified.append(str(dst))
                print(f"模型产物校验通过: {dst}", flush=True)
            except Exception as verify_error:
                print(f"[WARN] 模型产物无法重新加载: {dst}: {verify_error}", flush=True)

        if not copied:
            raise RuntimeError("训练进程结束，但没有找到 best.pt 或 last.pt；请查看上方 Ultralytics 日志。")
        if not verified:
            raise RuntimeError("训练产生了权重文件，但权重无法重新加载，产物不可交付。")
        best_path = next((path for path in verified if Path(path).stem.endswith("_best")), "")
        last_path = next((path for path in verified if Path(path).stem.endswith("_last")), "")

        training_report={"generated_at":now_iso(),"gate_events":gate_events,"quality_gate_reason":gate_reason,"validation_status":"pending","metrics":{},"per_class":[],"weak_labels":[],"test_metrics":{},"test_result":{"status":"sealed_pending_final_evaluation","metrics":{}},"ai_intervention_events":ai_events}
        # Persist the verified weights before validation/report generation.  A
        # supervising Worker that restarts during validation can then preserve
        # and resume from best.pt instead of launching training again.
        update_job(job_file,status="train_completed",stage="train_completed",
                   message="训练完成，模型产物校验通过，准备验证",
                   run_dir=str(run_dir),models=copied,verified_models=verified,
                   best_path=best_path,last_path=last_path,artifact_verified=True,
                   training_report=training_report)
        try:
            update_job(job_file, stage="validating", message="训练完成，正在验证 best.pt")
            best_model=YOLO(verified[0])
            val_metrics=best_model.val(data=args.data, split="val", verbose=False)
            training_report.update(build_report_from_metrics(val_metrics,getattr(best_model,"names",None)))
            training_report["validation_status"]="succeeded"
        except Exception as ve:
            training_report["validation_status"]="failed"
            training_report["validation_error"]=str(ve)
        try:
            analysis_limit=int(args.val_max_samples) if int(args.val_max_samples or 0)>0 else 200
            training_report["error_samples"]=analyze_detection_errors(best_model,args.data,args.device,max_images=min(500,analysis_limit))
            training_report["error_sample_count"]=len([x for x in training_report["error_samples"] if not x.get("analysis_error")])
        except Exception as ae:
            training_report["error_analysis_error"]=str(ae)
        outcome="target_reached" if gate_reason and "达到提前完成阈值" in gate_reason else "needs_optimization" if gate_reason and "低于继续训练阈值" in gate_reason else "completed"
        update_job(
            job_file,
            status="done",
            stage="train_completed",
            message="训练完成，模型产物校验通过",
            run_dir=str(run_dir),
            models=copied,
            verified_models=verified,
            best_path=best_path,
            last_path=last_path,
            artifact_verified=True,
            training_report=training_report,
            training_outcome=outcome,
            progress_percent=100,
            finished_at=now_iso(),
        )
        print(f"[{now_iso()}] 训练完成", flush=True)
        for m in copied:
            print(f"模型已保存: {m}", flush=True)
    except Exception as e:
        print("训练失败：", e, flush=True)
        traceback.print_exc()
        update_job(job_file, status="failed", message=f"训练失败：{e}", artifact_verified=False, finished_at=now_iso())
        sys.exit(1)
    finally:
        if telemetry is not None:
            telemetry.close()


if __name__ == "__main__":
    main()
