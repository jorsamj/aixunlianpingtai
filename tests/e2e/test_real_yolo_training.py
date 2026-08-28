import io
import time
from pathlib import Path

from PIL import Image, ImageDraw


TERMINAL_STATUSES = {"done", "completed", "finished", "failed", "stopped"}


def _training_image(index: int) -> bytes:
    image = Image.new("RGB", (160, 160), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    color = (220, 55, 35) if index % 2 == 0 else (70, 90, 210)
    draw.rectangle((30, 30, 125, 125), fill=color, outline=(20, 20, 20), width=3)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=95)
    return stream.getvalue()


def _local_yolo11_checkpoint() -> str:
    import app as app_module

    roots = [Path(app_module.BASE_DIR), *Path(app_module.BASE_DIR).parents]
    checkpoint = next((root / "yolo11n.pt" for root in roots if (root / "yolo11n.pt").is_file()), None)
    return str(checkpoint) if checkpoint else "yolo11n.pt"


def test_real_cpu_training_produces_verified_version_and_report(client):
    project = client.post(
        "/api/projects",
        json={
            "name": f"real-yolo-{time.time_ns()}",
            "description": "one epoch real CPU training proof",
            "labels": [
                {"code": "fire", "display_name": "明火"},
                {"code": "smoke", "display_name": "烟雾"},
            ],
        },
    ).json()
    project_id = project["id"]
    splits = ["train", "train", "val", "test"]
    images = []
    for index, split in enumerate(splits):
        upload = client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", (f"sample-{index}.jpg", _training_image(index), "image/jpeg"))],
            data={"dataset_id": "default"},
        )
        upload.raise_for_status()
        image = upload.json()["uploaded"][0]
        label = "fire" if index % 2 == 0 else "smoke"
        annotation = client.post(
            f"/api/projects/{project_id}/annotations/{image['id']}",
            json={"boxes": [{"class_id": index % 2, "label": label, "x1": 30, "y1": 30, "x2": 125, "y2": 125}]},
        )
        annotation.raise_for_status()
        split_response = client.patch(
            f"/api/v12/projects/{project_id}/images/{image['id']}", json={"split": split}
        )
        split_response.raise_for_status()
        images.append(image)

    algorithm_response = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={
            "name": "真实训练烟火算法",
            "industry": "训练回归",
            "algorithm_type": "yolo_ultralytics",
            "remark": "",
        },
    )
    algorithm_response.raise_for_status()
    algorithm = algorithm_response.json()["algorithm"]

    start = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": algorithm["id"],
            "model": _local_yolo11_checkpoint(),
            "epochs": 1,
            "imgsz": 128,
            "batch": 2,
            "device": "cpu",
            "workers": 0,
            "patience": 1,
            "amp": False,
            "mosaic": 0.0,
            "close_mosaic": 0,
            "seed": 7,
            "train_image_ids": [images[0]["id"], images[1]["id"]],
            "val_image_ids": [images[2]["id"]],
        },
    )
    assert start.status_code == 200, start.text
    job_id = start.json()["job"]["id"]

    deadline = time.monotonic() + 300
    job = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/projects/{project_id}/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job.get("status") in TERMINAL_STATUSES:
            break
        time.sleep(0.5)

    log = client.get(f"/api/projects/{project_id}/jobs/{job_id}/log").text
    assert job.get("status") in {"done", "completed", "finished"}, log[-12_000:]
    artifact = job.get("best_path") or job.get("last_path")
    assert artifact and Path(artifact).is_file(), job
    assert job.get("artifact_verified") is True
    assert job.get("auto_version_id"), job

    version_report = client.get(f"/api/v44/projects/{project_id}/jobs/{job_id}/report")
    version_report.raise_for_status()
    assert version_report.json()["report_type"] == "version"
