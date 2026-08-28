"""RKNN-Toolkit2 conversion runner.
Runs inside the Python environment where official rknn-toolkit2 is installed.
Conversion does NOT require a Rockchip board. Board Runtime/Lite2 is only for final inference/validation.
"""
import argparse
import json
from pathlib import Path


def parse_triplet(text, default):
    try:
        vals=[float(x.strip()) for x in str(text).split(',') if x.strip()]
        return vals if len(vals)==3 else default
    except Exception:
        return default


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
        ret=rknn.config(mean_values=[mean], std_values=[std], target_platform=str(args.chip).lower())
        if ret not in (None,0): raise RuntimeError(f'rknn.config 失败: {ret}')
        ret=rknn.load_onnx(model=str(onnx))
        if ret!=0: raise RuntimeError(f'rknn.load_onnx 失败: {ret}')
        ret=rknn.build(do_quantization=quant, dataset=dataset if quant else None)
        if ret!=0: raise RuntimeError(f'rknn.build 失败: {ret}')
        ret=rknn.export_rknn(str(out))
        if ret!=0: raise RuntimeError(f'rknn.export_rknn 失败: {ret}')
        print(json.dumps({'ok':True,'output':str(out),'chip':args.chip,'precision':args.precision},ensure_ascii=False))
    finally:
        try:rknn.release()
        except Exception:pass

if __name__=='__main__': main()
