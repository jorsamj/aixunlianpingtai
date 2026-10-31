"""TQ-05: class-aware metrics must not invent or mislabel YOLO AP evidence."""
from types import SimpleNamespace

import numpy as np

from train_worker import build_report_from_metrics


def _stub(ids, *, p, r, ap50, ap, maps, names=None):
    box = SimpleNamespace(
        ap_class_index=np.asarray(ids, dtype=int),
        p=np.asarray(p, dtype=float),
        r=np.asarray(r, dtype=float),
        ap50=np.asarray(ap50, dtype=float),
        ap=np.asarray(ap, dtype=float),
        maps=np.asarray(maps, dtype=float),
    )
    return SimpleNamespace(
        box=box,
        names=names or {0: "smoke", 1: "helmet", 2: "fire"},
        results_dict={"metrics/mAP50(B)": 0.935},
    )


def test_sparse_classes_map_to_real_ids_and_never_report_unmeasured_class():
    metrics = _stub(
        [0, 2], p=[.61, .98], r=[.64, .95], ap50=[.71, .97],
        ap=[.42, .83], maps=[.42, .625, .83],
    )
    result = build_report_from_metrics(metrics)
    assert [item["class_id"] for item in result["per_class"]] == [0, 2]
    assert [item["label"] for item in result["per_class"]] == ["smoke", "fire"]
    assert [item["map50_95"] for item in result["per_class"]] == [.42, .83]
    assert result["per_class"][0]["precision"] == .61
    assert result["per_class"][1]["recall"] == .95
    assert "helmet" not in [item["label"] for item in result["per_class"]]
    assert result["weak_labels"] == ["smoke"]
    assert result["metrics"]["metrics/mAP50(B)"] == .935
    assert "report_error" not in result


def test_single_sparse_class_has_correct_name_and_ap50_95():
    metrics = _stub([2], p=[.99], r=[.9], ap50=[.97], ap=[.81],
                    maps=[.81, .81, .81])
    result = build_report_from_metrics(metrics)
    assert len(result["per_class"]) == 1
    assert result["per_class"][0] == {
        "class_id": 2, "label": "fire", "precision": .99,
        "recall": .9, "map50": .97, "map50_95": .81,
    }


def test_no_measurements_does_not_fabricate_map_from_dense_maps():
    metrics = _stub([], p=[], r=[], ap50=[], ap=[], maps=[.94, .94, .94])
    result = build_report_from_metrics(metrics)
    assert result["per_class"] == []
    assert result["weak_labels"] == []
    assert "report_error" not in result


def test_missing_class_ids_cannot_claim_per_class_accuracy():
    metrics = _stub([], p=[.8], r=[.85], ap50=[.9], ap=[.6],
                    maps=[.6, .6, .6])
    result = build_report_from_metrics(metrics)
    assert result["per_class"] == []
    assert result["weak_labels"] == []
    assert "ap_class_index" in result["report_error"]
    assert result["metrics"]["metrics/mAP50(B)"] == .935


def test_inconsistent_lengths_and_duplicate_class_ids_fail_closed():
    for ids, precision in (([0, 2], [.1]), ([2, 2], [.8, .7])):
        result = build_report_from_metrics(_stub(
            ids, p=precision, r=[.6, .8], ap50=[.7, .9],
            ap=[.45, .55], maps=[.45, .5, .55],
        ))
        assert result["per_class"] == []
        assert result["weak_labels"] == []
        assert "report_error" in result


def test_class_id_indexed_maps_is_only_fallback_when_ap_unavailable():
    metrics = _stub([0, 2], p=[.9, .8], r=[.8, .7],
                    ap50=[.7, .6], ap=[], maps=[.2, .55, .4])
    result = build_report_from_metrics(metrics)
    assert [row["map50_95"] for row in result["per_class"]] == [.2, .4]
