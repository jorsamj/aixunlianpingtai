import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path


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


def _master_unused_counts(project_dir, labels):
    images=read_json(Path(project_dir)/"images.json",[]); counts={str(x):0 for x in labels}
    for img in images:
        if str(img.get("split") or "unassigned")!="unassigned": continue
        ann=read_json(Path(project_dir)/"annotations"/f"{img.get('id')}.json",{"boxes":[]})
        found={str(b.get("label") or "") for b in ann.get("boxes",[]) if str(b.get("label") or "")}
        for l in counts:
            if l in found: counts[l]+=1
    return counts


def _box_to_yolo_worker(b,w,h):
    try:
        xc=((float(b["x1"])+float(b["x2"]))/2)/w; yc=((float(b["y1"])+float(b["y2"]))/2)/h
        bw=(float(b["x2"])-float(b["x1"]))/w; bh=(float(b["y2"])-float(b["y1"]))/h
        return f"{int(b.get('class_id',0))} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}"
    except:return ""


def _supplement_snapshot(project_dir, data_yaml, target_labels, limit, round_no):
    import yaml
    project_dir=Path(project_dir); base=Path(data_yaml).resolve().parent
    new=base.parent/(base.name+f"_ai{round_no}")
    if new.exists(): shutil.rmtree(new)
    shutil.copytree(base,new)
    dy=new/"data.yaml"; spec=yaml.safe_load(dy.read_text(encoding="utf-8")) or {}; spec["path"]=str(new).replace("\\","/"); dy.write_text(yaml.safe_dump(spec,allow_unicode=True,sort_keys=False),encoding="utf-8")
    images=read_json(project_dir/"images.json",[]); selected=[]
    for img in images:
        if len(selected)>=max(0,int(limit)):break
        if str(img.get("split") or "unassigned")!="unassigned":continue
        ann=read_json(project_dir/"annotations"/f"{img.get('id')}.json",{"boxes":[]}); boxes=ann.get("boxes",[])
        labs={str(b.get("label") or "") for b in boxes}
        if target_labels and not labs.intersection(set(target_labels)):continue
        src=project_dir/"uploads"/str(img.get("stored_name") or "")
        if not src.is_file():continue
        dst=new/"images"/"train"/src.name; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
        lines=[_box_to_yolo_worker(b,float(img.get("width") or 1),float(img.get("height") or 1)) for b in boxes]; lines=[x for x in lines if x]
        lab=new/"labels"/"train"/(src.stem+".txt"); lab.parent.mkdir(parents=True,exist_ok=True); lab.write_text("\n".join(lines),encoding="utf-8")
        img["split"]="train"; img["updated_at"]=now_iso(); selected.append(str(img.get("id")))
    if selected: write_json(project_dir/"images.json",images)
    return str(dy),selected


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
    metrics=dict(getattr(trainer,"metrics",{}) or {}); unused=_master_unused_counts(project_dir,weak_labels)
    image,sampled_files=_ai_eval_contact_sheet(args.data,args.ai_eval_samples,args.seed,epoch,Path(project_dir)/"jobs"/args.job_id/"ai_intervention")
    default_prompt=("你是算法训练决策助手。客观指标和人工Ground Truth是最终依据，你不能修改标准答案。\n"
                    "请根据当前训练指标、逐标签表现和未使用训练数据数量，在以下动作中选择一个：continue、supplement_and_retrain、extend_epochs。\n"
                    "若弱标签明显且存在未使用同标签数据，优先 supplement_and_retrain；若指标仍有提升空间但缺少合适补样，选择 extend_epochs；否则 continue。\n"
                    "只返回JSON：{\"action\":\"continue|supplement_and_retrain|extend_epochs\",\"reason\":\"通俗原因\",\"target_labels\":[\"标签\"],\"extra_epochs\":20}。")
    tmpl=str(cfg.get("training_intervention_prompt") or "").strip() or default_prompt
    summary={"epoch":epoch,"total_epochs":args.epochs,"eval_samples":len(sampled_files),"sampled_validation_files":sampled_files,"metrics":metrics,"per_class":per_class,"weak_labels":weak_labels,"unused_labeled_data":unused}
    prompt=tmpl+"\n当前客观数据："+json.dumps(summary,ensure_ascii=False,default=str)
    raw=_call_ai_model(cfg,image,prompt); dec=_json_from_ai_response(raw)
    action=str(dec.get("action") or "continue").strip().lower()
    if action not in {"continue","supplement_and_retrain","extend_epochs"}: action="continue"
    targets=[str(x) for x in (dec.get("target_labels") or weak_labels) if str(x)]
    extra=max(1,min(200,int(dec.get("extra_epochs") or args.ai_extra_epochs or 20)))
    if action=="supplement_and_retrain" and not any(unused.get(x,0)>0 for x in targets): action="extend_epochs"
    return {"epoch":epoch,"action":action,"reason":str(dec.get("reason") or "AI未提供原因"),"target_labels":targets,"extra_epochs":extra,"model_name":cfg.get("name") or cfg.get("model_name") or "AI模型","summary":summary,"raw":dec}


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--imgsz", type=int, required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--device", default="cpu")
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

    update_job(job_file, status="running", message="训练中", actual_train_params=train_args, actual_model=actual_model)
    print(f"[{now_iso()}] 开始训练", flush=True)
    print(f"模型: {actual_model}", flush=True)
    print(f"数据集: {args.data}", flush=True)
    print("实际训练参数:", flush=True)
    print(json.dumps(train_args, ensure_ascii=False, indent=2, default=str), flush=True)

    try:
        from ultralytics import YOLO
        model = YOLO(actual_model)
        gate_events=[]
        gate_reason=""
        ai_events=[]; ai_plan=None; ai_rounds=0
        ai_enabled=as_bool(args.ai_intervention)
        ai_epochs={int(x) for x in str(args.ai_intervention_epochs or "").split(",") if str(x).strip().isdigit()}
        ai_cfg=read_json(Path(args.ai_config),{}) if ai_enabled and args.ai_config else {}
        def on_fit_epoch_end(trainer):
            nonlocal gate_reason, ai_plan, ai_rounds
            epoch=int(getattr(trainer,"epoch",0))+1
            if ai_enabled and epoch in ai_epochs and ai_rounds < max(1,int(args.ai_max_rounds or 1)) and ai_cfg:
                try:
                    decision=_run_ai_intervention(ai_cfg,trainer,args,epoch,project_dir)
                    ai_events.append(decision); ai_rounds += 1
                    update_job(job_file, ai_intervention_events=ai_events, ai_intervention_last=decision)
                    print(f"[AI介入] Epoch {epoch}: {decision.get('action')} · {decision.get('reason')}",flush=True)
                    if str(args.ai_action_mode).lower()=="auto" and decision.get("action")=="supplement_and_retrain":
                        ai_plan=decision; trainer.stop=True; return
                    if decision.get("action")=="extend_epochs": ai_plan=decision
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
        train_result=model.train(**train_args)
        first_run_dir=runs_dir/args.run_name
        if ai_plan and str(args.ai_action_mode).lower()=="auto" and ai_plan.get("action") in {"supplement_and_retrain","extend_epochs"}:
            first_last=first_run_dir/"weights"/"last.pt"; first_best=first_run_dir/"weights"/"best.pt"
            resume_model=first_last if first_last.is_file() else first_best
            if resume_model.is_file():
                next_data=args.data; supplemented=[]
                if ai_plan.get("action")=="supplement_and_retrain":
                    next_data,supplemented=_supplement_snapshot(project_dir,args.data,ai_plan.get("target_labels") or [],max(1,int(args.supplement_count or 50)),ai_rounds)
                extra=max(1,int(ai_plan.get("extra_epochs") or args.ai_extra_epochs or 20))
                phase={"action":ai_plan.get("action"),"reason":ai_plan.get("reason"),"target_labels":ai_plan.get("target_labels") or [],"supplemented_image_ids":supplemented,"extra_epochs":extra,"data_yaml":next_data,"started_at":now_iso()}
                update_job(job_file,ai_continuation=phase,message="AI建议已执行，进入追加训练")
                print(f"[AI执行] {phase['action']} · 追加 {extra} 轮 · 补充数据 {len(supplemented)} 张",flush=True)
                cont_args=dict(train_args);cont_args.update({"data":next_data,"epochs":extra,"name":args.run_name+f"_ai{ai_rounds}","project":str(runs_dir),"exist_ok":True})
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

        training_report={"generated_at":now_iso(),"gate_events":gate_events,"quality_gate_reason":gate_reason,"metrics":{},"per_class":[],"weak_labels":[],"test_metrics":{},"ai_intervention_events":ai_events}
        try:
            best_model=YOLO(verified[0])
            val_metrics=best_model.val(data=args.data, split="val", verbose=False)
            training_report.update(build_report_from_metrics(val_metrics,getattr(best_model,"names",None)))
            try:
                test_metrics=best_model.val(data=args.data, split="test", verbose=False)
                training_report["test_metrics"]=(build_report_from_metrics(test_metrics,getattr(best_model,"names",None)).get("metrics") or {})
            except Exception as te:
                training_report["test_note"]="评测集为空或无法评测："+str(te)
        except Exception as ve:
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
            message="训练完成，模型产物校验通过",
            run_dir=str(run_dir),
            models=copied,
            verified_models=verified,
            artifact_verified=True,
            training_report=training_report,
            training_outcome=outcome,
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


if __name__ == "__main__":
    main()
