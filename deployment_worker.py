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

from platform_core.rknn_runtime import (
    RKNN_ONNX_DEPENDENCY_CODE,
    probe_rknn_toolkit,
)

from platform_core.sophon_runtime import (find_sophon_tools, require_sophon_toolchain, tool_argv)

from platform_core.conversion import (
    ConversionError,
    build_manifest,
    file_record,
    sha256_file,
    validate_target,
    conversion_input_shape,
)


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
    height, width = conversion_input_shape(params)
    imgsz = [height, width] if height != width else height
    opset = int(params.get('opset') or 12)
    dynamic = bool(params.get('dynamic', False))
    simplify = bool(params.get('simplify', False))
    batch = max(1, int(params.get('batch') or 1))
    half = params.get('kind') == 'onnx' and params.get('precision') == 'fp16'
    script = (
        "import sys; from pathlib import Path; from ultralytics import YOLO; "
        "p=Path(sys.argv[1]).resolve(strict=True); m=YOLO(str(p)); "
        f"print(m.export(format='onnx', imgsz={imgsz}, batch={batch}, opset={opset}, dynamic={dynamic}, simplify={simplify}, half={half}))"
    )
    run_cmd([py, '-c', script, str(source.resolve())], source.parent, log_file)
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
    from platform_core.color_adapter import adapt_onnx_color_input

    ext = source.suffix.lower()
    if ext in {'.pt', '.pth', '.onnx'}:
        original = export_pt_to_onnx(source, out_dir, resource, params, log_file)
    elif ext in {'.pdparams', '.pdmodel', '.pdiparams'}:
        inf = export_paddle_inference(source, out_dir, resource, params, log_file)
        original = paddle_inference_to_onnx(inf, out_dir, resource, params, log_file)
    else:
        raise RuntimeError(f'当前源模型格式 {ext} 暂不能转换为 ONNX。')
    converted, evidence = adapt_onnx_color_input(original, out_dir, params)
    params['color_adapter_evidence'] = evidence
    if evidence.get('applied'):
        append_log(log_file, '颜色适配生效：' + evidence['source_color_order'].upper()
                   + ' → ' + evidence['input_color_order'].upper() + '；ONNX Runtime数值等价验证通过。')
    return converted


def preflight_vendor_tool(target: str, resource: Dict[str, Any], params: Dict[str, Any]):
    root_raw = str(resource.get('tool_root') or '').strip()
    if target == 'tensorrt':
        tool = which([str(resource.get('trtexec_path') or ''), str(Path(root_raw)/'bin'/'trtexec') if root_raw else '', 'trtexec'])
        if not tool:
            raise ConversionError('TENSORRT_NOT_FOUND', '未检测到 trtexec，无法生成 TensorRT Engine。', solution='请在 NVIDIA 部署服务器安装 TensorRT，并在部署资源中配置 trtexec 路径。')
    elif target == 'ascend':
        tool = which([str(resource.get('atc_path') or ''), str(Path(root_raw)/'bin'/'atc') if root_raw else '', 'atc'])
        if not tool:
            raise ConversionError('ATC_NOT_FOUND', '未检测到 CANN ATC，无法生成 Ascend OM。', solution='请在 Linux 转换服务器安装华为 CANN Toolkit，并配置 ATC 路径和环境脚本。')
    elif target == 'sophon':
        return require_sophon_toolchain(resource, chip=str(params.get('chip') or '').lower(), precision=str(params.get('precision') or 'fp16'))
    elif target == 'rockchip':
        py = str(resource.get('python_path') or params.get('rknn_python') or sys.executable)
        if not py or not Path(py).exists():
            raise ConversionError('RKNN_TOOLKIT_NOT_FOUND', '瑞芯微转换需要一个安装了 RKNN-Toolkit2 的 Python 环境。', solution='请在 Linux x86_64 转换环境安装官方 RKNN-Toolkit2，并配置该环境的 Python 路径。')
        probe = probe_rknn_toolkit(py,**({"target_chips":[params["chip"]]} if params.get("constraint_id")=="rknn-verified" else {}))
        if not probe["available"]:
            if probe.get("error_code") == RKNN_ONNX_DEPENDENCY_CODE:
                raise ConversionError(
                    RKNN_ONNX_DEPENDENCY_CODE,
                    str(probe["error"]),
                    solution=(
                        f"请在转换节点执行 {py} -m pip install --no-deps "
                        "--force-reinstall onnx==1.18.0；然后检查 "
                        "hasattr(onnx, 'mapping') 是否为 True。"
                    ),
                )
            raise ConversionError(
                'RKNN_TOOLKIT_NOT_FOUND',
                'RKNN 转换 Python 环境未就绪：' + str(probe.get('error') or 'RKNN-Toolkit2 不可用')[-500:],
                solution='请检查转换节点的 RKNN Python 路径及 Toolkit2 安装。',
            )
        return probe


