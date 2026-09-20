import app as app_module

def test_label_aliases_are_editable_and_canonical_conflicts_fail_closed(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-api",
        "labels": [
            {"code": "helmet", "display_name": "安全头盔"},
            {"code": "person", "display_name": "人员"},
        ],
    }).json()

    updated = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1", "toukui2", "toukui1"],
        },
    )
    assert updated.status_code == 200, updated.text
    helmet = updated.json()["items"][0]
    assert helmet["aliases"] == ["toukui1", "toukui2"]

    conflict = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["person"],
        },
    )
    assert conflict.status_code == 409
    assert "正式标签身份冲突" in conflict.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert labels[0]["aliases"] == ["toukui1", "toukui2"]
    assert labels[1]["aliases"] == []


def test_confirmed_alias_learning_skips_only_canonical_conflicts(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-mixed-confirmation",
        "labels": [
            {"code": "helmet", "display_name": "安全头盔"},
            {"code": "person", "display_name": "人员"},
        ],
    }).json()

    remembered = app_module.remember_project_label_aliases(
        project["id"],
        [
            {"class_id": "0", "name": "toukui1"},
            {"class_id": "1", "name": "person"},
            {"class_id": "2", "name": "toukui2"},
        ],
        {"0": "helmet", "1": "helmet", "2": "helmet"},
    )
    assert remembered["helmet"] == ["toukui1", "toukui2"]

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    assert helmet["aliases"] == ["toukui1", "toukui2"]
    assert "person" not in helmet["aliases"]


def test_new_canonical_label_retires_matching_alias_from_other_label(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-canonical-promotion",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()

    seeded = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1"],
        },
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["items"][0]["aliases"] == ["toukui1"]

    promoted = client.post(
        f"/api/projects/{project['id']}/labels",
        json={"label": "toukui1", "display_name": "头盔旧类"},
    )
    assert promoted.status_code == 200, promoted.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    canonical = next(row for row in labels if row["code"] == "toukui1")
    assert helmet["aliases"] == []
    assert canonical["code"] == "toukui1"


def test_project_initialization_preserves_aliases_and_prunes_canonical_conflicts(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-project-init",
        "labels": [
            {
                "code": "helmet",
                "display_name": "安全头盔",
                "aliases": ["toukui1", "person"],
            },
            {
                "code": "person",
                "display_name": "人员",
                "aliases": [],
            },
        ],
    }).json()

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    assert helmet["aliases"] == ["toukui1"]
