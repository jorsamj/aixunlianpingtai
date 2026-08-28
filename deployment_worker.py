import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    except Exception:
        return default


def write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def append_log(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', errors='ignore') as f:
        f.write(f'[{now()}] {text}\n')
        f.flush()


def update(job_file: Path, **kwargs):
    job = read_json(job_file, {})
    job.update(kwargs)
    job['updated_at'] = now()
    write_json(job_file, job)
    return job


def which(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.exists() and p.is_file():
            return str(p)
        found = shutil.which(c)
        if found:
            return found
    return None


def run_cmd(cmd: List[str], cwd: Path, log_file: Path, env: Optional[Dict[str, str]] = None, timeout: Optional[int] = None):
    pretty = subprocess.list2cmdline([str(x) for x in cmd]) if os.name == 'nt' else ' '.join([shlex_quote(str(x)) for x in cmd])
    append_log(log_file, '执行命令：' + pretty)
    cp = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        env=env or os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='ignore',
        timeout=timeout,
    )
    if cp.stdout:
        for line in cp.stdout.splitlines():
            append_log(log_file, line)
    if cp.returncode != 0:
        tail = (cp.stdout or '')[-5000:]
        raise RuntimeError(f'命令执行失败，退出码 {cp.returncode}\n{tail}')
    return cp.stdout or ''


def shlex_quote(s: str) -> str:
    if not s:
        return "''"
    if all(ch.isalnum() or ch in '._/-:[],' for ch in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def safe_name(s: str) -> str:
    out = ''.join(c if c.isalnum() or c in '._-' else '_' for c in s)
    return out.strip('._') or 'model'


def find_ultra_python(resource: Dict[str, Any]) -> str:
    for key in ['ultralytics_python', 'python_path']:
        p = str(resource.get(key) or '')
        if p and Path(p).exists():
            return p
    return sys.executable


def export_pt_to_onnx(source: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    if source.suffix.lower() == '.onnx':
        dst = out_dir / source.name
        if source.resolve() != dst.resolve():
            shutil.copy2(source, dst)
        append_log(log_file, f'源模型已经是 ONNX：{dst.name}')
        return dst
    if source.suffix.lower() not in {'.pt', '.pth'}:
        raise RuntimeError(f'当前源模型 {source.suffix} 不能直接导出 ONNX。请先生成 ONNX 或 Paddle Inference 模型。')
    py = find_ultra_python(resource)
    imgsz = int(params.get('input_size') or 640)
    opset = int(params.get('opset') or 12)
    dynamic = bool(params.get('dynamic', False))
    simplify = bool(params.get('simplify', False))
    batch = max(1, int(params.get('batch') or 1))
    script = (
        "from ultralytics import YOLO; "
        f"m=YOLO(r'''{source}'''); "
        f"print(m.export(format='onnx', imgsz={imgsz}, batch={batch}, opset={opset}, dynamic={dynamic}, simplify={simplify}))"
    )
    run_cmd([py, '-c', script], source.parent, log_file)
    candidates = [source.with_suffix('.onnx')]
    candidates += sorted(source.parent.glob(source.stem + '*.onnx'), key=lambda x: x.stat().st_mtime, reverse=True)
    exported = next((p for p in candidates if p.exists()), None)
    if not exported:
        raise RuntimeError('Ultralytics 命令执行结束，但没有找到导出的 .onnx 文件。')
    dst = out_dir / f'{safe_name(source.stem)}.onnx'
    shutil.copy2(exported, dst)
    append_log(log_file, f'ONNX 已生成：{dst}')
    return dst


def export_paddle_inference(source: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    if source.suffix.lower() in {'.pdmodel', '.pdiparams'}:
        model_dir = source.parent
        dst = out_dir / 'paddle_inference'
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(model_dir, dst)
        return dst
    if source.suffix.lower() != '.pdparams':
        raise RuntimeError('Paddle Inference 导出只接受 .pdparams 训练权重或已有 .pdmodel/.pdiparams。')
    paddledet_raw = str(resource.get('paddledet_dir') or params.get('paddledet_dir') or '').strip()
    paddledet_dir = Path(paddledet_raw) if paddledet_raw else None
    python_path = str(resource.get('paddle_python') or params.get('paddle_python') or resource.get('python_path') or sys.executable)
    config_path = Path(str(params.get('config_path') or resource.get('config_path') or ''))
    export_py = (paddledet_dir / 'tools' / 'export_model.py') if paddledet_dir else None
    if not paddledet_dir or not paddledet_dir.exists() or not export_py or not export_py.exists():
        raise RuntimeError('未找到 PaddleDetection/tools/export_model.py，请在部署资源中配置 PaddleDetection 目录。')
    if not config_path.exists():
        raise RuntimeError('没有找到该 .pdparams 对应的训练 yml 配置，无法真实导出 Paddle Inference 模型。')
    out_root = out_dir / 'paddle_export'
    out_root.mkdir(parents=True, exist_ok=True)
    cmd = [python_path, str(export_py), '-c', str(config_path), '--output_dir', str(out_root), '-o', f'weights={source}']
    run_cmd(cmd, paddledet_dir, log_file)
    dirs = [p for p in out_root.rglob('*') if p.is_dir() and ((p/'model.pdmodel').exists() or (p/'model.json').exists() or (p/'model.pdiparams').exists())]
    if not dirs:
        # Paddle 3.x may export model.json instead of model.pdmodel
        dirs = [p.parent for p in out_root.rglob('*.pdiparams')]
    if not dirs:
        raise RuntimeError('PaddleDetection export_model.py 已执行，但没有找到推理模型输出。')
    model_dir = dirs[0]
    final_dir = out_dir / 'paddle_inference'
    if final_dir.exists(): shutil.rmtree(final_dir)
    shutil.copytree(model_dir, final_dir)
    append_log(log_file, f'Paddle Inference 模型已生成：{final_dir}')
    return final_dir


def paddle_inference_to_onnx(model_dir: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    paddle2onnx = which([str(resource.get('paddle2onnx_path') or ''), 'paddle2onnx'])
    if not paddle2onnx:
        raise RuntimeError('需要把飞桨模型转换到 ONNX，但当前部署资源没有检测到 paddle2onnx。请在飞桨环境安装 paddle2onnx 或配置命令路径。')
    model_file = None
    params_file = None
    for name in ['model.pdmodel', 'model.json']:
        p = model_dir / name
        if p.exists(): model_file = p; break
    p = model_dir / 'model.pdiparams'
    if p.exists(): params_file = p
    if not model_file or not params_file:
        raise RuntimeError('Paddle Inference 目录缺少 model.pdmodel/model.json 或 model.pdiparams。')
    out = out_dir / 'model_from_paddle.onnx'
    # paddle2onnx CLI supports model_dir and save_file on current releases.
    cmd = [paddle2onnx, '--model_dir', str(model_dir), '--model_filename', model_file.name, '--params_filename', params_file.name, '--save_file', str(out)]
    run_cmd(cmd, out_dir, log_file)
    if not out.exists():
        raise RuntimeError('paddle2onnx 已执行，但没有生成 ONNX。')
    return out


def prepare_onnx(source: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    ext = source.suffix.lower()
    if ext in {'.pt', '.pth', '.onnx'}:
        return export_pt_to_onnx(source, out_dir, resource, params, log_file)
    if ext in {'.pdparams', '.pdmodel', '.pdiparams'}:
        inf = export_paddle_inference(source, out_dir, resource, params, log_file)
        return paddle_inference_to_onnx(inf, out_dir, resource, params, log_file)
    raise RuntimeError(f'当前源模型格式 {ext} 暂不能转换为 ONNX。')


def build_tensorrt(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    root_raw = str(resource.get('tool_root') or '').strip()
    trtexec = which([str(resource.get('trtexec_path') or ''), str(Path(root_raw)/'bin'/'trtexec') if root_raw else '', 'trtexec'])
    if not trtexec:
        raise RuntimeError('未检测到 trtexec，无法生成 TensorRT Engine。请在 NVIDIA/TensorRT 服务器配置部署资源。')
    precision = str(params.get('precision') or 'fp16').lower()
    if precision == 'int8':
        raise RuntimeError('v39 当前 TensorRT INT8 不做伪转换：需要真实 Q/DQ ONNX 或校准器。请先使用 FP16，或后续配置 INT8 校准缓存。')
    engine = out_dir / f'{safe_name(onnx.stem)}_{precision}.engine'
    cmd = [trtexec, f'--onnx={onnx}', f'--saveEngine={engine}']
    if precision == 'fp16': cmd.append('--fp16')
    workspace = int(params.get('workspace_mb') or 2048)
    # TensorRT 10 使用 --memPoolSize；较老版本使用 --workspace。先读帮助信息，避免固定参数导致真实环境转换失败。
    try:
        hp = subprocess.run([trtexec, '--help'], capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=15)
        help_text = (hp.stdout or '') + '\n' + (hp.stderr or '')
    except Exception:
        help_text = ''
    if '--memPoolSize' in help_text:
        cmd.append(f'--memPoolSize=workspace:{workspace}M')
    elif '--workspace' in help_text:
        cmd.append(f'--workspace={workspace}')
    else:
        append_log(log_file, '未识别 trtexec workspace 参数版本，使用当前版本推荐的 --memPoolSize。')
        cmd.append(f'--memPoolSize=workspace:{workspace}M')
    run_cmd(cmd, out_dir, log_file)
    if not engine.exists(): raise RuntimeError('TensorRT 转换结束，但没有生成 .engine 文件。')
    return engine


def find_tpu_tools(resource: Dict[str, Any]):
    root = Path(str(resource.get('tool_root') or '')) if resource.get('tool_root') else None
    roots = []
    if root:
        roots += [root, root/'python'/'tools', root/'python'/'utils']
    def f(name):
        cands=[]
        for r in roots: cands.append(str(r/name))
        cands += [name, name.replace('.py','')]
        return which(cands)
    return f('model_transform.py'), f('model_deploy.py'), f('run_calibration.py')


def build_sophon(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], calibration_dir: Optional[Path], log_file: Path) -> Path:
    transform, deploy, cali = find_tpu_tools(resource)
    if not transform or not deploy:
        raise RuntimeError('未检测到 TPU-MLIR 的 model_transform.py / model_deploy.py。请在算能转换服务器配置 TPU-MLIR 环境。')
    py = str(resource.get('python_path') or sys.executable)
    chip = str(params.get('chip') or 'bm1684x').lower()
    precision = str(params.get('precision') or 'fp16').lower()
    qmap = {'fp32':'F32','f32':'F32','fp16':'F16','f16':'F16','bf16':'BF16','int8':'INT8'}
    quant = qmap.get(precision, precision.upper())
    h = int(params.get('input_height') or params.get('input_size') or 640)
    w = int(params.get('input_width') or params.get('input_size') or 640)
    batch = int(params.get('batch') or 1)
    mean = str(params.get('mean') or '0.0,0.0,0.0')
    scale = str(params.get('scale') or '0.0039216,0.0039216,0.0039216')
    pixel = str(params.get('pixel_format') or 'rgb').lower()
    name = safe_name(params.get('model_name') or onnx.stem)
    mlir = out_dir / f'{name}.mlir'
    cmd = [py, transform, '--model_name', name, '--model_def', str(onnx), '--input_shapes', f'[[{batch},3,{h},{w}]]', '--mean', mean, '--scale', scale, '--pixel_format', pixel]
    if bool(params.get('keep_aspect_ratio', True)): cmd.append('--keep_aspect_ratio')
    cmd += ['--mlir', str(mlir)]
    run_cmd(cmd, out_dir, log_file)
    if not mlir.exists(): raise RuntimeError('TPU-MLIR model_transform 没有生成 .mlir。')
    cali_table = None
    if quant == 'INT8':
        if not cali or not calibration_dir or not calibration_dir.exists():
            raise RuntimeError('INT8 BMODEL 必须提供真实校准数据，并且部署资源需包含 run_calibration.py。')
        cali_table = out_dir / f'{name}_cali_table'
        input_num = int(params.get('calibration_count') or 100)
        ccmd = [py, cali, str(mlir), '--dataset', str(calibration_dir), '--input_num', str(input_num), '--processor', chip, '-o', str(cali_table)]
        method = str(params.get('calibration_method') or '').strip()
        if method: ccmd += ['--cali_method', method]
        run_cmd(ccmd, out_dir, log_file)
        if not cali_table.exists(): raise RuntimeError('INT8 校准执行结束，但没有生成 calibration table。')
    model = out_dir / f'{name}_{chip}_{precision}.bmodel'
    dcmd = [py, deploy, '--mlir', str(mlir), '--quantize', quant, '--processor', chip, '--model', str(model)]
    if cali_table: dcmd += ['--calibration_table', str(cali_table)]
    if bool(params.get('dynamic', False)): dcmd.append('--dynamic')
    num_core = int(params.get('num_core') or 1)
    if num_core > 1: dcmd += ['--num_core', str(num_core)]
    run_cmd(dcmd, out_dir, log_file)
    if not model.exists(): raise RuntimeError('TPU-MLIR 编译结束，但没有生成 .bmodel。')
    return model


def build_ascend(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    root_raw = str(resource.get('tool_root') or '').strip()
    atc = which([str(resource.get('atc_path') or ''), str(Path(root_raw)/'bin'/'atc') if root_raw else '', 'atc'])
    if not atc:
        raise RuntimeError('未检测到 CANN ATC，无法生成 Ascend OM。请在华为 Atlas/CANN 服务器配置部署资源。')
    soc = str(params.get('soc_version') or params.get('chip') or '').strip()
    atlas_product = str(params.get('atlas_product') or '').strip()
    if not soc:
        raise RuntimeError('华为 Atlas 转换必须指定 soc_version，例如 Ascend310P3。')
    h = int(params.get('input_height') or params.get('input_size') or 640)
    w = int(params.get('input_width') or params.get('input_size') or 640)
    batch = int(params.get('batch') or 1)
    input_name = str(params.get('input_name') or 'images').strip()
    prefix = out_dir / f'{safe_name(onnx.stem)}_{safe_name(soc)}'
    cmd = [atc, f'--model={onnx}', '--framework=5', f'--output={prefix}', f'--soc_version={soc}', f'--input_shape={input_name}:{batch},3,{h},{w}']
    precision_mode = str(params.get('precision_mode') or '').strip()
    if precision_mode:
        cmd.append(f'--precision_mode={precision_mode}')
    elif str(params.get('precision') or '').lower() == 'fp16':
        cmd.append('--precision_mode=allow_fp32_to_fp16')
    if bool(params.get('aipp_enabled', False)):
        content = str(params.get('aipp_config') or '').strip()
        if not content:
            content = f'''aipp_op {{\n  aipp_mode: static\n  input_format: RGB888_U8\n  src_image_size_w: {w}\n  src_image_size_h: {h}\n  csc_switch: false\n  min_chn_0: 0\n  min_chn_1: 0\n  min_chn_2: 0\n  var_reci_chn_0: 0.003921568627451\n  var_reci_chn_1: 0.003921568627451\n  var_reci_chn_2: 0.003921568627451\n}}'''
        aipp = out_dir / 'aipp.cfg'
        aipp.write_text(content, encoding='utf-8')
        cmd.append(f'--insert_op_conf={aipp}')
    env = os.environ.copy()
    env_script = str(resource.get('env_script') or '').strip()
    # If the resource uses a shell environment script, execute through bash so source takes effect.
    if env_script and os.name != 'nt':
        shell_cmd = 'source ' + shlex_quote(env_script) + ' && ' + ' '.join(shlex_quote(str(x)) for x in cmd)
        run_cmd(['bash', '-lc', shell_cmd], out_dir, log_file, env=env)
    else:
        run_cmd(cmd, out_dir, log_file, env=env)
    om = Path(str(prefix) + '.om')
    if not om.exists(): raise RuntimeError('ATC 执行结束，但没有生成 .om 文件。')
    return om



def build_rockchip(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], calibration_dir: Optional[Path], log_file: Path) -> Path:
    py = str(resource.get('python_path') or params.get('rknn_python') or sys.executable)
    if not py or not Path(py).exists():
        raise RuntimeError('瑞芯微转换需要一个安装了 RKNN-Toolkit2 的 Python 环境。请到“部署资源/部署插件”配置 RKNN Python。')
    # Validate SDK in the selected environment, not the platform venv.
    cp = subprocess.run([py, '-c', "from rknn.api import RKNN; import importlib.metadata as m; print(m.version('rknn-toolkit2'))"], capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=20)
    if cp.returncode != 0:
        raise RuntimeError('当前 Python 未安装可用的 RKNN-Toolkit2：\n' + (cp.stderr or cp.stdout or '')[-1800:])
    chip = str(params.get('chip') or 'rk3588').lower()
    supported = {'rk3588','rk3576','rk3566','rk3568','rk3562','rv1103','rv1106','rv1103b','rv1106b','rv1126b','rk2118'}
    if chip not in supported:
        raise RuntimeError(f'当前平台未开放该瑞芯微 target_platform：{chip}')
    precision = str(params.get('precision') or 'fp16').lower()
    quant = precision in {'int8','i8','u8'}
    dataset_txt = None
    if quant:
        if not calibration_dir or not calibration_dir.exists():
            raise RuntimeError('RKNN INT8 转换需要真实校准图片。请在转换任务选择校准数据集。')
        imgs=[]
        for ext in ['*.jpg','*.jpeg','*.png','*.bmp','*.webp']:
            imgs.extend(calibration_dir.rglob(ext))
        imgs=sorted(set(imgs))
        if not imgs:
            raise RuntimeError('校准目录中没有可用图片。')
        dataset_txt=out_dir/'rknn_dataset.txt'
        dataset_txt.write_text('\n'.join(str(x.resolve()) for x in imgs), encoding='utf-8')
        append_log(log_file, f'RKNN INT8 校准图片：{len(imgs)} 张')
    out=out_dir/f'{safe_name(onnx.stem)}_{chip}_{"int8" if quant else "fp"}.rknn'
    mean=str(params.get('mean') or '0,0,0')
    std=str(params.get('rknn_std') or '255,255,255')
    runner=Path(__file__).resolve().parent/'rknn_convert_runner.py'
    if not runner.exists(): raise RuntimeError('缺少平台 RKNN 转换执行器 rknn_convert_runner.py')
    cmd=[py,str(runner),'--onnx',str(onnx),'--output',str(out),'--chip',chip,'--precision',precision,'--mean',mean,'--std',std]
    if dataset_txt: cmd += ['--dataset',str(dataset_txt)]
    run_cmd(cmd, out_dir, log_file, timeout=int(params.get('timeout') or 3600))
    if not out.exists(): raise RuntimeError('RKNN-Toolkit2 执行结束，但没有生成 .rknn 文件。')
    return out

def copy_artifact(src: Path, artifacts: Path):
    artifacts.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        dst = artifacts / src.name
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return dst
    dst = artifacts / src.name
    if src.resolve() != dst.resolve(): shutil.copy2(src, dst)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job-dir', required=True)
    args = ap.parse_args()
    job_dir = Path(args.job_dir).resolve()
    job_file = job_dir / 'job.json'
    log_file = job_dir / 'convert.log'
    source_dir = job_dir / 'source'
    work = job_dir / 'work'
    artifacts = job_dir / 'artifacts'
    work.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    job = read_json(job_file, {})
    resource = job.get('resource') or {}
    params = job.get('params') or {}
    source = Path(job.get('source_path') or '')
    calibration_dir = Path(job.get('calibration_dir') or '') if job.get('calibration_dir') else None
    try:
        update(job_file, status='running', progress=3, stage='准备源模型', message='转换任务已启动', started_at=now())
        append_log(log_file, f"转换目标：{job.get('target')} / 资源：{resource.get('name','')}")
        if not source.exists(): raise RuntimeError(f'源模型不存在：{source}')
        target = str(job.get('target') or '').lower()
        outputs = []
        if target == 'onnx':
            update(job_file, progress=18, stage='导出 ONNX', message='正在生成通用 ONNX')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            outputs.append(copy_artifact(onnx, artifacts))
        elif target == 'paddle_inference':
            update(job_file, progress=18, stage='导出 Paddle Inference', message='正在导出飞桨推理模型')
            pdir = export_paddle_inference(source, work, resource, params, log_file)
            outputs.append(copy_artifact(pdir, artifacts))
        elif target == 'tensorrt':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 TensorRT 中间模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            update(job_file, progress=52, stage='编译 TensorRT Engine', message='正在调用 TensorRT')
            engine = build_tensorrt(onnx, work, resource, params, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(engine, artifacts)])
        elif target == 'sophon':
            update(job_file, progress=10, stage='准备 ONNX', message='正在生成 TPU-MLIR 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            update(job_file, progress=45 if str(params.get('precision')).lower()!='int8' else 30, stage='TPU-MLIR 编译', message='正在生成 BMODEL')
            bmodel = build_sophon(onnx, work, resource, params, calibration_dir, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(bmodel, artifacts)])
        elif target == 'ascend':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 ATC 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            update(job_file, progress=55, stage='ATC 编译', message='正在生成 OM')
            om = build_ascend(onnx, work, resource, params, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(om, artifacts)])
        elif target == 'rockchip':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 RKNN 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            update(job_file, progress=52, stage='RKNN 编译', message='正在调用 RKNN-Toolkit2 生成 RKNN')
            rknn = build_rockchip(onnx, work, resource, params, calibration_dir, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(rknn, artifacts)])
        else:
            raise RuntimeError(f'不支持的转换目标：{target}')
        manifest = {
            'job_id': job.get('id'), 'source_model': source.name, 'target': target,
            'resource': {k:resource.get(k) for k in ['id','name','kind','mode','version']},
            'params': params, 'outputs': [str(p.relative_to(job_dir)) for p in outputs],
            'created_at': now(),
        }
        write_json(artifacts/'deployment_manifest.json', manifest)
        output_rows=[]
        for p in artifacts.rglob('*'):
            if p.is_file():
                output_rows.append({'name':p.name,'path':str(p),'rel':str(p.relative_to(job_dir)),'size_mb':round(p.stat().st_size/1024/1024,3)})
        update(job_file, status='done', progress=100, stage='转换完成', message='部署模型已生成', finished_at=now(), outputs=output_rows, validation_status='not_run')
        append_log(log_file, '转换完成。')
    except Exception as e:
        append_log(log_file, '转换失败：' + str(e))
        update(job_file, status='failed', stage='转换失败', message=str(e), error=str(e), finished_at=now())
        raise


if __name__ == '__main__':
    main()