def validate_onnx_runtime(onnx_path: Path, params: Dict[str, Any], log_file: Path, *, expected_precision: str | None = None) -> Dict[str, Any]:
    try:
        import numpy as np
        import onnx
        import onnxruntime as ort

        model = onnx.load(str(onnx_path))
        onnx.checker.check_model(model)
        floating_types = {t.data_type for t in model.graph.initializer}
        floating_types.update(t.type.tensor_type.elem_type for t in model.graph.input)
        if expected_precision == 'fp16' and onnx.TensorProto.FLOAT16 not in floating_types:
            raise ValueError('ONNX requested precision FP16 was not applied by the exporter')
        if expected_precision == 'fp32' and floating_types.intersection({onnx.TensorProto.FLOAT16, onnx.TensorProto.BFLOAT16}):
            raise ValueError('ONNX requested precision FP32 differs from exported tensors')
        session = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
        feeds = {}
        height, width = conversion_input_shape(params)
        expected_shape = [int(params.get('batch') or 1), 3, height, width]
        actual_shapes = []
        dtype_map = {
            'tensor(float)': np.float32,
            'tensor(float16)': np.float16,
            'tensor(double)': np.float64,
            'tensor(int64)': np.int64,
            'tensor(int32)': np.int32,
        }
        if params.get('kind') == 'sophon' and len(session.get_inputs()) != 1:
            raise ValueError('Sophon首期只支持单一NCHW输入')
        for input_meta in session.get_inputs():
            if params.get('kind') == 'sophon' and list(input_meta.shape) != expected_shape:
                raise ValueError(f'ONNX input shape {input_meta.shape} 与编译尺寸 {expected_shape} 不一致')
            if params.get('kind') in {'rockchip','ascend','tensorrt'} and len(input_meta.shape)==4 and any(type(d) is int and d>0 and d!=expected_shape[i] for i,d in enumerate(input_meta.shape)):
                raise ValueError(f'ONNX input shape {input_meta.shape} differs from requested shape {expected_shape}')
            actual_shapes.append(list(input_meta.shape))
            dtype = dtype_map.get(input_meta.type)
            if dtype is None:
                raise ValueError(f'暂不支持 ONNX 输入类型：{input_meta.type}')
            shape = []
            for index, dimension in enumerate(input_meta.shape):
                if isinstance(dimension, int) and dimension > 0:
                    shape.append(dimension)
                elif len(input_meta.shape) == 4:
                    shape.append(expected_shape[index])
                else:
                    shape.append(1)
            feeds[input_meta.name] = np.zeros(shape, dtype=dtype)
        outputs = session.run(None, feeds)
        result = {
            'checker': 'passed',
            'runtime': 'onnxruntime',
            'runtime_version': ort.__version__,
            'input_names': [item.name for item in session.get_inputs()],
            'input_shapes': actual_shapes,
            'output_names': [item.name for item in session.get_outputs()],
            'output_count': len(outputs),
            'input_types': [item.type for item in session.get_inputs()],
            'floating_tensor_types': sorted({onnx.TensorProto.DataType.Name(t.data_type) for t in model.graph.initializer if t.data_type in (onnx.TensorProto.FLOAT, onnx.TensorProto.FLOAT16, onnx.TensorProto.DOUBLE, onnx.TensorProto.BFLOAT16)}),
            'opset_imports': {item.domain: item.version for item in model.opset_import},
        }
        append_log(log_file, 'ONNX Checker 与 ONNX Runtime 空白输入推理验证通过。')
        return result
    except Exception as error:
        raise ConversionError(
            'ONNX_VALIDATION_FAILED',
            f'ONNX 结构或 ONNX Runtime 推理验证失败：{error}',
            solution='请检查导出 opset、动态输入和算子兼容性，并确认转换环境已安装 onnxruntime。',
        ) from error


