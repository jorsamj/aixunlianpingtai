from platform_core.labels import (
    active_label_options,
    label_governance_fence,
    labels_match_any,
)


LABELS = [
    {"class_id": 0, "code": "fire", "display_name_zh": "明火", "status": "active"},
    {"class_id": 1, "code": "smoke", "display_name_zh": "烟雾", "status": "active"},
    {"class_id": 2, "code": "helmet", "display_name_zh": "安全帽", "status": "disabled"},
    {"class_id": 3, "code": "legacy", "display_name_zh": "旧标签", "status": "active", "active": False},
]


def test_only_active_labels_are_selectable():
    assert [item["code"] for item in active_label_options(LABELS)] == ["fire", "smoke"]


def test_material_filter_uses_or_logic():
    assert labels_match_any(["fire"], {"smoke", "fire"})
    assert labels_match_any(["smoke"], {"smoke", "fire"})
    assert not labels_match_any(["person"], {"smoke", "fire"})




def test_label_governance_fence_is_reentrant_in_same_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with label_governance_fence(project):
        with label_governance_fence(project):
            assert True
