"""RKNN-Toolkit2 conversion runner.
Runs inside the Python environment where official rknn-toolkit2 is installed.
Conversion does NOT require a Rockchip board. Board Runtime/Lite2 is only for final inference/validation.
"""
import argparse
import json
from pathlib import Path

# This runner executes inside a separate RKNN virtualenv. Keep it independent of
# platform_core/__init__.py and of the control-plane's installed dependencies.
RKNN_ONNX_DEPENDENCY_CODE = "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE"


def parse_triplet(text, default):
    try:
        vals=[float(x.strip()) for x in str(text).split(',') if x.strip()]
        return vals if len(vals)==3 else default
    except Exception:
        return default


def checked_rknn_step(code, label, call, *, allow_none=False):
    """Expose the failed official API stage without suppressing SDK tracebacks."""
    try:
        result = call()
        if result != 0 and not (allow_none and result is None):
            raise RuntimeError(f"{label} 失败: {result}")
        return result
    except Exception:
        print(f"__RKNN_STAGE_ERROR__={code}", flush=True)
        raise


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--onnx', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--chip', required=True)
    ap.add_argument('--precision', default='fp16')
    ap.add_argument('--dataset', default='')
    ap.add_argument('--mean', default='0,0,0')
    ap.add_argument('--std', default='255,255,255')
    ap.add_argument('--verbose', action='store_true')
    args=ap.parse_args()
    # Guard the *actual* RKNN interpreter before load_onnx emits an opaque traceback.
    try:
        import onnx as onnx_module
    except ImportError as error:
        raise SystemExit(
            f"{RKNN_ONNX_DEPENDENCY_CODE}: RKNN Python 环境未安装 ONNX: {error}"
        ) from None
    if not hasattr(onnx_module, "mapping"):
        version = str(getattr(onnx_module, "__version__", "未知"))
        raise SystemExit(
            f"{RKNN_ONNX_DEPENDENCY_CODE}: "
            f"当前 RKNN Python 环境的 ONNX {version} 缺少 onnx.mapping；"
            "请在该环境中安装 onnx==1.18.0 后重试。"
        )
    try:
        from rknn.api import RKNN
    except Exception as e:
        raise SystemExit('RKNN-Toolkit2 未安装或当前 Python 环境不可用: '+str(e))
    onnx=Path(args.onnx).resolve(); out=Path(args.output).resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    if not onnx.exists(): raise SystemExit(f'ONNX 不存在: {onnx}')
    quant=str(args.precision).lower() in {'int8','i8','u8'}
    dataset=str(args.dataset or '').strip()
    if quant and (not dataset or not Path(dataset).exists()):
        raise SystemExit('INT8 RKNN 转换必须提供校准 dataset.txt')
    mean=parse_triplet(args.mean,[0,0,0]); std=parse_triplet(args.std,[255,255,255])
    rknn=RKNN(verbose=bool(args.verbose))
    try:
        checked_rknn_step('RKNN_CONFIG_FAILED', 'rknn.config',
                          lambda: rknn.config(mean_values=[mean], std_values=[std], target_platform=str(args.chip).lower()),
                          allow_none=True)
        checked_rknn_step('RKNN_LOAD_ONNX_FAILED', 'rknn.load_onnx', lambda: rknn.load_onnx(model=str(onnx)))
        checked_rknn_step('RKNN_BUILD_FAILED', 'rknn.build',
                          lambda: rknn.build(do_quantization=quant, dataset=dataset if quant else None))
        checked_rknn_step('RKNN_EXPORT_FAILED', 'rknn.export_rknn', lambda: rknn.export_rknn(str(out)))
        print(json.dumps({'ok':True,'output':str(out),'chip':args.chip,'precision':args.precision},ensure_ascii=False))
    finally:
        try:rknn.release()
        except Exception:pass

if __name__=='__main__': main()
