from types import SimpleNamespace

import train_worker


def _args(tmp_path):
    return SimpleNamespace(
        data=str(tmp_path / "bundle" / "data.yaml"),
        ai_eval_samples=20,
        seed=7,
        job_id="job-1",
        epochs=50,
        ai_extra_epochs=20,
    )


def _fake_metrics(_trainer):
    return [
        {"label": "fire", "precision": 0.61, "recall": 0.42, "map50": 0.55},
        {"label": "smoke", "precision": 0.90, "recall": 0.88, "map50": 0.86},
    ]


def test_legacy_supplement_action_becomes_next_task_recommendation(tmp_path, monkeypatch):
    monkeypatch.setattr(train_worker, "_trainer_per_class", _fake_metrics)
    monkeypatch.setattr(
        train_worker,
        "_ai_eval_contact_sheet",
        lambda *args, **kwargs: (tmp_path / "sheet.jpg", ["sample.jpg"]),
    )
    monkeypatch.setattr(
        train_worker,
        "_call_ai_model",
        lambda *args, **kwargs: {
            "action": "supplement_and_retrain",
            "reason": "fire 召回率偏低，需要更多同类素材",
            "target_labels": ["fire"],
            "extra_epochs": 30,
        },
    )

    decision = train_worker._run_ai_intervention(
        {}, SimpleNamespace(metrics={"metrics/mAP50(B)": 0.55}), _args(tmp_path), 10, tmp_path
    )

    assert decision["action"] == "recommend_supplement"
    assert decision["requires_new_training_task"] is True
    assert decision["snapshot_immutable"] is True
    assert decision["target_labels"] == ["fire"]
    assert "unused_labeled_data" not in decision["summary"]
    assert decision["summary"]["snapshot_policy"] == {
        "immutable": True,
        "allowed_current_task_actions": ["continue", "extend_epochs"],
        "supplement_requires_new_training_task": True,
    }


def test_extend_epochs_remains_same_snapshot_action(tmp_path, monkeypatch):
    monkeypatch.setattr(train_worker, "_trainer_per_class", _fake_metrics)
    monkeypatch.setattr(
        train_worker,
        "_ai_eval_contact_sheet",
        lambda *args, **kwargs: (tmp_path / "sheet.jpg", ["sample.jpg"]),
    )
    monkeypatch.setattr(
        train_worker,
        "_call_ai_model",
        lambda *args, **kwargs: {
            "action": "extend_epochs",
            "reason": "仍有收敛空间",
            "target_labels": ["fire"],
            "extra_epochs": 15,
        },
    )

    decision = train_worker._run_ai_intervention(
        {}, SimpleNamespace(metrics={"metrics/mAP50(B)": 0.55}), _args(tmp_path), 10, tmp_path
    )

    assert decision["action"] == "extend_epochs"
    assert decision["requires_new_training_task"] is False
    assert decision["snapshot_immutable"] is True
    assert decision["extra_epochs"] == 15


def test_training_worker_contains_no_mutable_supplement_helper():
    source = open(train_worker.__file__, "r", encoding="utf-8").read()

    assert "def _supplement_snapshot" not in source
    assert "def _master_unused_counts" not in source
    assert 'img["split"]="train"' not in source
