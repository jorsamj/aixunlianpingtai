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
