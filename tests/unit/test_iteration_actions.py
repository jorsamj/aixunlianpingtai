from platform_core.iteration_actions import build_confirmed_iteration_action, training_action_context

def _version(decision="continue_training"):
    action = {"continue_training":"continue_training","needs_data":"supplement_data",
              "ready_for_business_validation":"business_validation","review_required":"manual_review"}[decision]
    return {
        "id":"v1","dataset_revision_id":"d"*64,"snapshot_id":"snapshot-v3",
        "evaluation":{"evaluation_id":"e"*64,"dataset_revision_id":"d"*64,
                      "snapshot_id":"snapshot-v3","model_sha256":"a"*64,
                      "error_samples":[{"image":"a.jpg","fp_count":1,"fn_count":2}]},
        "iteration_decision":{"decision_id":"c"*64,"evaluation_id":"e"*64,
                              "decision":decision,"weak_labels":["smoke"] if decision=="needs_data" else [],
                              "automatic_execution":False,"requires_confirmation":True},
    }, action

def test_continue_training_action_is_deterministic_and_lineage_bound():
    version, action = _version()
    first=build_confirmed_iteration_action(algorithm_id="a1",version=version,requested_action=action,decision_id="c"*64,confirmed_at="now")
    second=build_confirmed_iteration_action(algorithm_id="a1",version=version,requested_action=action,decision_id="c"*64,confirmed_at="later")
    assert first["action_id"]==second["action_id"]
    assert first["requires_user_submit"] is True
    assert first["automatic_execution"] is False
    assert first["training_draft"]["task_id"] == f"train_{first['action_id'][:24]}"
    assert training_action_context(first)["version_id"]=="v1"

def test_needs_data_action_carries_draft_without_mutation():
    version, action=_version("needs_data")
    result=build_confirmed_iteration_action(algorithm_id="a1",version=version,requested_action=action,decision_id="c"*64,confirmed_at="now")
    assert result["data_draft"]["weak_labels"]==["smoke"]
    assert result["data_draft"]["problem_samples"][0]["image"]=="a.jpg"
    assert result["automatic_execution"] is False

def test_confirmed_action_rejects_stale_or_wrong_action():
    import pytest
    version,_=_version()
    with pytest.raises(ValueError,match="decision changed"):
        build_confirmed_iteration_action(algorithm_id="a1",version=version,requested_action="continue_training",decision_id="b"*64,confirmed_at="now")
    with pytest.raises(ValueError,match="does not match"):
        build_confirmed_iteration_action(algorithm_id="a1",version=version,requested_action="supplement_data",decision_id="c"*64,confirmed_at="now")


def test_manual_review_action_carries_durable_product_entry():
    version, action = _version("review_required")
    version["iteration_decision"]["reason_codes"] = ["evaluation_missing", "manual_check"]
    version["iteration_decision"]["recommended_actions"] = [
        "configure_independent_test_split", "review_evaluation_configuration",
    ]
    result = build_confirmed_iteration_action(
        algorithm_id="a1", version=version, requested_action=action,
        decision_id="c" * 64, confirmed_at="now",
    )
    assert result["action"] == "manual_review"
    assert result["review_entry"]["decision_id"] == "c" * 64
    assert result["review_entry"]["evaluation_id"] == "e" * 64
    assert result["review_entry"]["dataset_revision_id"] == "d" * 64
    assert result["review_entry"]["snapshot_id"] == "snapshot-v3"
    assert result["review_entry"]["reason_codes"] == ["evaluation_missing", "manual_check"]
    assert result["review_entry"]["recommended_actions"] == [
        "configure_independent_test_split", "review_evaluation_configuration",
    ]


def test_business_validation_entry_carries_frozen_source_identity():
    version, action = _version("ready_for_business_validation")
    result = build_confirmed_iteration_action(
        algorithm_id="a1", version=version, requested_action=action,
        decision_id="c" * 64, confirmed_at="now",
    )
    entry = result["validation_entry"]
    assert entry["decision_id"] == "c" * 64
    assert entry["evaluation_id"] == "e" * 64
    assert entry["dataset_revision_id"] == "d" * 64
    assert entry["snapshot_id"] == "snapshot-v3"
    assert entry["model_sha256"] == "a" * 64
