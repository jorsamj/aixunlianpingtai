"""Safe, order-only repair for flat ONNX computation graphs.

Never changes tensor edges, operator attributes, weights or model metadata.
Control-flow/sparse/external-data graphs are deliberately excluded from repair.
"""
from __future__ import annotations

import heapq
import os
import uuid
from pathlib import Path
from typing import Any

from .conversion import ConversionError


def _invalid(message: str) -> ConversionError:
    return ConversionError(
        "ONNX_GRAPH_TOPOLOGY_INVALID", message,
        solution="请检查 ONNX 导出器的节点依赖、张量生产者和子图结构；无法证明安全时不自动修改。",
    )


def _repair_failed(message: str) -> ConversionError:
    return ConversionError(
        "ONNX_GRAPH_REPAIR_FAILED", message,
        solution="请检查 ONNX 图结构及导出环境；保留原始导出文件，不要跳过 Checker 和 Runtime 验证。",
    )


def _safe_to_reorder(model: Any, onnx: Any) -> None:
    graph = model.graph
    if graph.sparse_initializer:
        raise _invalid("模型包含稀疏权重，不支持自动调整节点顺序")
    if any(t.data_location == onnx.TensorProto.EXTERNAL for t in graph.initializer):
        raise _invalid("模型包含外部权重，不支持自动调整节点顺序")
    graph_types = (onnx.AttributeProto.GRAPH, onnx.AttributeProto.GRAPHS)
    for node in graph.node:
        for attribute in node.attribute:
            if attribute.type in graph_types:
                raise _invalid("模型包含控制流或嵌套子图，无法证明顶层重排对捕获变量安全")
            tensors = []
            if attribute.type == onnx.AttributeProto.TENSOR:
                tensors = [attribute.t]
            elif attribute.type == onnx.AttributeProto.TENSORS:
                tensors = attribute.tensors
            if any(t.data_location == onnx.TensorProto.EXTERNAL for t in tensors):
                raise _invalid("模型节点属性引用外部权重，不支持自动重排")


def repair_onnx_topology(
    source: Path, output_dir: Path
) -> tuple[Path, dict[str, Any]]:
    """Return original path for valid graphs; write a separate ONNX only for a proven reorder.

    Caller MUST still run ONNX Runtime inference before registering an artifact.
    """
    source = Path(source)
    try:
        import onnx
    except ImportError as error:
        raise _repair_failed("无法导入 onnx，不能执行结构校验") from error
    try:
        model = onnx.load(str(source), load_external_data=False)
    except Exception as error:
        raise _invalid(f"无法读取 ONNX 模型：{error}") from error

    graph = model.graph
    available = {value.name for value in graph.input}
    available.update(value.name for value in graph.initializer)
    producer: dict[str, int] = {}
    for position, node in enumerate(graph.node):
        for name in node.output:
            if not name:
                continue
            if name in available or name in producer:
                raise _invalid(f"重复张量生产者或违反 SSA：{name}")
            producer[name] = position

    dependencies: list[set[int]] = []
    for position, node in enumerate(graph.node):
        parents: set[int] = set()
        for name in node.input:
            if not name:
                continue  # ONNX optional input
            if name in available:
                continue
            if name not in producer:
                raise _invalid(f"节点 {node.name or node.op_type} 的输入缺少生产者：{name}")
            parents.add(producer[name])
        dependencies.append(parents)
    for output in graph.output:
        if output.name not in available and output.name not in producer:
            raise _invalid(f"图输出缺少生产者：{output.name}")

    followers: list[list[int]] = [[] for _ in graph.node]
    pending = [len(parents) for parents in dependencies]
    for index, parents in enumerate(dependencies):
        for parent in parents:
            followers[parent].append(index)
    ready = list(index for index, count in enumerate(pending) if count == 0)
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        index = heapq.heappop(ready)
        order.append(index)
        for follower in followers[index]:
            pending[follower] -= 1
            if pending[follower] == 0:
                heapq.heappush(ready, follower)
    if len(order) != len(graph.node):
        raise _invalid("ONNX 图存在循环依赖，无法安全拓扑排序")

    evidence: dict[str, Any] = {
        "status": "unchanged", "applied": False,
        "node_count": len(order), "moved_nodes": 0,
        "checker": "passed", "runtime": "pending",
    }
    if all(position == index for position, index in enumerate(order)):
        try:
            onnx.checker.check_model(model)
        except Exception as error:
            raise _invalid(f"ONNX Checker 校验失败（并非纯节点顺序问题）：{error}") from error
        return source, evidence

    _safe_to_reorder(model, onnx)
    # Serialize original nodes, preserving every attribute, edge and initializer.
    nodes = [node.SerializeToString() for node in graph.node]
    moved = sum(index != position for position, index in enumerate(order))
    del graph.node[:]
    for index in order:
        graph.node.add().ParseFromString(nodes[index])
    if [node.SerializeToString() for node in graph.node] != [nodes[index] for index in order]:
        raise _repair_failed("节点内容在重排过程中发生变化，已拒绝写入")
    try:
        onnx.checker.check_model(model)
    except Exception as error:
        raise _repair_failed(f"重排后 ONNX Checker 仍未通过：{error}") from error

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{source.stem}_topology_sorted.onnx"
    if target.resolve() == source.resolve():
        raise _repair_failed("修复产物不能覆盖原始导出模型")
    temporary = output_dir / f".{target.stem}.{uuid.uuid4().hex}.tmp.onnx"
    try:
        onnx.save(model, str(temporary))
        onnx.checker.check_model(str(temporary))
        os.replace(temporary, target)
    except Exception as error:
        raise _repair_failed(f"无法保存或复核拓扑修复副本：{error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    evidence.update(status="reordered", applied=True, moved_nodes=moved)
    return target, evidence
