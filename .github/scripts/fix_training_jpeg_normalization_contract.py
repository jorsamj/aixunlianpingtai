from pathlib import Path

path = Path("tests/unit/test_training_startup_performance_contract.py")
text = path.read_text(encoding="utf-8")
old = '    assert manifest["construction_verification"]["image_integrity"] == "sha256_verified_during_materialization"\n'
new = '    assert manifest["construction_verification"]["image_integrity"] == "source_sha256_verified_then_training_input_normalized"\n    assert manifest["construction_verification"]["training_input_policy"] == "ultralytics_jpeg_repair_v1"\n'
if old not in text:
    raise SystemExit("startup performance construction-evidence contract anchor missing")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
