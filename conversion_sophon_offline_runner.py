"""Optional TPU-MLIR CPU/toolchain simulator adapter; never board inference.

Runs in the user's configured Sophon SDK Python environment. Failure to
import its official model_runner is reported as unavailable, not success.
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import numpy as np
    from tools.model_runner import model_inference

    with np.load(args.input, allow_pickle=False) as data:
        tensors = {key: data[key] for key in data.files}
    result = model_inference(tensors, str(Path(args.model).resolve()))
    if not isinstance(result, dict) or not result:
        raise ValueError("Sophon 模拟器未返回可检查的模型输出")
    np.savez(args.output, **result)


if __name__ == "__main__":
    main()
