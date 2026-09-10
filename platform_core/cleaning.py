"""Shared v47 image checks, independent of HTTP and material collection loading."""
from __future__ import annotations

import math
from pathlib import Path

from .storage.cache import file_sha256


DEFAULT_OPTIONS = {
    "exact_duplicate": True, "near_duplicate": True, "near_duplicate_hamming": 5,
    "min_width": 320, "min_height": 240, "max_width": 10000, "max_height": 10000,
    "blur_check": True, "blur_min_laplacian": 45.0,
    "brightness_check": False, "brightness_min": 15.0, "brightness_max": 245.0,
    "corrupt_check": True,
}


class ImageDecodeError(ValueError):
    """Image bytes failed the real decoder, as distinct from storage access."""


def clean_options(value):
    unknown = set(value) - set(DEFAULT_OPTIONS) - {"task_name"}
    if unknown:
        raise ValueError("unsupported cleaning options: " + ", ".join(sorted(unknown)))
    options = {**DEFAULT_OPTIONS, **value}
    for key, default in DEFAULT_OPTIONS.items():
        candidate = options[key]
        if isinstance(default, bool):
            if not isinstance(candidate, bool):
                raise ValueError(f"{key} must be boolean")
        elif isinstance(candidate, bool) or not isinstance(candidate, (int, float)) or not math.isfinite(candidate) or candidate < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
        elif isinstance(default, int) and int(candidate) != candidate:
            raise ValueError(f"{key} must be an integer")
    if options["near_duplicate_hamming"] > 20:
        raise ValueError("near_duplicate_hamming must be between 0 and 20")
    for low, high in (("min_width", "max_width"), ("min_height", "max_height"), ("brightness_min", "brightness_max")):
        if options[high] and options[low] > options[high]:
            raise ValueError(f"{low} must not exceed {high}")
    if options["brightness_max"] > 255:
        raise ValueError("brightness_max must not exceed 255")
    return options


def dhash(path: Path) -> int:
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert("L").resize((9, 8))
        vals = list(g.getdata())
    out = 0
    for y in range(8):
        row = vals[y * 9:(y + 1) * 9]
        for x in range(8):
            out = (out << 1) | (1 if row[x] > row[x + 1] else 0)
    return out


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def image_metrics(path: Path, *, require_blur: bool = False) -> dict:
    """Original Laplacian/brightness/entropy/dHash checks with honest fallback.

    Pillow validates corruption first. A missing blur engine cannot produce a
    fabricated zero score; Workers fail the item when blur was requested.
    """
    from PIL import Image, ImageStat, UnidentifiedImageError
    exact = file_sha256(path)
    try:
        with Image.open(path) as im:
            im.verify()
    except (PermissionError, FileNotFoundError):
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        raise ImageDecodeError(str(error)) from error
    try:
        import cv2
        import numpy as np
        # imdecode supports Windows Unicode paths, unlike some cv2.imread builds.
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("OpenCV无法解码图片")
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
        prob = hist / max(1.0, float(hist.sum()))
        nz = prob[prob > 0]
        entropy = float(-(nz * np.log2(nz)).sum()) if len(nz) else 0.0
    except Exception as error:
        if require_blur:
            raise RuntimeError("CLEAN_BLUR_ENGINE_UNAVAILABLE: " + str(error)) from error
        with Image.open(path) as im:
            w, h = im.size
            brightness = float(ImageStat.Stat(im.convert("L")).mean[0])
        blur_score = None
        entropy = None
    return {"width": int(w), "height": int(h), "sha256": exact, "dhash": dhash(path),
            "blur_score": round(blur_score, 3) if blur_score is not None else None,
            "brightness": round(brightness, 3),
            "entropy": round(entropy, 3) if entropy is not None else None}


def metric_issues(metrics, options, image_id, index):
    """Shared rule evaluation; index supplies bounded candidate iteration."""
    issues = []
    if options.get("exact_duplicate"):
        previous = index.exact(metrics["sha256"], image_id)
        if previous:
            issues.append({"code": "exact_duplicate", "name": "重复图", "detail": "与另一张图片完全相同", "related_image_id": previous})
    near_indexed = options.get("near_duplicate") and not any(x["code"] == "exact_duplicate" for x in issues)
    if near_indexed:
        dh = int(metrics["dhash"])
        threshold = int(options.get("near_duplicate_hamming", 5))
        best = None
        for old_hash, old_id in index.candidates(dh, image_id):
            distance = hamming(dh, old_hash)
            if distance <= threshold and (best is None or (distance, old_id) < best):
                best = (distance, old_id)
        if best:
            issues.append({"code": "near_duplicate", "name": "近似重复", "detail": f"感知哈希距离 {best[0]}", "related_image_id": best[1]})
    w, h = int(metrics["width"]), int(metrics["height"])
    if w < int(options.get("min_width") or 0) or h < int(options.get("min_height") or 0):
        issues.append({"code": "resolution_low", "name": "分辨率偏低", "detail": f"{w}×{h}"})
    if (options.get("max_width") and w > int(options["max_width"])) or (options.get("max_height") and h > int(options["max_height"])):
        issues.append({"code": "resolution_high", "name": "分辨率过高", "detail": f"{w}×{h}"})
    if options.get("blur_check"):
        if metrics.get("blur_score") is None:
            raise RuntimeError("CLEAN_BLUR_ENGINE_UNAVAILABLE: no real blur score")
        if float(metrics["blur_score"]) < float(options.get("blur_min_laplacian", 45)):
            issues.append({"code": "blur", "name": "疑似模糊", "detail": f"清晰度 {metrics['blur_score']}"})
    if options.get("brightness_check"):
        b = float(metrics["brightness"])
        if b < float(options.get("brightness_min", 15)):
            issues.append({"code": "too_dark", "name": "疑似过暗", "detail": f"平均亮度 {b:.1f}"})
        if b > float(options.get("brightness_max", 245)):
            issues.append({"code": "too_bright", "name": "疑似过亮", "detail": f"平均亮度 {b:.1f}"})
    return issues, bool(near_indexed)


