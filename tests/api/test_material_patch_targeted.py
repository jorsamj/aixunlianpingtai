import io
import uuid

from PIL import Image

import app as platform_app


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(output, format="PNG")
    return output.getvalue()


def test_single_image_dataset_patch_is_targeted_and_revisioned(client, seeded_project):
    project_id, image = seeded_project
    dataset = client.post(
        f"/api/projects/{project_id}/datasets",
        json={"name": f"target-{uuid.uuid4().hex[:6]}", "description": ""},
    ).json()
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("second.png", _png(), "image/png"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    store = platform_app.material_store(project_id)
    before = store.read()
    before_second = next(row for row in before.rows if row["id"] == second["id"])
    before_target = next(row for row in before.rows if row["id"] == image["id"])

    response = client.patch(
        f"/api/v12/projects/{project_id}/images/{image['id']}",
        json={"dataset_id": dataset["id"]},
    )
    assert response.status_code == 200, response.text
    after = store.read()
    changed = next(row for row in after.rows if row["id"] == image["id"])
    untouched = next(row for row in after.rows if row["id"] == second["id"])
    assert changed["dataset_id"] == dataset["id"]
    assert changed["split"] == before_target.get("split", "unassigned")
    assert untouched == before_second
    assert after.revision == before.revision + 1

    split_response = client.patch(
        f"/api/v12/projects/{project_id}/images/{image['id']}",
        json={"split": "train"},
    )
    assert split_response.status_code == 200, split_response.text
    assert store.get(image["id"])["split"] == "train"
    assert store.get(image["id"])["dataset_id"] == dataset["id"]

    assert client.patch(
        f"/api/v12/projects/{project_id}/images/missing-image",
        json={"dataset_id": dataset["id"]},
    ).status_code == 404
    assert client.patch(
        f"/api/v12/projects/{project_id}/images/{image['id']}",
        json={"split": "not-a-split"},
    ).status_code == 400
