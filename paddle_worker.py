import argparse
import json
import os
import shlex
import shutil
import subprocess
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


def _configure_console_encoding():
    """Force UTF-8 logging on Windows so PaddleDetection unicode output never crashes the worker."""
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe_print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    text = " ".join(str(x) for x in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), **kwargs)


def build_pretrain_option(model_value: str) -> str:
    """Only pass pretrain_weights when the user selected a real Paddle weight/URL.
    Empty means: keep the pretrain_weights defined by the selected PaddleDetection yml, so it can auto-download.
    Never pass a .yml as pretrain_weights.
    """
    v = str(model_value or "").strip().strip('"')
    if not v or v.lower() in {"auto", "default", "none", "null"}:
        return ""
    low = v.lower()
    if low.endswith((".pdparams", ".pdmodel", ".pdiparams")) or low.startswith(("http://", "https://")):
        return f'pretrain_weights="{v}"'
    return ""


def paddle_class_options(family: str, num_classes: int) -> str:
    """Return PaddleDetection CLI overrides for custom category count.
    PaddleDetection models output class indexes 0..N-1; COCO categories are 1..N.
    If num_classes is not overridden, evaluation may crash with KeyError when predicted ids exceed custom categories.
    """
    n = max(1, int(num_classes or 1))
    f = (family or "").lower().replace("-", "_")
    opts = []
    if "picodet" in f:
        opts = [f"PicoHead.num_classes={n}", f"num_classes={n}"]
    elif "ppyoloe" in f:
        opts = [f"PPYOLOEHead.num_classes={n}", f"num_classes={n}"]
    elif "ppyolo" in f or "yolov3" in f:
        opts = [f"YOLOv3Head.num_classes={n}", f"num_classes={n}"]
    elif "rtdetr" in f or f == "detr":
        opts = [f"DETRHead.num_classes={n}", f"RTDETRTransformer.num_classes={n}", f"num_classes={n}"]
    elif "ssd" in f:
        opts = [f"SSDHead.num_classes={n}", f"num_classes={n}"]
    elif "fcos" in f:
        opts = [f"FCOSHead.num_classes={n}", f"num_classes={n}"]
    elif "retina" in f:
        opts = [f"RetinaHead.num_classes={n}", f"num_classes={n}"]
    elif "center" in f:
        opts = [f"CenterNetHead.num_classes={n}", f"num_classes={n}"]
    elif "faster" in f or "cascade" in f or "mask" in f:
        opts = [f"BBoxHead.num_classes={n}", f"MaskHead.num_classes={n}", f"num_classes={n}"]
    else:
        # 常见检测头兜底。PaddleDetection 通常允许 extra opts 合并，但为降低风险只给主流头。
        opts = [f"PicoHead.num_classes={n}", f"num_classes={n}"]
    return " ".join(opts)


def paddle_lr_options(lr0: float) -> str:
    try:
        lr = float(lr0 or 0.001)
    except Exception:
        lr = 0.001
    lr = max(1e-5, min(lr, 0.005))
    return f"LearningRate.base_lr={lr}"


def render_command(template: str, mapping: dict) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def ensure_eval_option(cmd: str, enable_eval: bool) -> str:
    """Enable/disable PaddleDetection --eval without requiring every stored algorithm template to be regenerated."""
    if not enable_eval:
        return cmd.replace(" {paddle_eval_option}", "").replace("{paddle_eval_option}", "")
    if "--eval" in cmd:
        return cmd.replace(" {paddle_eval_option}", "").replace("{paddle_eval_option}", "")
    # New templates have {paddle_eval_option}; old saved templates do not. Support both.
    if "{paddle_eval_option}" in cmd:
        return cmd.replace("{paddle_eval_option}", "--eval")
    for needle in ['tools\\train.py"', 'tools/train.py"', 'tools\\train.py', 'tools/train.py']:
        if needle in cmd:
            return cmd.replace(needle, needle + " --eval", 1)
    return cmd + " --eval"


def copy_outputs(run_dir: Path, models_dir: Path, run_name: str):
    models_dir.mkdir(exist_ok=True)
    copied = []
    for ext in ["*.pdparams", "*.pdmodel", "*.pdiparams", "*.yml", "*.yaml", "*.json", "*.onnx"]:
        for f in run_dir.rglob(ext):
            if f.is_file() and f.stat().st_size > 0:
                dst = models_dir / f"{run_name}_{f.name}"
                try:
                    shutil.copy2(f, dst)
                    copied.append(str(dst))
                except Exception:
                    pass
    # 防止复制太多配置/日志文件，限制数量
    return copied[:50]


