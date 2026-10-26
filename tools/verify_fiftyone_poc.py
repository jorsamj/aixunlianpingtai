"""Real-engine PoC; run ONLY using the separate optional Python environment."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform_core" / "smart_material_audit"))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-prediction-fixture", action="store_true")
    parser.add_argument("--identical-fixture", action="store_true")
    args = parser.parse_args()
    from PIL import Image, ImageDraw
    from engine import analyze

    with tempfile.TemporaryDirectory(prefix="smart-audit-poc-") as temp:
        root = Path(temp)
        first = Image.new("RGB", (96, 72), "navy")
        ImageDraw.Draw(first).rectangle((10, 8, 50, 55), fill="orange")
        first.save(root / "original.png")
        first.resize((192, 144)).save(root / "resized.jpg", quality=95)
        Image.new("RGB", (96, 72), "green").save(root / "different.png")
        names = ("original.png", "resized.jpg", "different.png")
        if args.identical_fixture:
            names = tuple(f"same-{i}.png" for i in range(4))
            for name in names:
                first.save(root/name)
            for name in ("original.png", "resized.jpg", "different.png"):
                (root/name).unlink()
        records = []
        for index, name in enumerate(names):
            path = root / name
            records.append(dict(image_id=f"image-{index}", path=str(path),
                content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                frozen_split="train" if index == 0 else "test"))
        if args.with_prediction_fixture:
            # Controlled API fixture only; not outputs of a real trained model.
            for row in records:
                with Image.open(row["path"]) as source:
                    width,height=source.size
                row.update(gt_boxes=[], pred_boxes=[dict(label="orange", x1=10, y1=8, x2=40, y2=50, confidence=.99)],
                    annotation_state="confirmed_empty", annotation_digest="b"*64,
                    prediction_evidence=dict(evaluation_id="c"*64, model_sha256="d"*64,
                        benchmark_scope_id="e"*64, image_content_sha256=row["content_sha256"],image_width=width,image_height=height))
        before = {row["image_id"]: Path(row["path"]).read_bytes() for row in records}
        result = analyze(dict(project_id="isolated", task_id="poc", feature="hog-color-v1",
            images=records, threshold=.4, frozen_split_evidence="a" * 64), root / "engine")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
        assert result["scanned"] == len(names) and result["failed"] == 0
        assert any(set(pair["image_ids"]) == {"image-0", "image-1"} for pair in result["similar_pairs"])
        assert result["checks"]["leakage"]["status"] == "completed"
        if args.with_prediction_fixture:
            assert result["checks"]["mistakenness"]["status"] == "completed"
            assert len(result["annotation_candidates"]) == len(names)
            assert all(row["possible_missing"] == 1 for row in result["annotation_candidates"])
        else:
            assert result["checks"]["mistakenness"]["status"] == "not_checked"
        if args.identical_fixture:
            assert all(row["value"] is None and row["status"] == "not_checked" for row in result["uniqueness"])
        assert result["database_cleaned"] is True
        assert all(Path(row["path"]).read_bytes() == before[row["image_id"]] for row in records)
        assert sorted(path.name for path in root.glob("*.*")) == sorted(names)


if __name__ == "__main__":
    main()
