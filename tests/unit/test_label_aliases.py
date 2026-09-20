import pytest

from platform_core.auto_label import parse_candidate_response
from platform_core.labels import (
    confirmed_alias_updates,
    normalize_label_aliases,
    suggest_label_code,
)


def test_alias_suggestion_uses_unique_alias_but_canonical_identity_wins():
    labels = [
        {
            "code": "helmet",
            "display_name": "安全头盔",
            "status": "active",
            "aliases": ["toukui1", "person"],
        },
        {
            "code": "person",
            "display_name": "人员",
            "status": "active",
            "aliases": [],
        },
    ]
    assert suggest_label_code("toukui1", labels) == "helmet"
    assert suggest_label_code("安全头盔", labels) == "helmet"
    assert suggest_label_code("person", labels) == "person"


def test_ambiguous_alias_never_auto_selects():
    labels = [
        {"code": "helmet", "status": "active", "aliases": ["hat"]},
        {"code": "cap", "status": "active", "aliases": ["hat"]},
    ]
    assert suggest_label_code("hat", labels) is None


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


def test_ai_alias_resolution_is_exact_and_does_not_use_substring_matching():
    exact = parse_candidate_response(
        '{"boxes":[{"label":"toukui1","confidence":0.9,"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}]}',
        width=100,
        height=100,
        label_ids={"helmet": 0},
        label_aliases={"helmet": ["toukui1"]},
    )
    assert exact[0]["label"] == "helmet"
    assert exact[0]["class_id"] == 0

    with pytest.raises(ValueError, match="标签库之外"):
        parse_candidate_response(
            '{"boxes":[{"label":"toukui1_extra","confidence":0.9,"x1":0.1,"y1":0.1,"x2":0.5,"y2":0.5}]}',
            width=100,
            height=100,
            label_ids={"helmet": 0},
            label_aliases={"helmet": ["toukui1"]},
        )


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