def build_tensorrt(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    root_raw = str(resource.get('tool_root') or '').strip()
    trtexec = which([str(resource.get('trtexec_path') or ''), str(Path(root_raw)/'bin'/'trtexec') if root_raw else '', 'trtexec'])
    if not trtexec:
        raise ConversionError(
            'TENSORRT_NOT_FOUND',
            '未检测到 trtexec，无法生成 TensorRT Engine。',
            solution='请在 NVIDIA 部署服务器安装 TensorRT，并在部署资源中配置 trtexec 路径。',
        )
    precision = str(params.get('precision') or 'fp16').lower()
    if precision == 'int8':
        raise RuntimeError('v39 当前 TensorRT INT8 不做伪转换：需要真实 Q/DQ ONNX 或校准器。请先使用 FP16，或后续配置 INT8 校准缓存。')
    engine = out_dir / f'{safe_name(onnx.stem)}_{precision}.engine'
    cmd = [trtexec, f'--onnx={onnx}', f'--saveEngine={engine}']
    if precision == 'fp16': cmd.append('--fp16')
    if precision == 'fp32': cmd.append('--noTF32')
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
    tools = find_sophon_tools(resource)
    return tools["model_transform"], tools["model_deploy"], tools["run_calibration"]


def build_sophon(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], calibration_dir: Optional[Path], log_file: Path, *, verified_toolchain: Dict[str, Any] | None = None) -> Path:
    params = validate_target("sophon", params)
    environment = verified_toolchain if verified_toolchain is not None else require_sophon_toolchain(resource, chip=params["chip"], precision=params["precision"])
    tools, py = environment["tools"], environment["python_path"]
    height, width = conversion_input_shape(params)
    # Caller supplies normalized NCHW in the selected input_color_order. Do not fuse
    # mean/scale/letterbox again. The exact caller contract travels in manifest.
    name = safe_name(str(params.get("model_name") or onnx.stem))
    mlir = out_dir / f"{name}.mlir"
    model = out_dir / f"{name}_{params['chip']}_{params['precision']}.bmodel"
    # A failed retry must not inherit an old compiled file from the work folder.
    mlir.unlink(missing_ok=True)
    model.unlink(missing_ok=True)
    timeout = int(params.get("timeout") or 3600)
    run_cmd(tool_argv(py, "model_transform", tools["model_transform"],
        "--model_name", name, "--model_def", str(onnx),
        "--input_shapes", f"[[1,3,{height},{width}]]", "--mlir", str(mlir)), out_dir, log_file, timeout=timeout)
    file_record(mlir)
    chip_option = environment.get("chip_option") or "--chip"
    if chip_option not in {"--chip", "--processor"}:
        raise ValueError("TPU-MLIR目标选项未经Adapter映射")
    sdk_precision = {"fp16":"F16", "fp32":"F32"}[params["precision"]]
    run_cmd(tool_argv(py, "model_deploy", tools["model_deploy"],
        "--mlir", str(mlir), "--quantize", sdk_precision, chip_option, params["chip"],
        "--num_core", "1", "--model", str(model)), out_dir, log_file, timeout=timeout)
    file_record(model)
    info = run_cmd(tool_argv(py, "model_tool", tools["model_tool"], "--info", str(model)),
                   out_dir, log_file, timeout=min(timeout, 30))
    import re
    observed_chips = set(re.findall(r"\b(?:bm|cv)\d+[a-z]*\b", info.lower()))
    if observed_chips != {params["chip"]}:
        raise ConversionError("SOPHON_MODEL_CHIP_MISMATCH", "BMODEL结构检查未确认唯一目标芯片",
                              solution="请检查model_tool与编译工具版本，拒绝把BMODEL登记为其他芯片。")
    write_json(out_dir / "sophon_validation.json", {
        "structure": "passed", "chip": params["chip"], "hardware_verified": False,
        "toolchain": environment, "inspection": info[-8000:], "artifact": file_record(model),
        "preprocessing": params["preprocessing"],
        "precision": params["precision"], "input_shape": [1,3,height,width],
        "model_validation_status": "incomplete", "model_validation_reason": "芯片结构已确认；尚未完成编译产物输入输出与数值对照验证",
    })
    return model


def build_ascend(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], log_file: Path) -> Path:
    root_raw = str(resource.get('tool_root') or '').strip()
    atc = which([str(resource.get('atc_path') or ''), str(Path(root_raw)/'bin'/'atc') if root_raw else '', 'atc'])
    if not atc:
        raise ConversionError(
            'ATC_NOT_FOUND',
            '未检测到 CANN ATC，无法生成 Ascend OM。',
            solution='请在 Linux 转换服务器安装华为 CANN Toolkit，并配置 ATC 路径和环境脚本。',
        )
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
    # Use the same validated contract as API admission and the persisted manifest.
    precision_mode = validate_target('ascend', params)['precision_mode']
    cmd.append(f'--precision_mode={precision_mode}')
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



