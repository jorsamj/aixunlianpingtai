import sys
from types import SimpleNamespace

import pytest
import yaml

from train_worker import stage_gate_random_eval


def dataset(tmp_path, *, val='images/validation', count=8):
    root = tmp_path / 'bundle'
    for split in ('train', 'validation', 'test'):
        directory = root / 'images' / split
        directory.mkdir(parents=True)
        for i in range(count if split == 'validation' else 1):
            (directory / f'{split}-{i}.jpg').write_bytes(f'{split}-{i}'.encode())
    spec = {'path': 'bundle', 'train': 'images/train', 'val': val, 'test': 'images/test'}
    data = tmp_path / 'data.yaml'
    data.write_text(yaml.safe_dump(spec), encoding='utf-8')
    args = SimpleNamespace(data=str(data), val_max_samples=0, seed=7,
                           project_dir=str(tmp_path), job_id='stage', imgsz=640, device='cpu')
    trainer = SimpleNamespace(metrics={'metrics/mAP50(B)': .97},
                              data={'val': str(root / 'images/validation')})
    return args, trainer, root


def test_portable_validation_uses_yaml_path_and_full_scope(tmp_path):
    args, trainer, root = dataset(tmp_path)
    metrics, sampled, mode, note = stage_gate_random_eval(trainer, args, 1)
    assert sampled == [f'validation-{i}.jpg' for i in range(8)]
    assert metrics == trainer.metrics
    assert mode == 'all'


def test_fixed_seed_subset_does_not_change_with_epoch(tmp_path, monkeypatch):
    args, trainer, root = dataset(tmp_path)
    args.val_max_samples = 3
    trainer.last = tmp_path / 'last.pt'
    trainer.last.write_bytes(b'fake checkpoint')
    evaluated = []

    class FakeYOLO:
        def __init__(self, path):
            pass

        def val(self, **kwargs):
            spec = yaml.safe_load(open(kwargs['data'], encoding='utf-8'))
            evaluated.append(open(spec['val'], encoding='utf-8').read().splitlines())
            assert kwargs['split'] == 'val'
            return SimpleNamespace(results_dict={'metrics/mAP50(B)': .6})

    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=FakeYOLO))
    first = stage_gate_random_eval(trainer, args, 1)
    second = stage_gate_random_eval(trainer, args, 20)
    assert first[2] == second[2] == 'random'
    assert len(first[1]) == 3
    assert first[1] == second[1]
    assert evaluated[0] == evaluated[1]
    assert all('/validation/' in path for path in evaluated[0])


def test_failed_subset_records_actual_full_normal_validation(tmp_path):
    args, trainer, root = dataset(tmp_path)
    args.val_max_samples = 3
    metrics, sampled, mode, note = stage_gate_random_eval(trainer, args, 1)
    assert mode == 'normal_validation'
    assert len(sampled) == 8
    assert metrics == trainer.metrics
    assert note


@pytest.mark.parametrize('val', ['images/test', 'images/train', 'missing', '../outside'])
def test_unproven_or_forbidden_source_cannot_stop(tmp_path, val):
    args, trainer, root = dataset(tmp_path, val=val)
    metrics, sampled, mode, note = stage_gate_random_eval(trainer, args, 1)
    assert metrics == {}
    assert sampled == []
    assert mode == 'invalid_source'
    assert note


def test_cross_split_duplicate_sha_cannot_produce_gate_metrics(tmp_path):
    args, trainer, root = dataset(tmp_path)
    (root / 'images/test/test-0.jpg').write_bytes(b'validation-0')
    assert stage_gate_random_eval(trainer, args, 1)[0] == {}


def test_frozen_validation_content_cannot_change_between_gates(tmp_path):
    args, trainer, root = dataset(tmp_path)
    assert stage_gate_random_eval(trainer, args, 1)[0] == trainer.metrics
    (root / 'images/validation/validation-0.jpg').write_bytes(b'changed')
    assert stage_gate_random_eval(trainer, args, 2)[0] == {}


def test_normal_metrics_from_another_split_are_not_trusted(tmp_path):
    args, trainer, root = dataset(tmp_path)
    trainer.data['val'] = str(root / 'images/test')
    assert stage_gate_random_eval(trainer, args, 1)[0] == {}


def test_missing_metrics_are_not_synthesized(tmp_path):
    args, trainer, root = dataset(tmp_path)
    trainer.metrics = {'fitness': .99, 'metrics/mAP50(B)': float('nan')}
    metrics = stage_gate_random_eval(trainer, args, 1)[0]
    assert 'metrics/mAP50(B)' not in metrics
    assert 'metrics/recall(B)' not in metrics