def main():
    _configure_console_encoding()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--train-json", required=True)
    parser.add_argument("--val-json", required=True)
    parser.add_argument("--label-list", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--command-template", required=True)
    parser.add_argument("--num-classes", type=int, default=1)
    parser.add_argument("--family", default="")
    parser.add_argument("--lr0", type=float, default=0.001)
    parser.add_argument("--enable-eval", action="store_true", help="Enable PaddleDetection COCO evaluation during training")
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    job_file = project_dir / "jobs" / args.job_id / "job.json"
    runs_dir = project_dir / "runs" / args.run_name
    models_dir = project_dir / "models"
    runs_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "project_dir": project_dir,
        "dataset_dir": Path(args.dataset_dir),
        "train_json": Path(args.train_json),
        "val_json": Path(args.val_json),
        "label_list": Path(args.label_list),
        "model": args.model,
        "pretrain_option": build_pretrain_option(args.model),
        "paddle_class_options": paddle_class_options(args.family, args.num_classes),
        "paddle_lr_options": paddle_lr_options(args.lr0),
        "paddle_eval_option": "--eval" if args.enable_eval else "",
        "num_classes": args.num_classes,
        "epochs": args.epochs,
        "batch": args.batch,
        "device": args.device,
        "run_dir": runs_dir,
        "python": os.environ.get("PADDLE_PYTHON", sys.executable),
        "paddledet_dir": os.environ.get("PADDLEDETECTION_DIR", r"D:\PaddleDetection"),
        "paddlex_dir": os.environ.get("PADDLEX_DIR", r"D:\PaddleX"),
    }
    cmd = render_command(args.command_template, mapping)
    cmd = ensure_eval_option(cmd, bool(args.enable_eval))
    update_job(job_file, status="running", message="飞桨训练中", run_dir=str(runs_dir), rendered_command=cmd, num_classes=args.num_classes, paddle_class_options=mapping.get("paddle_class_options"), paddle_lr0=args.lr0, paddle_eval=bool(args.enable_eval))
    safe_print(f"[{now_iso()}] 开始飞桨/Paddle训练")
    safe_print("数据集:", args.dataset_dir)
    safe_print("训练标注:", args.train_json)
    safe_print("验证标注:", args.val_json)
    safe_print("标签列表:", args.label_list)
    safe_print("类别数:", args.num_classes)
    safe_print("类别覆盖:", mapping.get("paddle_class_options"))
    safe_print("学习率覆盖:", mapping.get("paddle_lr_options"))
    safe_print("基础模型:", args.model or "使用配置默认预训练权重/自动下载")
    safe_print("命令:", cmd)
    safe_print("训练中COCO评估:", "开启" if args.enable_eval else "关闭")
    safe_print("说明：v26 可在训练任务中动态开启/关闭 --eval。小数据集建议关闭，先保证模型完整训练；需要 AP/mAP 指标时再开启。")
    safe_print("PaddleDetection目录：", mapping.get("paddledet_dir"))

    try:
        child_env = os.environ.copy()
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        child_env.setdefault("PYTHONUTF8", "1")
        if os.name == "nt":
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(runs_dir), shell=True, text=True, encoding="utf-8", errors="replace", env=child_env)
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(runs_dir), shell=True, text=True, encoding="utf-8", errors="replace", env=child_env)
        for line in proc.stdout or []:
            try:
                print(line, end="", flush=True)
            except UnicodeEncodeError:
                safe_print(line.rstrip("\r\n"))
        code = proc.wait()
        copied = copy_outputs(runs_dir, models_dir, args.run_name)
        if code != 0:
            msg = f"飞桨训练命令退出码：{code}"
            # 常见原因：仍使用了带 --eval 的旧模板，或 COCO 类别映射不一致。
            update_job(job_file, status="failed", message=msg, models=copied, finished_at=now_iso())
            sys.exit(code)
        update_job(job_file, status="done", message="飞桨训练完成", models=copied, finished_at=now_iso())
        safe_print(f"[{now_iso()}] 飞桨训练完成")
        if copied:
            safe_print("已收集模型/配置文件：")
            for x in copied:
                safe_print(x)
        else:
            safe_print("未自动收集到 .pdparams/.pdmodel/.pdiparams/.onnx；请检查训练命令输出目录是否设置为 {run_dir}。")
    except Exception as e:
        safe_print("飞桨训练失败：", e)
        traceback.print_exc()
        update_job(job_file, status="failed", message=f"飞桨训练失败：{e}", finished_at=now_iso())
        sys.exit(1)


if __name__ == "__main__":
    main()
