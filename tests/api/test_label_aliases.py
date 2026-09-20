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
