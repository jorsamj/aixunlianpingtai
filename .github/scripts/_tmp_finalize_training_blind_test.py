from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one finalizer target, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


workflow = ".github/workflows/v42.25-release-regression.yml"

replace_once(
    workflow,
    '''      - platform_core/training_metrics.py\n      - platform_core/training_tasks.py\n      - platform_core/video_tasks.py\n''',
    '''      - platform_core/training_metrics.py\n      - platform_core/training_evaluation.py\n      - platform_core/training_tasks.py\n      - platform_core/video_tasks.py\n''',
)

replace_once(
    workflow,
    '''      - tests/unit/test_training_ai_continuation_progress.py\n      - tests/unit/test_training_progress_v2.py\n      - tests/unit/test_training_realtime_progress.py\n      - tests/unit/test_training_resource_contract.py\n      - tests/unit/test_video_commit_fencing.py\n''',
    '''      - tests/unit/test_training_ai_continuation_progress.py\n      - tests/unit/test_training_blind_test_contract.py\n      - tests/unit/test_training_evaluation.py\n      - tests/unit/test_training_progress_v2.py\n      - tests/unit/test_training_realtime_progress.py\n      - tests/unit/test_training_resource_contract.py\n      - tests/unit/test_portable_dataset.py\n      - tests/unit/test_video_commit_fencing.py\n''',
)

replace_once(
    workflow,
    '''# Training-progress guard: preparation owns 0..20, active training advances 20..90 with throttled per-batch durable truth.\n# AI-continuation progress guard: a new continuation YOLO instance must rebind epoch/batch/resource callbacks and advance cumulative epoch truth through 90..95.\n''',
    '''# Training-progress guard: preparation owns 0..20, active training advances 20..90 with throttled per-batch durable truth.\n# Training blind-test guard: independent test GT stays outside Ultralytics labels/data.yaml; all image-only predictions finish before hidden GT scoring begins.\n# AI-continuation progress guard: a new continuation YOLO instance must rebind epoch/batch/resource callbacks and advance cumulative epoch truth through 90..95.\n''',
)

replace_once(
    workflow,
    '''          tests/unit/test_snapshots.py\n          tests/unit/test_portable_dataset.py\n          tests/unit/test_training_resource_contract.py\n''',
    '''          tests/unit/test_snapshots.py\n          tests/unit/test_portable_dataset.py\n          tests/unit/test_training_blind_test_contract.py\n          tests/unit/test_training_evaluation.py\n          tests/unit/test_training_resource_contract.py\n''',
)

print("release regression permanently guards blind independent test evaluation")
