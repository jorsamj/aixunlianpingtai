"""Combine exact git source with verified same-SHA CI assets, without rebuilding."""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


def package(sha, artifact, metadata, output):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("A full exact commit SHA is required")
    info = json.loads(Path(metadata).read_text(encoding="utf-8"))
    raw = Path(artifact).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if (info["workflow_run"]["head_sha"] != sha
            or info["name"] != "vue-catalog-preview-" + sha
            or info["digest"] != "sha256:" + digest):
        raise ValueError("Artifact SHA/name/digest mismatch")
    source = subprocess.check_output(["git", "archive", "--format=zip", sha])
    with zipfile.ZipFile(io.BytesIO(raw)) as built, zipfile.ZipFile(io.BytesIO(source)) as original:
        if built.testzip() or original.testzip() or original.comment.decode() != sha:
            raise ValueError("ZIP CRC/source SHA mismatch")
        assets = {}
        for item in built.infolist():
            name = item.filename
            if item.is_dir() or not name.startswith("static/vue-catalog/"):
                continue
            if ".." in PurePosixPath(name).parts or "\\" in name:
                raise ValueError("Unsafe artifact path")
            if name in assets:
                raise ValueError("Duplicate artifact file")
            assets[name] = built.read(item)
        prefix = "static/vue-catalog/"
        receipt = json.loads(assets[prefix + "offline-assets.json"])
        if receipt["sha"] != sha or receipt["build_origin"] != "github-actions":
            raise ValueError("Assets are not this SHA's CI build")
        expected = {prefix + name for name in receipt["assets"]} | {prefix + "offline-assets.json"}
        if set(assets) != expected:
            raise ValueError("Unexpected or missing dynamic/shared asset")
        for name, record in receipt["assets"].items():
            data = assets[prefix + name]
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Asset hash mismatch: " + name)
        output = Path(output)
        if output.exists():
            raise FileExistsError(output)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
            for item in original.infolist():
                if not item.filename.startswith(prefix):
                    result.writestr(item, original.read(item))
            for name, data in assets.items():
                result.writestr(name, data)
            result.writestr("_delivery/vue-artifact-metadata.json", json.dumps(info, indent=2))
            result.comment = sha.encode()
    with zipfile.ZipFile(output) as result:
        if result.testzip():
            raise ValueError("Delivery ZIP CRC mismatch")
    proof = {"sha": sha, "artifact_sha256": digest, "vue_files": len(assets), "crc": "PASS",
             "package_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "rebuilt": False}
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sha", "artifact", "metadata", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(package(**vars(parser.parse_args())), indent=2))
