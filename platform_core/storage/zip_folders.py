"""Folder confirmation for the existing v19 ZIP import owner."""
from collections import defaultdict
from hashlib import sha256
from pathlib import PurePosixPath
import json


_USAGE = {
    'train': 'train', 'training': 'train', '训练集': 'train',
    'val': 'val', 'valid': 'val', 'validation': 'val', '验证集': 'val',
    'test': 'test', 'testing': 'test', '测试集': 'test',
}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def folder_key(image_path):
    return PurePosixPath(image_path).parent.as_posix()


def sources_by_stem(paths):
    groups = defaultdict(list)
    for path in paths:
        groups[PurePosixPath(path).stem].append(path)
    return groups


def structured_image(reference, annotation_path, image_paths, image_stems):
    reference = str(reference or '').replace('\\', '/')
    if not reference or reference.startswith('/') or '..' in PurePosixPath(reference).parts:
        return None
    source = PurePosixPath(reference)
    parent = PurePosixPath(annotation_path).parent
    relative = (parent / source).as_posix()
    for candidate in ((reference, relative) if len(source.parts) > 1 else (relative, reference)):
        if candidate in image_paths:
            return candidate
    matches = image_stems.get(source.stem, ())
    for index in range(len(parent.parts) - 1, -1, -1):
        if parent.parts[index].casefold() in {'labels', 'annotations'}:
            mirrored = PurePosixPath(*parent.parts[:index], 'images', *parent.parts[index + 1:]) / source
            if mirrored.as_posix() in image_paths:
                return mirrored.as_posix()
            break
    if len(matches) > 1:
        raise ValueError(f'标注 {annotation_path} 无法唯一对应图片 {reference}，请提供完整来源路径或拆分导入')
    return matches[0] if matches else None


def yolo_sidecar(image_path, label_paths, label_stems, image_stems):
    path = PurePosixPath(image_path).with_suffix('.txt')
    parts = list(path.parts)
    for index in range(len(parts) - 2, -1, -1):
        if parts[index].lower() == 'images':
            alternate = PurePosixPath(*parts[:index], 'labels', *parts[index + 1:]).as_posix()
            if alternate in label_paths:
                return alternate
    if path.as_posix() in label_paths:
        return path.as_posix()
    candidates = label_stems.get(path.stem, ())
    if len(candidates) == 1 and len(image_stems.get(path.stem, ())) == 1:
        return candidates[0]
    return None


def folder_rows(images):
    result = {}
    for image in images:
        key = folder_key(image['path'])
        if key not in result:
            components = {part.casefold() for part in PurePosixPath(key).parts}
            roles = {_USAGE[part] for part in components if part in _USAGE}
            manual = bool(components & {'试验集', '评测集'})
            suggestion = next(iter(roles)) if len(roles) == 1 and not manual else 'unassigned'
            reason = ('用途目录冲突' if len(roles) > 1 else '目录术语需人工确认' if manual
                      else '匹配标准用途目录' if roles else '未匹配用途目录')
            result[key] = dict(folder_key=key, folder_path=key, suggested_usage=suggestion,
                               suggestion_reason=reason, confirmation_required=True,
                               image_count=0, annotated_count=0, annotation_formats=set())
        row = result[key]
        row['image_count'] += 1
        if image.get('annotation_format'):
            row['annotated_count'] += 1
            row['annotation_formats'].add(image['annotation_format'])
    return [{**result[key], 'annotation_formats': sorted(result[key]['annotation_formats'])} for key in sorted(result)]


def scan_identity(project_id, job_id, source_sha256, images, scan):
    return digest({'project_id': project_id, 'job_id': job_id, 'source_sha256': source_sha256,
                   'images': [(row['path'], row.get('annotation_format')) for row in images],
                   'classes': scan.get('external_classes'), 'scan_kind': scan.get('scan_kind'),
                   'mapping_conflict': scan.get('folder_mapping_conflict')})


def normalize_rules(images, selected_paths, rules, active_labels, categories):
    image_paths = {row['path'] for row in images}
    selected = set(selected_paths or image_paths)
    if not selected or not selected <= image_paths:
        raise ValueError('选择含有不属于当前扫描的图片')
    selected_rows = {row['folder_key']: row for row in folder_rows(row for row in images if row['path'] in selected)}
    normalized = {}
    for rule in rules:
        key = rule.get('folder_key')
        if not isinstance(key, str) or key not in selected_rows or key in normalized:
            raise ValueError('文件夹不存在、重复或未在导入范围内')
        usage, kind = rule.get('usage_intent'), rule.get('sample_type')
        if usage not in ('train', 'val', 'test', 'unassigned') or kind not in ('positive', 'negative', 'unclassified'):
            raise ValueError(f'{key}：请确认用途和素材类型')
        codes = rule.get('intended_label_codes', [])
        groups = rule.get('negative_category_ids', [])
        if any(not isinstance(values, list) or any(not isinstance(value, str) for value in values)
               for values in (codes, groups)):
            raise ValueError(f'{key}：标签和分类必须是 ID 列表')
        codes, groups = sorted(set(codes)), sorted(set(groups))
        if kind == 'positive' and (not codes or groups or not set(codes) <= active_labels):
            raise ValueError(f'{key}：请选择有效平台目标标签')
        if kind == 'negative' and (not groups or codes or not set(groups) <= categories):
            raise ValueError(f'{key}：请选择当前项目的有效负样本分类')
        if kind == 'unclassified' and (codes or groups or selected_rows[key]['annotated_count']):
            raise ValueError(f'{key}：含外部标注的文件夹必须确认映射及归集类型')
        normalized[key] = dict(folder_key=key, usage_intent=usage, sample_type=kind,
                               intended_label_codes=codes, negative_category_ids=groups)
    if normalized.keys() != selected_rows.keys():
        raise ValueError('所有待导入图片所在的文件夹都必须明确确认')
    return sorted(selected) if selected != image_paths else [], normalized
