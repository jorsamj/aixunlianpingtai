"""Frozen, train-only simulated color-decoder mismatches.

These presets are synthetic device variability, not device calibration. Encode
RGB with the named BT standard/range and deliberately decode with the opposite
standard AND range. An encode/decode with the same matrix would be an identity.
Coordinates and labels are retained; sources and validation/Test never change.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from filelock import FileLock
from PIL import Image

PRESETS = ('bt601_limited', 'bt601_full', 'bt709_limited', 'bt709_full')


def _integer(value, field):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value) or int(value) != value:
        raise ValueError(f'robustness {field} must be an integer')
    return int(value)


def normalize_policy(value=None):
    value = dict(value or {})
    mode = value.get('mode', 'enabled' if value.get('enabled') else 'disabled')
    if mode not in {'enabled', 'disabled', 'inherit'}:
        raise ValueError('invalid robustness mode')
    selection = dict(value.get('selection') or {'mode': 'ratio', 'ratio': 20})
    selection_mode = selection.get('mode', 'ratio')
    if selection_mode not in {'ratio', 'count', 'manual'}:
        raise ValueError('invalid robustness selection mode')
    normalized = {'mode': selection_mode}
    if selection_mode == 'ratio':
        if isinstance(selection.get('ratio'), bool):
            raise ValueError('robustness ratio must be numeric')
        ratio = float(selection.get('ratio', 20))
        if not math.isfinite(ratio) or not 0 <= ratio <= 100:
            raise ValueError('robustness ratio must be 0..100')
        normalized['ratio'] = ratio
    elif selection_mode == 'count':
        count = _integer(selection.get('count', 100), 'count')
        if count < 0:
            raise ValueError('robustness count must be nonnegative')
        normalized['count'] = count
    else:
        image_ids = selection.get('image_ids', [])
        if not isinstance(image_ids, list) or any(not isinstance(item, str) or not item.strip() for item in image_ids):
            raise ValueError('robustness manual image_ids must be a list of image ids')
        normalized['image_ids'] = sorted(set(image_ids))
    copies = _integer(value.get('copies', 1), 'copies')
    if not 1 <= copies <= 3:
        raise ValueError('robustness copies must be 1..3')
    raw_presets = value.get('presets', list(PRESETS))
    if not isinstance(raw_presets, list) or any(not isinstance(item, str) for item in raw_presets):
        raise ValueError('robustness presets must be a list')
    presets = list(dict.fromkeys(raw_presets))
    if not presets or any(item not in PRESETS for item in presets):
        raise ValueError('unknown robustness preset')
    return {'mode': mode, 'enabled': mode == 'enabled', 'selection': normalized,
            'copies': copies, 'presets': presets, 'seed': _integer(value.get('seed', 0), 'seed'),
            'transform_version': 'rgb_yuv_decoder_mismatch_v1'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_global_policy(data_dir):
    path = Path(data_dir) / 'config' / 'training_robustness.json'
    if not path.exists():
        return {'revision': '0', 'policy': normalize_policy({'enabled': False})}
    value = json.loads(path.read_text(encoding='utf-8'))
    policy = normalize_policy(value['policy'])
    if value.get('revision') != _digest(policy):
        raise ValueError('robustness global revision mismatch')
    return {'revision': value['revision'], 'policy': policy}


def save_global_policy(data_dir, policy, expected_revision):
    path = Path(data_dir) / 'config' / 'training_robustness.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + '.lock', timeout=10):
        if read_global_policy(data_dir)['revision'] != str(expected_revision):
            raise ValueError('robustness global revision changed')
        normalized = normalize_policy(policy)
        if normalized['mode'] == 'inherit':
            raise ValueError('global robustness policy cannot inherit')
        result = {'revision': _digest(normalized), 'policy': normalized}
        temporary = path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return result


def resolve_policy(data_dir, value=None):
    requested = dict(value or {'mode': 'inherit'})
    if requested.get('source') in {'global', 'task'} and requested.get('mode') in {'enabled', 'disabled'}:
        return {**normalize_policy(requested), 'global_revision': requested.get('global_revision'),
                'source': requested['source']}
    if requested.get('mode', 'inherit') == 'inherit':
        current = read_global_policy(data_dir)
        return {**current['policy'], 'global_revision': current['revision'], 'source': 'global'}
    return {**normalize_policy(requested), 'global_revision': None, 'source': 'task'}


def select_train_ids(train_ids, policy):
    train_ids = set(map(str, train_ids))
    selection = policy['selection']
    if selection['mode'] == 'manual':
        selected = set(selection.get('image_ids') or [])
        if not selected <= train_ids:
            raise ValueError('robustness manual image_ids must belong to frozen train split')
        return sorted(selected)
    ordered = sorted(train_ids, key=lambda item: hashlib.sha256(f"{policy['seed']}:{item}".encode()).digest())
    count = (int(selection['count']) if selection['mode'] == 'count' else
             int(math.ceil(len(ordered) * float(selection['ratio']) / 100)))
    if selection['mode']=='count' and count>len(ordered):
        raise ValueError('CSC_SELECTION_COUNT_EXCEEDS_TRAIN: 指定增强数量超过最终训练集可用原图数')
    return ordered[:count]


def transform_rgb(image, preset):
    import numpy as np
    if preset not in PRESETS:
        raise ValueError('unknown robustness preset')
    standard, range_name = preset.split('_')
    kr, kb = (0.299, 0.114) if standard == 'bt601' else (0.2126, 0.0722)
    dkr, dkb = (0.2126, 0.0722) if standard == 'bt601' else (0.299, 0.114)
    rgb = np.asarray(image.convert('RGB'), dtype=np.float64) / 255
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = kr*r + (1-kr-kb)*g + kb*b
    cb, cr = (b-y)/(2*(1-kb)), (r-y)/(2*(1-kr))
    if range_name == 'limited':
        y, cb, cr = 16+219*y, 128+224*cb, 128+224*cr
        # The simulated receiver incorrectly assumes full range.
        y, cb, cr = np.rint(y)/255, (np.rint(cb)-128)/255, (np.rint(cr)-128)/255
    else:
        y, cb, cr = (np.clip(np.rint(channel), 0, 255) for channel in (255*y, 128+255*cb, 128+255*cr))
        # The simulated receiver incorrectly assumes limited range.
        y, cb, cr = (y-16)/219, (cb-128)/224, (cr-128)/224
    rr, bb = y+2*(1-dkr)*cr, y+2*(1-dkb)*cb
    gg = (y-dkr*rr-dkb*bb)/(1-dkr-dkb)
    output = np.stack((rr,gg,bb), axis=-1)
    return Image.fromarray(np.clip(np.rint(output*255), 0, 255).astype('uint8'), 'RGB')


def augment_bundle(root, snapshot, splits, policy, progress=None, *, safety_reserve_bytes=0):
    """Append deterministic PNG copies after the original role split is fixed."""
    root = Path(root)
    from .training_tasks import _bundle_output_path, _check_bundle_disk_space
    from io import BytesIO
    if not policy or not policy.get('enabled'):
        return []
    selected = set(select_train_ids((snapshot.get('ids') or {}).get('train', []), policy))
    originals = [row for row in splits['train'] if row['image_id'] in selected and not row.get('augmentation')]
    derived = []
    frozen_rows = {str(row.get('image_id')): row for row in snapshot.get('images') or []}
    for row in originals:
        for copy in range(policy['copies']):
            key = f"{policy['seed']}:{row['image_id']}:{copy}"
            preset = policy['presets'][int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(policy['presets'])]
            identity = _digest([row['image_id'], policy, copy])[:24]
            frozen_source = frozen_rows.get(row['image_id'], {})
            encode_standard, encode_range = preset.split('_')
            image_ref = f'dataset/images/train/robustness_{identity}.png'
            label_ref = f'dataset/labels/train/robustness_{identity}.txt'
            destination = _bundle_output_path(root, image_ref)
            with Image.open(root / row['image_ref']) as source:
                transformed = transform_rgb(source, preset)
                if transformed.tobytes() == source.convert('RGB').tobytes():
                    raise ValueError(f'CSC_NO_PIXEL_CHANGE: 素材 {row["image_id"]} 在 {preset} 预设量化后无像素变化，未将其计为增强；请调整预设或抽样')
                buffer = BytesIO()
                transformed.save(buffer, format='PNG')
                encoded = buffer.getvalue()
                _check_bundle_disk_space(root, len(encoded), len(encoded), safety_reserve_bytes)
                temporary = _bundle_output_path(root, image_ref + '.tmp')
                temporary.write_bytes(encoded)
                os.replace(temporary, destination)
            labels = (root / row['label_ref']).read_bytes()
            _bundle_output_path(root, label_ref).write_bytes(labels)
            item = {**row, 'image_ref': image_ref, 'label_ref': label_ref,
                    'content_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                    'size_bytes': destination.stat().st_size,
                    'label_sha256': hashlib.sha256(labels).hexdigest(),
                    'augmentation': {'policy_digest': _digest(policy), 'preset': preset,
                                     'transformation_type': 'rgb_yuv_decoder_mismatch',
                                     'transformation_version': 'v1',
                                     'source_root_id': frozen_source.get('source_root_id') or row['image_id'],
                                     'derived_from_image_id': row['image_id'],
                                     'source_group_id': frozen_source.get('source_group_id') or frozen_source.get('group_id') or row['image_id'],
                                     'derived_from': row['image_ref'],
                                     'group_id': frozen_rows.get(row['image_id'], {}).get('group_id', row['image_id']),
                                     'transformation_params': {
                                         'encode_standard': encode_standard,
                                         'encode_range': encode_range,
                                         'decode_standard': 'bt709' if encode_standard == 'bt601' else 'bt601',
                                         'decode_range': 'full' if encode_range == 'limited' else 'limited',
                                         'seed': policy['seed'],
                                         'rounding': 'nearest_even_8bit',
                                         'output': 'rgb_uint8_clamped_png',
                                     },
                                     'created_at': snapshot.get('created_at'),
                                     'copy': copy+1, 'source_image_id': row['image_id'],
                                     'source_training_sha256': row['content_sha256']}}
            derived.append(item)
            if progress:
                progress(len(derived), len(originals)*policy['copies'], item)
    splits['train'].extend(derived)
    return derived


def augmentation_summary(manifest):
    """Actual counts from the already verified, task-owned portable manifest."""
    if not manifest.get('robustness_policy'):
        return None
    splits=manifest.get('splits') or {}
    train=splits.get('train') or []
    derived=[row for row in train if row.get('augmentation')]
    return {'original_train_images':len(train)-len(derived), 'augmented_images':len(derived),
            'actual_train_images':len(train), 'validation_images':len(splits.get('validation') or []),
            'test_images':len(splits.get('test') or []),
            'augmented_bytes':sum(int(row.get('size_bytes') or 0) for row in derived),
            'policy_digest':_digest(manifest['robustness_policy'])}
