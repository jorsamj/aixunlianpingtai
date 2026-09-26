import pytest

from platform_core.auto_label import parse_candidate_response
from platform_core.labels import (
    confirmed_alias_updates,
    normalize_label_aliases,
)
from platform_core.storage.import_confirmation import resolve_external_label_mapping


def test_aliases_are_normalized_metadata_not_automatic_mapping_decisions():
    assert normalize_label_aliases(
        ["toukui1", " toukui1 ", "安全头盔", ""]
    ) == ["toukui1", "安全头盔"]


def test_confirmed_alias_updates_only_learn_non_identity_names():
    labels = [
        {"code": "helmet", "display_name": "安全头盔", "status": "active", "aliases": []},
        {"code": "person", "display_name": "人员", "status": "active", "aliases": []},
    ]
    updates = confirmed_alias_updates(
        [
            {"class_id": "0", "name": "toukui1"},
            {"class_id": "1", "name": "toukui2"},
            {"class_id": "2", "name": "helmet"},
        ],
        {"0": "helmet", "1": "helmet", "2": "helmet"},
        labels,
    )
    assert updates == {"helmet": ["toukui1", "toukui2"]}
    assert normalize_label_aliases(["toukui1", "toukui1", " 安全帽 "]) == [
        "toukui1", "安全帽",
    ]


def test_ai_candidate_requires_exact_canonical_code_and_never_resolves_alias():
    with pytest.raises(ValueError, match="标签库之外"):
        parse_candidate_response(
            '{"boxes":[{"label":"toukui1","confidence":0.9,"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}]}',
            width=100,
            height=100,
            label_ids={"helmet": 0},
            label_aliases={"helmet": ["toukui1"]},
        )

    exact = parse_candidate_response(
        '{"boxes":[{"label":"helmet","confidence":0.9,"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}]}',
        width=100,
        height=100,
        label_ids={"helmet": 0},
        label_aliases={"helmet": ["toukui1"]},
    )
    assert exact[0]["label"] == "helmet"
    assert exact[0]["class_id"] == 0


def test_confirmed_alias_updates_do_not_learn_one_name_with_two_targets():
    labels = [
        {"code": "helmet", "display_name": "安全头盔", "status": "active", "aliases": []},
        {"code": "cap", "display_name": "帽子", "status": "active", "aliases": []},
    ]
    updates = confirmed_alias_updates(
        [
            {"class_id": "0", "name": "hat"},
            {"class_id": "1", "name": "hat"},
            {"class_id": "2", "name": "toukui1"},
        ],
        {"0": "helmet", "1": "cap", "2": "helmet"},
        labels,
    )
    assert updates == {"helmet": ["toukui1"]}

def test_import_mapping_rejects_implicit_platform_label_creation():
    labels = [
        {"code": "helmet", "display_name": "安全头盔", "status": "active", "aliases": []},
    ]
    classes = [{"class_id": "0", "name": "toukui1"}]

    with pytest.raises(ValueError, match="不能根据外部标签名隐式创建平台标签"):
        resolve_external_label_mapping(
            classes,
            label_mapping={"0": "helmet_new"},
            create_labels=["helmet_new"],
            labels=labels,
        )

    with pytest.raises(ValueError, match="目标标签必须来自当前有效标签库"):
        resolve_external_label_mapping(
            classes,
            label_mapping={"0": "helmet_new"},
            create_labels=[],
            labels=labels,
        )