def test_list_manifest_validation_and_nested_images(tmp_path):
    args, trainer, root = dataset(tmp_path)
    manifest = root / 'validation.txt'
    manifest.write_text('./images/validation/validation-0.jpg\n./images/validation/validation-1.jpg\n', encoding='utf-8')
    spec = yaml.safe_load(open(args.data, encoding='utf-8'))
    spec['val'] = ['validation.txt']
    open(args.data, 'w', encoding='utf-8').write(yaml.safe_dump(spec))
    trainer.data['val'] = [str(manifest)]
    result = stage_gate_random_eval(trainer, args, 1)
    assert result[1] == ['validation-0.jpg', 'validation-1.jpg']
    assert result[0] == trainer.metrics


def test_confirmed_negative_image_with_empty_label_is_kept(tmp_path):
    args, trainer, root = dataset(tmp_path)
    labels = root / 'labels/validation'
    labels.mkdir(parents=True)
    (labels / 'validation-0.txt').write_text('', encoding='utf-8')
    assert 'validation-0.jpg' in stage_gate_random_eval(trainer, args, 1)[1]


def test_legacy_directory_remains_supported_without_val_field(tmp_path):
    args, trainer, root = dataset(tmp_path)
    legacy = root / 'images/val'
    (root / 'images/validation').rename(legacy)
    spec = yaml.safe_load(open(args.data, encoding='utf-8'))
    del spec['val']
    open(args.data, 'w', encoding='utf-8').write(yaml.safe_dump(spec))
    trainer.data['val'] = str(legacy)
    assert len(stage_gate_random_eval(trainer, args, 1)[1]) == 8


def test_unproven_trainer_metrics_cannot_be_used_as_fallback(tmp_path):
    args, trainer, root = dataset(tmp_path)
    del trainer.data
    assert stage_gate_random_eval(trainer, args, 1)[0] == {}


@pytest.mark.parametrize('failure', ['save', 'val'])
def test_extra_evaluation_failure_cannot_claim_subset_evidence(tmp_path, monkeypatch, failure):
    args, trainer, root = dataset(tmp_path)
    args.val_max_samples = 3
    trainer.last = tmp_path / 'last.pt'
    trainer.last.write_bytes(b'old checkpoint')
    invoked = []

    def save_model():
        if failure == 'save':
            raise RuntimeError('save failed')

    class FakeYOLO:
        def __init__(self, path):
            invoked.append(path)

        def val(self, **kwargs):
            raise RuntimeError('validation failed')

    trainer.save_model = save_model
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=FakeYOLO))
    metrics, sampled, mode, note = stage_gate_random_eval(trainer, args, 1)
    assert metrics == trainer.metrics
    assert len(sampled) == 8
    assert mode == 'normal_validation'
    assert note
    if failure == 'save':
        assert invoked == []


def test_ai_contact_sheet_uses_same_yaml_source_and_fixed_subset(tmp_path):
    from PIL import Image
    from train_worker import _ai_eval_contact_sheet

    args, trainer, root = dataset(tmp_path)
    for path in (root / 'images/validation').iterdir():
        Image.new('RGB', (4, 4), 'red').save(path)
    first = _ai_eval_contact_sheet(args.data, 3, 7, 1, tmp_path / 'sheet')
    second = _ai_eval_contact_sheet(args.data, 3, 7, 20, tmp_path / 'sheet')
    assert first[0].is_file() and second[0].is_file()
    assert first[1] == second[1]
    assert all(name.startswith('validation-') for name in first[1])


def test_duplicate_filenames_report_unambiguous_relative_identity(tmp_path):
    args, trainer, root = dataset(tmp_path)
    nested = root / 'images/validation/nested'
    nested.mkdir()
    (nested / 'validation-0.jpg').write_bytes(b'another actual image')
    sampled = stage_gate_random_eval(trainer, args, 1)[1]
    assert 'images/validation/validation-0.jpg' in sampled
    assert 'images/validation/nested/validation-0.jpg' in sampled


def test_disabled_trainer_validation_cannot_supply_stale_metrics(tmp_path):
    args, trainer, root = dataset(tmp_path)
    trainer.args = SimpleNamespace(val=False)
    assert stage_gate_random_eval(trainer, args, 1)[0] == {}


def test_unchanged_stage_reuses_verified_sha_without_full_dataset_reads(tmp_path, monkeypatch):
    import hashlib

    args, trainer, root = dataset(tmp_path)
    original = hashlib.file_digest
    reads = []

    def counted(stream, algorithm):
        reads.append(stream.name)
        return original(stream, algorithm)

    monkeypatch.setattr(hashlib, 'file_digest', counted)
    assert stage_gate_random_eval(trainer, args, 1)[0] == trainer.metrics
    assert len(reads) == 10
    reads.clear()
    assert stage_gate_random_eval(trainer, args, 2)[0] == trainer.metrics
    assert reads == []
    (root / 'images/test/test-0.jpg').write_bytes(b'validation-0')
    assert stage_gate_random_eval(trainer, args, 3)[0] == {}