class MemoryHashIndex:
    """Compatibility index for the legacy task; Workers use DurableHashIndex."""
    def __init__(self):
        self.hashes, self.bands = {}, {}

    def exact(self, digest, image_id):
        return self.hashes.get(digest)

    def candidates(self, value, image_id):
        for band in range(4):
            yield from self.bands.get((band, (value >> (band * 16)) & 0xffff), ())

    def remember(self, image_id, metrics, near_indexed):
        self.hashes.setdefault(metrics["sha256"], image_id)
        if near_indexed:
            value = int(metrics["dhash"])
            for band in range(4):
                self.bands.setdefault((band, (value >> (band * 16)) & 0xffff), []).append((value, image_id))


class DurableHashIndex:
    """Task-local persistent v47 four-band LSH, paged even for constant images.

    As in v47, near-duplicate search is approximate (four matching 16-bit
    bands); the configured Hamming cutoff only filters these candidates.
    """
    def __init__(self, database, check_active):
        self.database, self.check_active = database, check_active
        database.executescript("""
            CREATE TABLE IF NOT EXISTS clean_hashes (
                image_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, dhash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_clean_sha256 ON clean_hashes(sha256,image_id);
            CREATE TABLE IF NOT EXISTS clean_bands (
                band INTEGER, value INTEGER, image_id TEXT, dhash TEXT NOT NULL,
                PRIMARY KEY(band,value,image_id));
            CREATE INDEX IF NOT EXISTS ix_clean_bands_image ON clean_bands(image_id);
            CREATE TABLE IF NOT EXISTS clean_results (
                image_id TEXT PRIMARY KEY, result_json TEXT NOT NULL,
                flagged INTEGER NOT NULL CHECK(flagged IN (0,1)));
            INSERT OR IGNORE INTO meta(key,value) VALUES ('clean_flagged','0');
            CREATE TRIGGER IF NOT EXISTS clean_result_insert AFTER INSERT ON clean_results BEGIN
                UPDATE meta SET value=CAST(value AS INTEGER)+NEW.flagged WHERE key='clean_flagged';
            END;
            CREATE TRIGGER IF NOT EXISTS clean_result_update AFTER UPDATE ON clean_results BEGIN
                UPDATE meta SET value=CAST(value AS INTEGER)+NEW.flagged-OLD.flagged WHERE key='clean_flagged';
            END;
        """)

    def exact(self, digest, image_id):
        row = self.database.execute(
            "SELECT image_id FROM clean_hashes WHERE sha256=? AND image_id<>? ORDER BY image_id LIMIT 1",
            (digest, image_id),
        ).fetchone()
        return row[0] if row else None

    def candidates(self, value, image_id):
        for band in range(4):
            cursor = ""
            while True:
                self.check_active()
                rows = self.database.execute(
                    "SELECT image_id,dhash FROM clean_bands WHERE band=? AND value=? AND image_id>? "
                    "AND image_id<>? ORDER BY image_id LIMIT 500",
                    (band, (value >> (band * 16)) & 0xffff, cursor, image_id),
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    yield int(row[1], 16), row[0]
                cursor = rows[-1][0]

    def remember(self, image_id, metrics, near_indexed):
        value = int(metrics["dhash"])
        self.database.execute(
            "INSERT OR REPLACE INTO clean_hashes(image_id,sha256,dhash) VALUES (?,?,?)",
            (image_id, metrics["sha256"], f"{value:016x}"),
        )
        self.database.execute("DELETE FROM clean_bands WHERE image_id=?", (image_id,))
        if near_indexed:
            self.database.executemany("INSERT INTO clean_bands(band,value,image_id,dhash) VALUES (?,?,?,?)",
                ((band, (value >> (band * 16)) & 0xffff, image_id, f"{value:016x}") for band in range(4)))
