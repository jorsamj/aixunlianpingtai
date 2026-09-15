from pathlib import Path

path = Path(".github/tmp_training_bundle_cache_hardening.py")
text = path.read_text(encoding="utf-8")
replacements = {
    'expected_snapshot = str(manifest.get("snapshot_sha256") or "")': 'expected_snapshot_sha = str(manifest.get("snapshot_sha256") or "")',
    'or not expected_snapshot\\n': 'or not expected_snapshot_sha\\n',
    '_sha256(snapshot_path) != expected_snapshot\\n': '_sha256(snapshot_path) != expected_snapshot_sha\\n',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"hardening helper correction target missing: {old}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
