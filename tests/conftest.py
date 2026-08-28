import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="xjalgo-pytest-")).resolve()
os.environ["MC_TRAIN_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["MC_PLATFORM_VERSION"] = "test"

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def seeded_project(client):
    project = client.post(
        "/api/projects",
        json={
            "name": f"test-{uuid.uuid4().hex[:8]}",
            "description": "isolated test project",
            "labels": [
                {"code": "fire", "display_name": "明火"},
                {"code": "smoke", "display_name": "烟雾"},
            ],
        },
    ).json()
    image_bytes = io.BytesIO()
    Image.new("RGB", (128, 128), "white").save(image_bytes, format="JPEG")
    upload = client.post(
        f"/api/projects/{project['id']}/images",
        files=[("files", ("seed.jpg", image_bytes.getvalue(), "image/jpeg"))],
        data={"dataset_id": "default"},
    )
    upload.raise_for_status()
    return project["id"], upload.json()["uploaded"][0]

