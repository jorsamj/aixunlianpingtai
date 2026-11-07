import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.hardware
def test_configured_vendor_sdk_produces_real_loadable_artifact(tmp_path):
    target = os.environ.get("XJALGO_VENDOR_TARGET", "").strip().lower()
    source = Path(os.environ.get("XJALGO_VENDOR_TEST_ONNX", ""))
    if target not in {"ascend", "rockchip", "tensorrt", "sophon"} or not source.is_file():
        pytest.skip("未显式配置 XJALGO_VENDOR_TARGET 和 XJALGO_VENDOR_TEST_ONNX，不能宣称厂商转换通过")

    params = {"precision": os.environ.get("XJALGO_VENDOR_PRECISION", "fp16")}
    resource = {"id": "hardware-test", "name": "hardware-test", "version": ""}
    expected_suffix = {"ascend": ".om", "rockchip": ".rknn", "tensorrt": ".engine", "sophon": ".bmodel"}[target]
    if target == "ascend":
        params["soc_version"] = os.environ.get("XJALGO_ATLAS_SOC", "")
        resource["atc_path"] = os.environ.get("XJALGO_ATC_PATH", "")
    elif target == "rockchip":
        params["chip"] = os.environ.get("XJALGO_RKNN_CHIP", "")
        resource["python_path"] = os.environ.get("XJALGO_RKNN_PYTHON", "")
    elif target == "sophon":
        if os.environ.get("XJALGO_SOPHON_HARDWARE_TEST") != "1":
            pytest.skip("Sophon真实编译必须单独显式授权XJALGO_SOPHON_HARDWARE_TEST=1；NOT VERIFIED")
        params.update(chip=os.environ.get("XJALGO_SOPHON_CHIP", ""),
                      input_height=int(os.environ.get("XJALGO_SOPHON_HEIGHT", "640")),
                      input_width=int(os.environ.get("XJALGO_SOPHON_WIDTH", "640")), batch=1)
        resource.update(python_path=os.environ.get("XJALGO_SOPHON_PYTHON", ""),
                        tool_root=os.environ.get("XJALGO_SOPHON_TOOL_ROOT", ""))
    else:
        params["target_environment"] = os.environ.get("XJALGO_TENSORRT_ENVIRONMENT", "")
        resource["trtexec_path"] = os.environ.get("XJALGO_TRTEXEC_PATH", "")

    job_dir = tmp_path / "vendor-job"
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    local_source = source_dir / source.name
    local_source.write_bytes(source.read_bytes())
    job = {
        "id": "hardware-test",
        "source_id": "hardware-test-source",
        "source_path": str(local_source),
        "target": target,
        "resource": resource,
        "params": params,
        "status": "queued",
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=7200,
    )
    result = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, result.get("error") or completed.stdout or completed.stderr
    artifacts = list((job_dir / "artifacts").rglob(f"*{expected_suffix}"))
    assert artifacts and all(path.stat().st_size > 0 for path in artifacts)
    manifest = json.loads((job_dir / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "converted_unverified"
    assert manifest["outputs"]


@pytest.mark.hardware
def test_sophon_real_board_matches_pt_and_onnx_detections_on_same_images(tmp_path):
    """Opt-in real SAIL/TPU test; never replace this with a fake engine.

    Agreement precision/recall is not dataset mAP. GT-based mAP and INT8
    degradation remain separately NOT VERIFIED until a frozen GT set is supplied.
    """
    if os.environ.get("XJALGO_SOPHON_HARDWARE_TEST") != "1":
        pytest.skip("未授权配置真实Sophon硬件，BM1684X/BM1688加载与检测质量NOT VERIFIED")
    import hashlib
    import time
    import numpy as np
    from PIL import Image
    import onnxruntime as ort
    import sophon.sail as sail
    import torch
    from ultralytics import YOLO
    from platform_core.auto_label import nms_candidates, _iou

    bmodel=Path(os.environ["XJALGO_SOPHON_BMODEL"])
    manifest=json.loads(Path(os.environ["XJALGO_SOPHON_MANIFEST"]).read_text(encoding="utf-8"))
    pt=Path(os.environ["XJALGO_SOPHON_PT"])
    onnx=Path(os.environ["XJALGO_VENDOR_TEST_ONNX"])
    chip=os.environ["XJALGO_SOPHON_CHIP"].lower()
    assert chip in {"bm1684x","bm1688"} and manifest["target"]["chip"]==chip
    assert pt.is_file() and onnx.is_file() and bmodel.is_file()
    record=next(row for row in manifest["outputs"] if row["name"]==bmodel.name)
    assert hashlib.sha256(bmodel.read_bytes()).hexdigest()==record["sha256"]
    labels=manifest["source"]["label_codes"]
    assert labels and len(set(labels))==len(labels)
    preprocessing=manifest["parameters"]["preprocessing"]
    assert preprocessing["owner"]=="caller" and preprocessing["nms"]=="external"
    assert sail.get_tpu_count()>0
    engine=sail.Engine(str(bmodel),int(os.environ.get("XJALGO_SOPHON_DEVICE_ID","0")),sail.IOMode.SYSIO)
    graph=engine.get_graph_names()[0]
    inputs=engine.get_input_names(graph)
    assert len(inputs)==1
    shape=engine.get_input_shape(graph,inputs[0])
    assert shape[0:2]==[1,3]
    height,width=shape[2:]
    session=ort.InferenceSession(str(onnx),providers=["CPUExecutionProvider"])
    assert list(session.get_inputs()[0].shape)==shape
    mother=YOLO(str(pt)).model.eval()
    images=sorted(p for p in Path(os.environ["XJALGO_SOPHON_IMAGE_DIR"]).iterdir() if p.suffix.lower() in {".jpg",".jpeg",".png",".bmp"})[:20]
    assert len(images)>=3, "至少配置3张有代表性的实际图片"

    def decode(raw):
        values=np.asarray(raw)
        assert values.ndim==3 and values.shape[0]==1
        rows=values[0].T
        assert rows.shape[1]==4+len(labels), "必须为未内嵌NMS的YOLO11检测输出"
        boxes=[]
        for row in rows:
            cid=int(np.argmax(row[4:]));confidence=float(row[4+cid])
            if confidence<0.25:continue
            x,y,w,h=map(float,row[:4])
            boxes.append(dict(label=labels[cid],class_id=cid,confidence=confidence,
                              x1=x-w/2,y1=y-h/2,x2=x+w/2,y2=y+h/2))
        return nms_candidates(boxes,iou_threshold=0.7)

    counts={"reference":0,"candidate":0,"matched":0,"pt_reference":0,"pt_matched":0}
    cases=[]
    for path in images:
        image=Image.open(path).convert("RGB")
        if preprocessing["letterbox"]:
            ratio=min(width/image.width,height/image.height)
            resized=image.resize((round(image.width*ratio),round(image.height*ratio)),Image.Resampling.BILINEAR)
            canvas=Image.new("RGB",(width,height),(114,114,114))
            canvas.paste(resized,((width-resized.width)//2,(height-resized.height)//2))
        else:canvas=image.resize((width,height),Image.Resampling.BILINEAR)
        values=np.asarray(canvas,dtype=np.float32)
        if preprocessing["pixel_format"]=="bgr":values=values[:,:,::-1]
        values=(values-np.asarray(preprocessing["mean"],dtype=np.float32))*np.asarray(preprocessing["scale"],dtype=np.float32)
        tensor=np.ascontiguousarray(values.transpose(2,0,1)[None])
        reference=decode(session.run(None,{session.get_inputs()[0].name:tensor})[0])
        with torch.inference_mode():
            mother_raw=mother(torch.from_numpy(tensor))
        mother_raw=mother_raw[0] if isinstance(mother_raw,tuple) else mother_raw
        original=decode(mother_raw.detach().cpu().numpy())
        started=time.perf_counter()
        actual=engine.process(graph,{inputs[0]:tensor})
        elapsed=time.perf_counter()-started
        candidate=decode(next(iter(actual.values())))
        def matches(expected,observed):
            used=set();hits=0
            for box in expected:
                best=max(((_iou(box,row),i,row) for i,row in enumerate(observed) if i not in used and row["class_id"]==box["class_id"]),default=(0,-1,{}))
                if best[0]>=0.9 and abs(box["confidence"]-best[2]["confidence"])<=0.03:
                    used.add(best[1]);hits+=1
            return hits
        hit=matches(reference,candidate);pt_hit=matches(reference,original)
        counts["reference"]+=len(reference);counts["candidate"]+=len(candidate);counts["matched"]+=hit
        counts["pt_reference"]+=len(original);counts["pt_matched"]+=pt_hit
        cases.append(dict(image=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          seconds=elapsed,onnx=reference,pt=original,bmodel=candidate))
    assert counts["reference"]>0 and counts["candidate"]>0 and counts["pt_reference"]>0
    recall=counts["matched"]/counts["reference"]
    precision=counts["matched"]/counts["candidate"]
    assert recall>=0.98 and precision>=0.98
    assert counts["pt_matched"]/counts["reference"]>=0.98
    assert counts["pt_matched"]/counts["pt_reference"]>=0.98
    (tmp_path/"sophon-real-hardware-evidence.json").write_text(json.dumps(dict(chip=chip,
        hardware_verified=True,counts=counts,agreement_recall=recall,agreement_precision=precision,
        dataset_map="NOT VERIFIED without frozen ground-truth benchmark",cases=cases),ensure_ascii=False,indent=2),encoding="utf-8")