def build_rockchip(onnx: Path, out_dir: Path, resource: Dict[str, Any], params: Dict[str, Any], calibration_dir: Optional[Path], log_file: Path, *, verified_toolchain: Dict[str, Any] | None = None) -> Path:
    params = validate_target("rockchip", params)
    py = str(resource.get('python_path') or params.get('rknn_python') or sys.executable)
    # Direct callers need the same environment gate as the task-level preflight.
    if verified_toolchain is None:
        preflight_vendor_tool('rockchip', resource, params)
    chip = str(params.get('chip') or '').strip().lower()
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
        recorded_source_sha = str((job.get('source_trace') or {}).get('sha256') or '')
        if target == 'sophon' and recorded_source_sha and recorded_source_sha != sha256_file(source):
            raise ConversionError('SOURCE_IDENTITY_MISMATCH', '源模型SHA256与选定版本不一致', solution='请重新选择已验证算法版本并创建转换任务。')
        target_contract = validate_target(target, params)
        params = target_contract
        toolchain = preflight_vendor_tool(target, resource, params) or {}
        outputs = []
        onnx_validation = {}
        if target == 'onnx':
            update(job_file, progress=18, stage='导出 ONNX', message='正在生成通用 ONNX')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            onnx_validation = validate_onnx_runtime(onnx, params, log_file, expected_precision=params.get('precision') if source.suffix.lower() in {'.pt','.pth'} else None)
            outputs.append(copy_artifact(onnx, artifacts))
        elif target == 'paddle_inference':
            update(job_file, progress=18, stage='导出 Paddle Inference', message='正在导出飞桨推理模型')
            pdir = export_paddle_inference(source, work, resource, params, log_file)
            outputs.append(copy_artifact(pdir, artifacts))
        elif target == 'tensorrt':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 TensorRT 中间模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            onnx_validation = validate_onnx_runtime(onnx, params, log_file)
            update(job_file, progress=52, stage='编译 TensorRT Engine', message='正在调用 TensorRT')
            engine = build_tensorrt(onnx, work, resource, params, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(engine, artifacts)])
        elif target == 'sophon':
            update(job_file, progress=10, stage='准备 ONNX', message='正在生成 TPU-MLIR 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            onnx_validation = validate_onnx_runtime(onnx, params, log_file)
            update(job_file, progress=45 if str(params.get('precision')).lower()!='int8' else 30, stage='TPU-MLIR 编译', message='正在生成 BMODEL')
            bmodel = build_sophon(onnx, work, resource, params, calibration_dir, log_file, verified_toolchain=toolchain)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(bmodel, artifacts)])
        elif target == 'ascend':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 ATC 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            onnx_validation = validate_onnx_runtime(onnx, params, log_file)
            update(job_file, progress=55, stage='ATC 编译', message='正在生成 OM')
            om = build_ascend(onnx, work, resource, params, log_file)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(om, artifacts)])
        elif target == 'rockchip':
            update(job_file, progress=12, stage='准备 ONNX', message='正在生成 RKNN 输入模型')
            onnx = prepare_onnx(source, work, resource, params, log_file)
            onnx_validation = validate_onnx_runtime(onnx, params, log_file)
            update(job_file, progress=52, stage='RKNN 编译', message='正在调用 RKNN-Toolkit2 生成 RKNN')
            rknn = build_rockchip(onnx, work, resource, params, calibration_dir, log_file, verified_toolchain=toolchain)
            outputs.extend([copy_artifact(onnx, artifacts), copy_artifact(rknn, artifacts)])
        else:
            raise RuntimeError(f'不支持的转换目标：{target}')
        if (params.get('csc_contract') or {}).get('capability')=='contract_only':
            from platform_core.conversion_csc import write_csc_deployment_bundle
            write_csc_deployment_bundle(artifacts, params['csc_contract'], include_reference_sources=False)
            outputs.extend(artifacts/name for name in ('csc_deployment_contract.json','csc_deployment_reference.zip'))
        onnx_output = next((p for p in outputs if p.is_file() and p.suffix.lower() == '.onnx'), None)
        output_records = [file_record(p, relative_to=artifacts) for p in outputs if p.is_file()]
        for directory in [p for p in outputs if p.is_dir()]:
            output_records.extend(file_record(p, relative_to=artifacts) for p in directory.rglob('*') if p.is_file())
        tool_names = {
            'onnx': 'ultralytics-export',
            'paddle_inference': 'paddledetection-export',
            'tensorrt': 'trtexec',
            'sophon': 'tpu-mlir',
            'ascend': 'cann-atc',
            'rockchip': 'rknn-toolkit2',
        }
        manifest = build_manifest(
            source=job.get('source_trace') or {
                'source_id': job.get('source_id'),
                'version_id': (job.get('source_meta') or {}).get('version_id') or '',
                'sha256': sha256_file(source),
            },
            onnx={**(file_record(onnx_output, relative_to=artifacts) if onnx_output else {}), **onnx_validation},
            target=target_contract,
            parameters=params,
            tool={
                'name': tool_names.get(target, target),
                'version': str(toolchain.get('version') or resource.get('version') or ''),
                'resource_id': resource.get('id') or '',
            },
            outputs=output_records,
            hardware_verified=False,
        )
        manifest['job_id'] = job.get('id')
        if target == 'sophon':
            sophon_facts = read_json(work/'sophon_validation.json', {})
            params["sdk_version"]=str((sophon_facts.get('toolchain') or {}).get('version') or '')
            manifest['parameters']=dict(params)
            manifest['sophon_validation'] = sophon_facts
            manifest['tool'].update(version=sophon_facts.get('toolchain', {}).get('version', ''),
                                    python_path=sophon_facts.get('toolchain', {}).get('python_path', ''))
        if target == 'onnx':
            manifest['status'] = 'runtime_verified'
            manifest['runtime_verified'] = True
        compiler_precision = {
            'sophon': {'fp16': 'F16', 'fp32': 'F32'}.get(params.get('precision')),
            'rockchip': 'do_quantization=' + str(params.get('precision') == 'int8').lower(),
            'ascend': params.get('precision_mode'),
            'tensorrt': '--fp16' if params.get('precision') == 'fp16' else '--noTF32',
        }.get(target)
        evidence = {
            'source_training_precision': params.get('source_training_precision'),
            'resolved_precision': params.get('precision'),
            'compiler_precision': compiler_precision,
            'input_color_order': params.get('input_color_order'),
            'source_color_order': params.get('source_color_order'),
            'color_adapter': params.get('color_adapter_evidence'),
            'csc': params.get('csc_contract'),
            'artifact_precision': None,  # No dtype inspection; compiler mode is not an artifact dtype.
            'onnx_export': 'reused_existing_onnx' if source.suffix.lower() == '.onnx' else 'exported',
            'onnx_export_parameters_applied': source.suffix.lower() != '.onnx',
            'sdk_version': manifest['tool']['version'],
            'compiler_completed': target in {'sophon','rockchip','ascend','tensorrt'},
            'onnx_input_shape': next((shape for shape in onnx_validation.get('input_shapes', []) if len(shape)==4 and all(type(d) is int and 0<d<=8192 for d in shape)), None) if len(onnx_validation.get('input_shapes', []))==1 else None,
            'onnx_input_types': onnx_validation.get('input_types') or [],
            'onnx_floating_tensor_types': onnx_validation.get('floating_tensor_types') or [],
            'onnx_opset_imports': onnx_validation.get('opset_imports') or {},
        }
        manifest['execution_evidence'] = evidence
        write_json(artifacts/'manifest.json', manifest)
        output_rows=[]
        for p in artifacts.rglob('*'):
            if p.is_file() and p.suffix.lower() not in {'.py','.md'}:
                output_rows.append({'name':p.name,'path':str(p),'rel':str(p.relative_to(job_dir)),'size_mb':round(p.stat().st_size/1024/1024,3)})
        runtime_verified = target == 'onnx'
        update(job_file, status='done', progress=100, stage='转换完成', message='ONNX Runtime 已真实加载验证' if runtime_verified else '部署模型已生成（尚未实机验证）', finished_at=now(), outputs=output_rows, params=params, execution_evidence=evidence, validation_status='runtime_verified' if runtime_verified else 'converted_unverified', runtime_verified=runtime_verified, manifest_path=str(artifacts/'manifest.json'))
        append_log(log_file, '转换完成。')
    except Exception as e:
        append_log(log_file, '转换失败：' + str(e))
        update(
            job_file,
            status='failed',
            stage='转换失败',
            message=str(e),
            error=str(e),
            error_code=str(getattr(e, 'code', 'CONVERSION_FAILED')),
            solution=str(getattr(e, 'solution', '请查看转换日志并检查源模型、目标参数和官方编译工具。')),
            finished_at=now(),
        )
        raise


if __name__ == '__main__':
    main()
