"""Graph-level RGB/BGR model-input adaptation shared by ONNX and vendor converters.

The tensor contract is NCHW and caller-owned normalization. Existing checkpoints
are not modified; the adapted ONNX is an independent compilation input.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class ColorAdapterError(ValueError):
    pass


def color_contract(params: Mapping[str, Any]) -> dict[str, str] | None:
    if "input_color_order" not in params and "source_color_order" not in params:
        return None  # Legacy jobs are unchanged; their input color was not recorded.
    source = params.get("source_color_order", "rgb")
    target = params.get("input_color_order", "rgb")
    if not isinstance(source, str) or source not in ("rgb", "bgr"):
        raise ColorAdapterError("源模型颜色仅允许 rgb / bgr")
    if not isinstance(target, str) or target not in ("rgb", "bgr"):
        raise ColorAdapterError("目标输入颜色仅允许 rgb / bgr")
    return {"source_color_order": source, "input_color_order": target}


def adapt_onnx_color_input(
    source_path: Path, output_dir: Path, params: Mapping[str, Any]
) -> tuple[Path, dict[str, Any]]:
    contract = color_contract(params)
    path = Path(source_path)
    if contract is None:
        return path, {"status": "legacy_unknown", "applied": False, "verified": False}
    src, dst = contract["source_color_order"], contract["input_color_order"]
    evidence: dict[str, Any] = {**contract, "status": "unchanged", "applied": False, "verified": False}
    if src == dst:
        return path, evidence

    try:
        import numpy as np
        import onnx
        import onnxruntime as ort
        from onnx import TensorProto, helper

        original = onnx.load(str(path))
        onnx.checker.check_model(original)
        graph = original.graph
        if any(t.data_location == TensorProto.EXTERNAL for t in graph.initializer):
            raise ColorAdapterError("外部权重ONNX暂不支持安全重写，请先导出独立ONNX文件")
        inputs = [value for value in graph.input if value.name not in {x.name for x in graph.initializer}]
        if len(inputs) != 1:
            raise ColorAdapterError("颜色适配仅支持单输入三通道模型，不支持多输入图")
        value = inputs[0]
        shape = value.type.tensor_type.shape.dim
        if len(shape) != 4 or not shape[1].HasField("dim_value") or shape[1].dim_value != 3:
            raise ColorAdapterError("颜色适配要求 NCHW 且通道数固定为3")
        if value.type.tensor_type.elem_type not in (TensorProto.FLOAT, TensorProto.FLOAT16):
            raise ColorAdapterError("颜色适配要求浮点型NCHW输入")
        if any(x.name == value.name for x in graph.output):
            raise ColorAdapterError("输入直连输出的图暂不支持颜色适配")
        if any(attribute.type in (onnx.AttributeProto.GRAPH, onnx.AttributeProto.GRAPHS)
               for node in graph.node for attribute in node.attribute):
            raise ColorAdapterError("包含子图的ONNX需单独核验输入引用")
        names = {i.name for i in graph.input} | {x.name for x in graph.initializer}
        names |= {s for node in graph.node for s in (*node.input, *node.output) if s}
        suffix = 0
        while True:
            alias = f"__cl_color_rgb_{suffix}"
            indices = f"__cl_color_indices_{suffix}"
            if alias not in names and indices not in names:
                break
            suffix += 1
        references = 0
        for node in graph.node:
            for index, name in enumerate(node.input):
                if name == value.name:
                    node.input[index] = alias
                    references += 1
        if not references:
            raise ColorAdapterError("模型输入没有可追踪的计算节点")
        graph.initializer.append(helper.make_tensor(indices, TensorProto.INT64, [3], [2, 1, 0]))
        graph.node.insert(0, helper.make_node("Gather", [value.name, indices], [alias],
                                             axis=1, name="ChangLianInputColorAdapter"))
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        adapted = output_dir / (path.stem + "_input_" + dst + ".onnx")
        if adapted.resolve() == path.resolve():
            raise ColorAdapterError("禁止覆盖原始ONNX")
        onnx.checker.check_model(original)
        onnx.save(original, str(adapted))

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        reference = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        converted = ort.InferenceSession(str(adapted), sess_options=options, providers=["CPUExecutionProvider"])
        in_ref, in_new = reference.get_inputs(), converted.get_inputs()
        if len(in_ref) != 1 or len(in_new) != 1 or in_ref[0].name != in_new[0].name:
            raise ColorAdapterError("颜色适配改变了输入接口")
        expected = []
        for idx, dim in enumerate(in_ref[0].shape):
            if isinstance(dim, int) and dim > 0:
                expected.append(dim)
            elif idx == 0:
                expected.append(1)
            elif idx == 1:
                expected.append(3)
            else:
                raise ColorAdapterError("动态宽高无法生成确定性验证输入")
        if expected[0] > 4 or expected[2] * expected[3] > 2048 * 2048:
            raise ColorAdapterError("颜色适配数值验证超出安全尺寸范围")
        rng = np.random.default_rng(20261027)
        dtype = np.float16 if in_ref[0].type == "tensor(float16)" else np.float32
        rgb = rng.random(expected).astype(dtype)
        swapped = np.ascontiguousarray(rgb[:, ::-1, :, :])
        baseline = reference.run(None, {in_ref[0].name: rgb})
        outputs = converted.run(None, {in_new[0].name: swapped})
        if len(baseline) != len(outputs) or any(
            a.shape != b.shape or not np.allclose(a, b, rtol=2e-4, atol=2e-4, equal_nan=False)
            for a, b in zip(baseline, outputs)
        ):
            raise ColorAdapterError("颜色适配数值等价校验失败")
        evidence.update(status="verified", applied=True, verified=True,
                        method="onnx_gather_channel_axis_1", check="onnxruntime_equivalence")
        return adapted, evidence
    except ColorAdapterError:
        raise
    except Exception as error:
        raise ColorAdapterError(f"ONNX颜色适配失败：{error}") from error
