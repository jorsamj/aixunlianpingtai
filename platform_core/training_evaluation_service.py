"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from fastapi import HTTPException
from .training_evaluation_contracts import EvaluationReviewReq, FreezeReviewedMiningReq, FreezeSupplementFeedbackCandidatesReq, HardSampleMiningCreateReq, SupplementFeedbackCandidateSelection

import json
import hashlib
import math
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Sequence
from fastapi.responses import FileResponse, Response
from platform_core.annotation_repository import AnnotationRepository
from platform_core.algorithms import update_algorithm_version
from platform_core.annotation_candidates import CandidateStore
from platform_core.material_repository import MaterialRepository
from platform_core.reports import build_algorithm_report
from platform_core.storage import StorageError
from platform_core.task_runtime import TaskKind, TaskStatus

@dataclass(frozen=True)
class TrainingEvaluationDependencies:
    _EVALUATION_SNAPSHOT_INDEX_CACHE: Callable[..., Any]
    _EVALUATION_SNAPSHOT_INDEX_LIMIT: Callable[..., Any]
    _EVALUATION_SNAPSHOT_INDEX_LOCK: Callable[..., Any]
    _EVALUATION_TASK_SNAPSHOT_READ_LOCK: Callable[..., Any]
    _EvaluationSnapshotIndexError: Any
    _TRAINING_COUNT_PAYLOADS: Callable[..., Any]
    _TRAINING_JOB_PROJECTION_LOCK: Callable[..., Any]
    _algorithm_version_for_action: Callable[..., Any]
    _annotation_label_catalog: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _online_feedback_repository: Callable[..., Any]
    _require_annotation_review_task: Callable[..., Any]
    _storage_source_fence: Callable[..., Any]
    _successful_training_counts: Callable[..., Any]
    _testable_version_pt_path: Callable[..., Any]
    _training_history_context: Callable[..., Any]
    algorithms_file: Callable[..., Any]
    get_project: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    public_annotation_task: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    read_json: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    storage_manager: Callable[..., Any]


class TrainingEvaluationService:
    def __init__(self, dependencies: TrainingEvaluationDependencies):
        self.dependencies = dependencies

    def _evaluation_snapshot_preview_path(self, project_id, version, evaluation, snapshot_id):
        "Resolve missing legacy project Snapshot from its exact durable TRAINING task.\n\n    Read-only: never reconstruct from today's materials, write a project file,\n    or relax the downstream frozen Test/image-byte verification.\n    "
        canonical = self.dependencies.project_dir(project_id) / "snapshots" / f"{snapshot_id}.json"
        if canonical.is_file():
            return canonical, False
        if canonical.exists() or canonical.is_symlink():
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '冻结快照路径不是有效文件')
        lineage = version.get('training_lineage') or {}
        ids = [
            str(value).strip() for value in (
                evaluation.get('task_id'), version.get('job_id'),
                lineage.get('task_id') if isinstance(lineage, dict) else None,
            ) if value
        ]
        if not ids:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_MISSING', '冻结快照文件不存在')
        if len(set(ids)) != 1:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '冻结评测与训练任务身份冲突')
        if version.get('snapshot_id') and str(version['snapshot_id']).lower() != snapshot_id:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '算法版本冻结快照身份不一致')
        task_id = ids[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task_id):
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_MISSING', '历史任务身份不可验证')
        task = self.dependencies.shared_task_repository().get(task_id)
        if task is None or str(task.project_id) != str(project_id) or task.kind is not TaskKind.TRAINING:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_MISSING', '未找到同项目的可信训练任务')
        candidate = self.dependencies.shared_task_artifacts().artifact_path(task_id, 'snapshot.json')
        if (candidate.is_symlink() or candidate.parent.is_symlink()
                or not candidate.is_file()):
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_MISSING', '训练任务原始冻结快照不存在')
        return candidate, True

    def _evaluation_snapshot_identity_index(self, path: Path, snapshot_id: str, *, verify_digest=False):
        'Return one bounded, immutable identity projection for a frozen Snapshot.\n\n    The cache owns only parsed Snapshot metadata. It never caches Material rows,\n    provider objects, decoded images, or response bytes. File stat identity makes\n    replacement invalidate the projection while every response still verifies\n    the selected material and actual file SHA256.\n    '
        try:
            stat = path.stat()
        except OSError as error:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_MISSING', '冻结快照文件不存在') from error
        key = (str(path.resolve()), ('verified:' if verify_digest else '') + snapshot_id,
               int(stat.st_mtime_ns), int(stat.st_size))
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            cached = self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().get(key)
            if cached is not None:
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().move_to_end(key)
                return cached
        snapshot = self.dependencies.read_json(path, {})
        if not isinstance(snapshot, dict) or snapshot.get('snapshot_id') != snapshot_id:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '冻结快照与评测身份不一致')
        if verify_digest:
            from platform_core.snapshots import snapshot_content_matches_identity
            if not snapshot_content_matches_identity(snapshot, snapshot_id):
                raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '训练任务冻结快照内容摘要校验失败')
        ids = snapshot.get('test_image_ids')
        if ids is None and isinstance(snapshot.get('ids'), dict):
            ids = snapshot['ids'].get('test')
        test_ids = tuple(dict.fromkeys(str(value) for value in (ids or []) if str(value)))
        if not test_ids or len(test_ids) > 30000:
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '冻结测试集身份无法验证')
        test_id_set = frozenset(test_ids)
        frozen_rows = tuple(
            dict(row) for row in (snapshot.get('images') or [])
            if isinstance(row, dict) and str(row.get('image_id') or '') in test_id_set
        )
        frozen = {str(row['image_id']): row for row in frozen_rows}
        if len(frozen_rows) != len(test_ids) or len(frozen) != len(test_ids):
            raise self.dependencies._EvaluationSnapshotIndexError('SNAPSHOT_INCOMPLETE', '冻结测试集图片身份不完整')
        stored_names = {}
        for image_id, row in frozen.items():
            stored_name = str(row.get('stored_name') or '')
            if stored_name:
                stored_names.setdefault(stored_name, []).append(image_id)
        result = {
            'test_ids': test_ids,
            'frozen': frozen,
            'stored_names': {name: tuple(values) for name, values in stored_names.items()},
            'all_have_stored_name': len(stored_names) == len(test_ids),
        }
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            for old_key in tuple(self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()):
                if old_key[0] == key[0] and old_key != key:
                    self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().pop(old_key, None)
            self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()[key] = result
            self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().move_to_end(key)
            while len(self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()) > self.dependencies._EVALUATION_SNAPSHOT_INDEX_LIMIT():
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().popitem(last=False)
        return result

    def _evaluation_bundle_identity_index(self, path: Path, snapshot_id: str):
        """Share the bounded metadata cache; never cache files or provider state."""
        try:
            stat = path.stat()
        except OSError:
            return {}
        key = (str(path.resolve()), 'bundle:' + snapshot_id, int(stat.st_mtime_ns), int(stat.st_size))
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            cached = self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().get(key)
            if cached is not None:
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().move_to_end(key)
                return cached
        manifest = self.dependencies.read_json(path, {})
        if not isinstance(manifest, dict) or manifest.get('snapshot_id') != snapshot_id:
            return {}
        members = (manifest.get('splits') or {}).get('test', [])
        if not isinstance(members, list) or len(members) > 30000:
            return {}
        by_name = {}
        for row in members:
            if isinstance(row, dict):
                by_name.setdefault(Path(str(row.get('image_ref') or '')).name, []).append(dict(row))
        result = {'snapshot_id': snapshot_id, 'by_name': by_name}
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            for old_key in tuple(self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()):
                if old_key[0] == key[0] and old_key != key:
                    self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().pop(old_key, None)
            self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()[key] = result
            while len(self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()) > self.dependencies._EVALUATION_SNAPSHOT_INDEX_LIMIT():
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().popitem(last=False)
        return result

    def _evaluation_legacy_name_index(self, path: Path, repository, test_ids):
        stat = path.stat()
        key = (str(path.resolve()), 'legacy:' + str(repository.current_revision()), int(stat.st_mtime_ns), int(stat.st_size))
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            cached = self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().get(key)
            if cached is not None:
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().move_to_end(key)
                return cached
        names = {}
        for offset in range(0, len(test_ids), 500):
            for row in repository.get_many(test_ids[offset:offset + 500]):
                names.setdefault(str(row.get('stored_name') or ''), []).append(str(row['id']))
        with self.dependencies._EVALUATION_SNAPSHOT_INDEX_LOCK():
            self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()[key] = names
            while len(self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE()) > self.dependencies._EVALUATION_SNAPSHOT_INDEX_LIMIT():
                self.dependencies._EVALUATION_SNAPSHOT_INDEX_CACHE().popitem(last=False)
        return names

    def evaluation_diagnostic_image_v1(self, project_id: str, algorithm_id: str, version_id: str, image_name: str,
            expected_evaluation_id: str = '', expected_image_id: str = '', expected_sha256: str = ''):
        'Read-only frozen Test Split preview, never a source of training candidates.\n\n    Authorize the version/evaluation and the exact snapshot/material digest\n    before returning bytes. Historical or unbound test snapshots fail closed.\n    '
        self.dependencies._authorize_business_file_project(project_id)
        def reject(code, message, status=409, retryable=False):
            raise HTTPException(status_code=status, detail={
                'code': code, 'message': message, 'retryable': retryable,
                'solution': '请稍后重试；持续失败时检查存储连接。' if retryable else '请恢复原始证据；无法恢复时需要重新评测。',
            })

        def verified_image_response(candidate: Path, evidence_source: str, evidence_sha256: str):
            media_types = {
                'JPEG': 'image/jpeg',
                'PNG': 'image/png',
                'WEBP': 'image/webp',
                'BMP': 'image/bmp',
            }
            try:
                from PIL import Image
                with Image.open(candidate) as decoded:
                    image_format = str(decoded.format or '').upper()
                    width, height = decoded.size
                    decoded.verify()
                with Image.open(candidate) as decoded:
                    orientation = decoded.getexif().get(274, 1)
            except (OSError, ValueError):
                reject('IMAGE_DECODE_FAILED', '评测图片证据无法解码')
            if image_format not in media_types or width <= 0 or height <= 0:
                reject('IMAGE_DECODE_FAILED', '评测图片格式不受支持')
            headers = {
                'Cache-Control': 'private, no-store',
                'X-Content-Type-Options': 'nosniff',
                'X-Evaluation-Image-Format': image_format,
                'X-Evaluation-Image-Width': str(width),
                'X-Evaluation-Image-Height': str(height),
                'X-Evaluation-Evidence-Source': evidence_source,
                'X-Evaluation-Original-SHA256': evidence_sha256,
                'X-Evaluation-Snapshot-Source': (
                    'verified-task-artifact' if task_snapshot_fallback else 'project'),
            }
            if orientation not in (None, 1):
                # The scorer records Pillow's raw pixel grid. Strip orientation in
                # an in-memory display derivative so browser auto-rotation cannot
                # move boxes; the frozen file and its identity remain unchanged.
                try:
                    with Image.open(candidate) as decoded:
                        with decoded.convert('RGBA' if 'A' in decoded.getbands() else 'RGB') as display:
                            output = BytesIO()
                            display.save(output, format='PNG', exif=b'')
                except (OSError, ValueError):
                    reject('IMAGE_DECODE_FAILED', '评测图片证据无法解码')
                headers.update({'X-Evaluation-Image-Format': 'PNG',
                                'X-Evaluation-Original-Format': image_format,
                                'X-Evaluation-Display-Derived': 'true'})
                return Response(output.getvalue(), media_type='image/png', headers=headers)
            response_class = FileResponse
            response_kwargs = {}
            if evidence_source == 'bundle':
                from platform_core.training_workspace_http import TrainingEvidenceFileResponse
                response_class = TrainingEvidenceFileResponse
                response_kwargs = {'workspace_root': bundle.parent.parent, 'expected_sha256': evidence_sha256}
            elif evidence_source == 'material':
                from platform_core.storage.http import StoredSourceFileResponse
                response_class = StoredSourceFileResponse
                response_kwargs = {'manager': manager, 'material': material}
            return response_class(
                candidate,
                **response_kwargs,
                media_type=media_types[image_format],
                headers=headers,
            )

        algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        evaluation = version.get("evaluation") or {}
        if not isinstance(evaluation, dict) or evaluation.get("status") != "succeeded":
            raise HTTPException(status_code=404, detail="评测记录不存在")
        if image_name != Path(image_name).name or '\\' in image_name or not image_name or image_name in {".", ".."}:
            raise HTTPException(status_code=404, detail="评测图片不存在")
        matches = []
        for evidence_key in ('sample_evidence', 'error_samples', 'sample_outcomes'):
            matches = [row for row in list(evaluation.get(evidence_key) or [])
                       if isinstance(row, dict) and row.get("image") == image_name]
            if matches:
                break
        if len(matches) > 1:
            reject('IMAGE_IDENTITY_AMBIGUOUS', '评测样本图片身份不唯一')
        if not matches:
            raise HTTPException(status_code=404, detail="图片不属于本版本的冻结评测样本")
        sample = matches[0]
        if expected_evaluation_id or expected_image_id or expected_sha256:
            if (not re.fullmatch(r'[0-9a-f]{64}', expected_evaluation_id)
                    or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)
                    or expected_evaluation_id != evaluation.get('evaluation_id')
                    or expected_sha256 != sample.get('image_content_sha256')
                    or (expected_image_id and expected_image_id != str(sample.get('image_id') or ''))):
                reject('EVALUATION_IDENTITY_CHANGED', '报告冻结评测或图片身份已变化，请刷新当前版本')
        snapshot_id = str(evaluation.get("snapshot_id") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            reject('SNAPSHOT_MISSING', '历史评测缺少可验证的冻结快照')
        try:
            path, task_snapshot_fallback = self._evaluation_snapshot_preview_path(
                project_id, version, evaluation, snapshot_id)
            if task_snapshot_fallback:
                with self.dependencies._EVALUATION_TASK_SNAPSHOT_READ_LOCK():
                    snapshot_index = self._evaluation_snapshot_identity_index(
                        path, snapshot_id, verify_digest=True)
            else:
                snapshot_index = self._evaluation_snapshot_identity_index(path, snapshot_id)
        except self.dependencies._EvaluationSnapshotIndexError as error:
            reject(error.code, error.message)
        test_ids = snapshot_index['test_ids']
        frozen = snapshot_index['frozen']
        task_id = str(evaluation.get('task_id') or version.get('job_id') or '')
        evaluated_hash = str(sample.get('image_content_sha256') or '').lower()
        bundle = None
        manifest = {}
        if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task_id):
            bundle = self.dependencies.shared_task_artifacts().artifact_path(task_id, 'work/bundle').resolve()
            if not (bundle / 'manifest.json').is_file():
                bundle = self.dependencies.shared_task_artifacts().artifact_path(task_id, 'evidence/bundle').resolve()
            manifest_path = bundle / 'manifest.json'
            manifest = self._evaluation_bundle_identity_index(manifest_path, snapshot_id)
            if manifest.get('snapshot_id') != snapshot_id:
                bundle = self.dependencies.shared_task_artifacts().artifact_path(task_id, 'evidence/bundle').resolve()
                manifest = self._evaluation_bundle_identity_index(bundle / 'manifest.json', snapshot_id)
                if manifest.get('snapshot_id') != snapshot_id:
                    manifest = {}
        # V3 frozen snapshots carry stored_name. Resolve a unique frozen ID
        # before querying MaterialRepository; legacy snapshots use bounded reads.
        repository = MaterialRepository(self.dependencies.project_dir(project_id))
        stable_id = str(sample.get('image_id') or '')
        if stable_id and stable_id not in frozen:
            reject('IMAGE_NOT_IN_SNAPSHOT', '评测图片不属于冻结测试集')
        if stable_id:
            selected_ids = [stable_id]
        else:
            # Historical samples have no stable ID. A filename stem is not an
            # identity: it may collide with a different frozen Image ID. Prefer
            # proven evaluated Bundle identity, then unique frozen stored_name.
            stored_ids = list(snapshot_index['stored_names'].get(image_name, ()))
            if manifest.get('by_name', {}).get(image_name):
                # Portable training bundles rename members to {image_id}.{ext}.
                # Old evaluation rows did not persist image_id, so a strict
                # stored_name-only lookup rejects valid archived evidence. Recover
                # through the bundle only when its snapshot, member identity and
                # source/evaluated hashes form a complete proof chain.
                portable = [
                    row for row in manifest.get('by_name', {}).get(image_name, [])
                    if isinstance(row, dict)
                    and Path(str(row.get('image_ref') or '')).name == image_name
                    and str(row.get('image_id') or '') in frozen
                ]
                if len(portable) > 1:
                    reject('IMAGE_IDENTITY_AMBIGUOUS', '归档评测图片身份不唯一')
                if len(portable) != 1:
                    reject('IMAGE_NOT_IN_SNAPSHOT', '图片不属于冻结测试集')
                portable_id = str(portable[0]['image_id'])
                source_hash = str(portable[0].get('source_content_sha256') or '').lower()
                member_hash = str(portable[0].get('content_sha256') or '').lower()
                expected_source = str(frozen[portable_id].get('content_sha256') or '').lower()
                if (not re.fullmatch(r'[0-9a-f]{64}', source_hash)
                    or source_hash != expected_source
                    or not re.fullmatch(r'[0-9a-f]{64}', member_hash)
                    or (evaluated_hash and evaluated_hash != member_hash)):
                    reject('IMAGE_HASH_MISMATCH', '归档评测图片与冻结身份不一致')
                selected_ids = [portable_id]
            elif len(stored_ids) > 1:
                reject('IMAGE_IDENTITY_AMBIGUOUS', '冻结图片文件名不唯一')
            elif len(stored_ids) == 1:
                selected_ids = stored_ids
            else:
                if snapshot_index['all_have_stored_name']:
                    reject('IMAGE_NOT_IN_SNAPSHOT', '图片不属于冻结测试集')
                # Old Snapshots without stored_name can still recover a real image,
                # but only through an exact Material stored_name match below.
                selected_ids = self._evaluation_legacy_name_index(path, repository, test_ids).get(image_name, [])
                if len(selected_ids) > 1:
                    reject('IMAGE_IDENTITY_AMBIGUOUS', '图片同名，无法唯一绑定冻结身份')
        material_rows = []
        for offset in range(0, len(selected_ids), 500):
            material_rows.extend(repository.get_many(selected_ids[offset:offset + 500]))
        candidates = [row for row in material_rows if str(row.get('id') or '') in frozen
                      and (len(selected_ids) == 1 or str(row.get('stored_name') or '') == image_name)]
        if len(candidates) > 1:
            reject('IMAGE_IDENTITY_AMBIGUOUS', '图片同名，无法唯一绑定冻结身份')
        image_id = selected_ids[0] if len(selected_ids) == 1 else str(candidates[0]['id']) if candidates else ''
        if not image_id:
            reject('ORIGINAL_IMAGE_MISSING', '原始图片索引已不存在')
        expected = str(frozen[image_id].get('content_sha256') or '').lower()
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            reject('SNAPSHOT_INCOMPLETE', '冻结图片缺少有效 SHA256')
        if not evaluated_hash:
            bound_members = [row for row in manifest.get('by_name', {}).get(image_name, [])
                             if isinstance(row, dict) and str(row.get('image_id') or '') == image_id
                             and Path(str(row.get('image_ref') or '')).name == image_name]
            if len(bound_members) == 1:
                member = bound_members[0]
                if str(member.get('source_content_sha256') or '').lower() == expected:
                    member_hash = str(member.get('content_sha256') or '').lower()
                    if re.fullmatch(r'[0-9a-f]{64}', member_hash):
                        evaluated_hash = member_hash
        from platform_core.storage.cache import file_sha256
        # Prefer the actual evaluated portable bytes. Normalization or label-scope
        # redaction can legitimately make their hash differ from the original.
        # Both source and evaluated hashes must be bound by the frozen manifest.
        preview_path = None
        if bundle is not None and manifest:
            if manifest.get('snapshot_id') == snapshot_id:
                members = [row for row in manifest.get('by_name', {}).get(image_name, [])
                           if isinstance(row, dict) and str(row.get('image_id') or '') == image_id
                           and Path(str(row.get('image_ref') or '')).name == image_name]
                if len(members) == 1:
                    member = members[0]
                    ref = str(member.get('image_ref') or '')
                    candidate = (bundle / ref).resolve()
                    preview_root = bundle
                    if not candidate.is_file():
                        retained = self.dependencies.shared_task_artifacts().artifact_path(task_id, 'evidence/bundle').resolve()
                        candidate = (retained / ref).resolve()
                        preview_root = retained
                    member_hash = str(member.get('content_sha256') or '').lower()
                    if (candidate.is_relative_to(preview_root / 'dataset' / 'images' / 'test')
                        and str(member.get('source_content_sha256') or '').lower() == expected
                        and re.fullmatch(r'[0-9a-f]{64}', member_hash)
                        and (not evaluated_hash or evaluated_hash == member_hash)
                        and candidate.is_file()):
                        if file_sha256(candidate) != member_hash:
                            reject('IMAGE_HASH_MISMATCH', '已归档评测图片内容发生变化')
                        preview_path = candidate
        if preview_path is not None:
            return verified_image_response(preview_path, 'bundle', member_hash)
        if evaluated_hash and evaluated_hash != expected:
            reject('ORIGINAL_IMAGE_MISSING', '本次评测使用了归一化图片，其原始评测字节已缺失')
        manager = self.dependencies.storage_manager(project_id)
        material = candidates[0] if candidates else None
        if material is None and hasattr(repository, 'get_by_content_sha256'):
            material = repository.get_by_content_sha256(expected)
        if material is None:
            reject('ORIGINAL_IMAGE_MISSING', '原始图片已不存在，未找到相同 SHA256 的可信对象')
        if str(material.get('content_sha256') or '').lower() != expected:
            reject('IMAGE_HASH_MISMATCH', '当前素材与冻结图片内容不同，禁止替代展示')
        try:
            resolved = manager.materialize(manager.material(str(material['id'])), read_only=True)
        except StorageError as error:
            if error.code in {'SOURCE_CONTENT_CHANGED', 'STORAGE_SHA256_MISMATCH'}:
                reject('IMAGE_HASH_MISMATCH', '存储对象与冻结图片哈希不同')
            if error.code in {'MATERIAL_NOT_FOUND', 'STORAGE_OBJECT_NOT_FOUND', 'SOURCE_UNAVAILABLE'}:
                reject('ORIGINAL_IMAGE_MISSING', '原始图片证据已不存在')
            if 'DENIED' in error.code or 'AUTH' in error.code or 'CREDENTIAL' in error.code:
                reject('ACCESS_DENIED', '当前存储凭据无法读取该图片', 403)
            reject('STORAGE_UNAVAILABLE', '图片存储暂时不可用', 503, True)
        if file_sha256(Path(resolved.path)) != expected:
            reject('IMAGE_HASH_MISMATCH', '实际图片字节与冻结 SHA256 不一致')
        return verified_image_response(Path(resolved.path), 'material', expected)

    def _advanced_evaluation_context(self, project_id: str, algorithm_id: str, version_id: str):
        from platform_core.scenario_models import resolve_scenario_model, ScenarioModelUnavailable
        algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        try:
            model = resolve_scenario_model(project_id, self.dependencies.project_dir(project_id), algorithm, version,
                self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts(), use_list_cache=True)
        except ScenarioModelUnavailable as error:
            raise HTTPException(status_code=409, detail=f"SCENARIO_MODEL_INELIGIBLE: {error}") from error
        model['current_version_id'] = str(algorithm.get('current_version_id') or '')
        return version, model

    def evaluation_trust_analysis(self, project_id: str, algorithm_id: str, version_id: str,
                                  offset: int = 0, limit: int = 20):
        if offset < 0 or not 1 <= limit <= 50:
            raise HTTPException(status_code=422, detail="可信度明细分页范围无效")
        version, model = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        result = self._advanced_trust_evidence(project_id, algorithm_id, version, model, offset=offset, limit=limit)
        return {'ok': True, 'analysis': result, 'project_id': project_id,
                'algorithm_id': algorithm_id, 'version_id': version_id}

    def evaluation_sample_page(self, project_id: str, algorithm_id: str, version_id: str,
                               offset: int = 0, limit: int = 24, issue: str = '', class_id: Optional[int] = None,
                               sort: str = 'severity', reader_view: bool=False):
        from platform_core.evaluation_analysis import evaluation_samples
        if (offset < 0 or not 1 <= limit <= 50 or issue not in {'', 'tp', 'fp', 'fn', 'wrong_class',
                'localization', 'low_confidence', 'duplicate'} or sort not in {'severity', 'high_confidence_fp'}
                or class_id is not None and class_id < 0):
            raise HTTPException(status_code=422, detail='样本筛选或分页范围无效')
        version, _ = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        evaluation = version.get('evaluation') or {}
        result = evaluation_samples(evaluation, offset=offset, limit=limit, issue=issue, class_id=class_id, sort=sort)
        if reader_view:
            from platform_core.evaluation_reader_views import samples_display
            result=samples_display(project_id,algorithm_id,version_id,result)
        return {'ok': True, 'project_id': project_id, 'algorithm_id': algorithm_id, 'version_id': version_id, **result}

    def advanced_evaluation_report(self, project_id: str, algorithm_id: str, version_id: str, reader_view: bool=False, section: str="summary", offset: int=0, limit: int=20, class_id: Optional[int]=None):
        version, model = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        if reader_view and section == 'iteration':
            from platform_core.iteration_actions import ACTION_BY_DECISION
            evaluation = version.get('evaluation') or {}
            decision = version.get('iteration_decision') or {}
            trusted = (evaluation.get('model_sha256') == model.get('model_sha256')
                       and evaluation.get('task_id') == model.get('training_task_id'))
            if not trusted:
                decision = {}
            stored = version.get('confirmed_iteration_action') or {}
            source = stored.get('source') or {}
            matching = bool(decision and source.get('decision_id') == decision.get('decision_id')
                            and source.get('evaluation_id') == evaluation.get('evaluation_id')
                            and source.get('algorithm_id') == algorithm_id and source.get('version_id') == version_id
                            and stored.get('action') == ACTION_BY_DECISION.get(decision.get('decision')))
            candidate_set = version.get('supplement_data_candidate_set') or {}
            if not matching or stored.get('action') != 'supplement_data' or candidate_set.get('action_id') != stored.get('action_id'):
                candidate_set = {}
            return {
                'ok': True, 'project_id': project_id, 'algorithm_id': algorithm_id, 'version_id': version_id,
                'current_version_id': model['current_version_id'],
                'evaluation_id': evaluation.get('evaluation_id'), 'model_sha256': model.get('model_sha256'),
                'decision': {key: decision[key] for key in ('decision_id', 'decision', 'weak_labels') if key in decision},
                'action': ({'action_id': stored.get('action_id'), 'action': stored.get('action'),
                            'status': stored.get('status'), 'automatic_execution': stored.get('automatic_execution'),
                            'source': source, 'training_draft': {'task_id': (stored.get('training_draft') or {}).get('task_id')}}
                           if matching else None),
                'candidate_set': ({'candidate_set_id': candidate_set.get('candidate_set_id'),
                                   'material_ids': candidate_set.get('material_ids') or []} if candidate_set else None),
            }
        if reader_view:
            if section not in {'summary','classes','curves','confusion'} or offset<0 or not 1<=limit<=100 or class_id is not None and class_id<0:raise HTTPException(422,detail='评测报告分段范围无效')
            from platform_core.evaluation_reader_views import report_section
            return {'ok':True,'project_id':project_id,'algorithm_id':algorithm_id,'version_id':version_id,**report_section(version.get('evaluation') or {},section,offset,limit,class_id)}
        # All-cohort outcomes are available only via the paged sample endpoint.
        evaluation = {key: value for key, value in (version.get('evaluation') or {}).items()
                      if key not in {'sample_outcomes', 'sample_evidence'}}
        public = {key: version[key] for key in ('id', 'version_name', 'iteration_decision',
                  'confirmed_iteration_action', 'supplement_data_candidate_set', 'feedback_adoption_outcome') if key in version}
        public['evaluation'] = evaluation
        return {'ok': True, 'algorithm': {'id': algorithm_id, 'current_version_id': model.get('current_version_id', ''), 'versions': [public]}}

    def compare_version_evaluation(self, project_id: str, algorithm_id: str, version_id: str, other_version_id: str, reader_view: bool=False, offset: int=0, limit: int=20):
        from platform_core.training_evaluation import compare_evaluations
        _, current = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        _, previous = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, other_version_id)
        result = compare_evaluations(previous.get('evaluation') or {}, current.get('evaluation') or {})
        before_params = (previous.get('training_lineage') or {}).get('parameters') or {}
        after_params = (current.get('training_lineage') or {}).get('parameters') or {}
        # Only public training parameters; never return model paths or storage secrets.
        allowed = ('epochs', 'imgsz', 'batch', 'workers', 'precision', 'optimizer', 'lr0')
        before = before_params.get('actual') or {}
        after = after_params.get('actual') or {}
        result['parameter_differences'] = {key: {'before': before.get(key), 'after': after.get(key)}
                                           for key in allowed if before.get(key) != after.get(key)}
        result.update(source_version_id=other_version_id, current_version_id=version_id)
        if reader_view:
            if offset<0 or not 1<=limit<=100:raise HTTPException(422,detail='版本比较分页范围无效')
            from platform_core.evaluation_reader_views import comparison_display
            return {'ok':True,'project_id':project_id,'algorithm_id':algorithm_id,'version_id':version_id,'comparison':comparison_display(result,offset,limit)}
        return {'ok': True, 'comparison': result}

    def deep_compare_evaluation(self, project_id: str, algorithm_id: str, version_id: str, other_version_id: str,
                                offset: int = 0, limit: int = 24, category: str = ''):
        from platform_core.evaluation_analysis import compare_sample_outcomes
        if offset < 0 or not 1 <= limit <= 50 or category not in {'', 'improved', 'regressed',
                'persistent_error', 'persistent_correct', 'unknown'} or version_id == other_version_id:
            raise HTTPException(status_code=422, detail='版本对比范围无效')
        current, current_model = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        previous, previous_model = self._advanced_evaluation_context(project_id, algorithm_id, other_version_id)
        for version, model in ((current, current_model), (previous, previous_model)):
            evidence = version.get('evaluation') or {}
            if (evidence.get('model_sha256') != model.get('model_sha256')
                    or evidence.get('task_id') != model.get('training_task_id')):
                raise HTTPException(status_code=409, detail='评测与正式模型任务身份不一致')
        trust_checks = [check for version, model in ((current, current_model), (previous, previous_model))
                        for check in self._advanced_trust_evidence(project_id, algorithm_id, version, model)['checks']]
        blocking = [check['code'] for check in trust_checks if check['status'] == 'risk'
                    or check['code'] == 'identity' and check['status'] != 'passed']
        if blocking:
            return {'ok': True, 'comparison': {'comparable': False, 'reason_codes': ['benchmark_trust_not_verified'],
                    'blocking_checks': sorted(set(blocking)), 'metrics': {}, 'classes': [], 'samples': [],
                    'source_version_id': other_version_id, 'current_version_id': version_id}}
        result = compare_sample_outcomes(previous.get('evaluation') or {}, current.get('evaluation') or {},
                                        offset=offset, limit=limit, category=category)
        result.update(source_version_id=other_version_id, current_version_id=version_id)
        result['trust_warnings'] = sorted({check['code'] for check in trust_checks if check['status'] != 'passed'})
        return {'ok': True, 'comparison': result}

    def preview_reviewed_mining(self, project_id: str, algorithm_id: str, version_id: str, task_id: str, offset: int = 0, limit: int = 24):
        if offset < 0 or not 1 <= limit <= 50:
            raise HTTPException(status_code=422, detail='审核候选分页范围无效')
        items = self._reviewed_mining_candidates(project_id, algorithm_id, version_id, task_id, offset=offset, limit=limit)
        return {'ok': True, 'items': items, 'offset': offset, 'limit': limit, 'has_more': len(items) == limit,
                'automatic_execution': False, 'requires_confirmation': True}

    def adopt_reviewed_mining(self, project_id: str, algorithm_id: str, version_id: str, task_id: str, payload: FreezeReviewedMiningReq):
        if not payload.confirmed or not 1 <= len(payload.candidates) <= 50:
            raise HTTPException(status_code=422, detail='请选择1至50项并明确确认采纳')
        requested = {row.image_id: row.candidate_digest for row in payload.candidates}
        if len(requested) != len(payload.candidates):
            raise HTTPException(status_code=422, detail='采纳候选不能重复')
        self._supplement_data_action(project_id, algorithm_id, version_id)
        with self.dependencies._storage_source_fence():
            items = self._reviewed_mining_candidates(project_id, algorithm_id, version_id, task_id, image_ids=list(requested))
            if any(not row['eligible'] or row['candidate_digest'] != requested[row['image_id']] for row in items):
                raise HTTPException(status_code=409, detail='审核候选、素材或正式GT已变化，请重新预览')
            repository = self.dependencies._online_feedback_repository(project_id)
            selections = []
            for item in items:
                staged, _ = repository.stage(item['evidence'], feedback_type='needs_correction',
                    note=f"人工审核困难样本 · {task_id}", created_at=self.dependencies.now_iso())
                finalized, _ = repository.finalize(staged['id'], expected_feedback_type='needs_correction',
                    material_id=item['image_id'], result={'annotation_action': 'reviewed_existing_gt',
                    'formal_gt_changed': False, 'source_task_id': task_id, 'automatic_execution': False}, confirmed_at=self.dependencies.now_iso())
                candidate = self._supplement_feedback_candidates(project_id, [finalized])[0]
                if not candidate['eligible']:
                    raise HTTPException(status_code=409, detail='审核候选尚不可训练')
                selections.append(SupplementFeedbackCandidateSelection(feedback_id=candidate['feedback_id'], candidate_digest=candidate['candidate_digest']))
            return self.freeze_supplement_feedback_candidates(project_id, algorithm_id, version_id,
                FreezeSupplementFeedbackCandidatesReq(candidates=selections))

    def _evaluation_sample_review_source(self, project_id: str, algorithm_id: str, version_id: str, evaluation_id: str, image_id: str):
        version, model = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        evaluation = version.get('evaluation') or {}
        if evaluation.get('evaluation_id') != evaluation_id or not re.fullmatch(r'[a-f0-9]{64}', evaluation_id):
            raise HTTPException(status_code=409, detail='评测身份已变化，请重新读取报告')
        if evaluation.get('model_sha256') != model.get('model_sha256') or evaluation.get('task_id') != model.get('training_task_id'):
            raise HTTPException(status_code=409, detail='评测模型与正式任务身份不一致')
        samples = evaluation.get('sample_outcomes') or evaluation.get('error_samples') or []
        matches = [row for row in samples if str(row.get('image_id') or '') == image_id]
        if len(matches) != 1:
            raise HTTPException(status_code=409, detail='冻结样本身份不唯一或未保存')
        sample = matches[0]
        # Persist only an opinion in the existing feedback owner. No image/GT write.
        prediction_id = 'evalreview_' + hashlib.sha256((evaluation_id + ':' + image_id).encode()).hexdigest()[:48]
        return {'schema_version': 1, 'prediction_id': prediction_id, 'project_id': project_id,
                  'algorithm_id': algorithm_id,
                  'version_id': version_id, 'model_sha256': model['model_sha256'],
                  'input_sha256': sample.get('image_content_sha256'), 'width': sample.get('image_width'),
                  'height': sample.get('image_height'), 'detections': [], 'engine': 'formal_evaluation',
                  'original_filename': sample.get('image'), 'input_file': '', 'created_at': evaluation.get('finished_at', ''),
                  'source_channel': 'evaluation', 'external_source': evaluation_id,
                  'external_sample_id': image_id}

    def read_evaluation_sample_review(self, project_id: str, algorithm_id: str, version_id: str, expected_evaluation_id: str, image_id: str):
        from platform_core.online_feedback import public_feedback
        source = self._evaluation_sample_review_source(project_id, algorithm_id, version_id, expected_evaluation_id, image_id)
        row = self.dependencies._online_feedback_repository(project_id).get_by_prediction(source['prediction_id'])
        if row is None:
            return {'ok': True, 'feedback': None}
        feedback = public_feedback(row)
        if any(feedback[key] != source[key] for key in ('project_id', 'algorithm_id', 'version_id', 'model_sha256', 'input_sha256')):
            raise HTTPException(409, detail='复核记录与冻结样本身份不一致')
        return {'ok': True, 'feedback': feedback}

    def review_evaluation_sample(self, project_id: str, algorithm_id: str, version_id: str, payload: EvaluationReviewReq):
        from platform_core.online_feedback import public_feedback
        if payload.observation not in {'', 'model_error', 'gt_error', 'model_correct', 'unknown', 'hard_sample'} or len(payload.note) > 1000:
            raise HTTPException(status_code=422, detail='复核意见无效')
        source = self._evaluation_sample_review_source(project_id, algorithm_id, version_id, payload.expected_evaluation_id, payload.image_id)
        repository = self.dependencies._online_feedback_repository(project_id)
        try:
            row, reused = repository.stage(source, feedback_type='needs_correction', note=payload.note, created_at=self.dependencies.now_iso())
            if payload.observation and payload.observation != 'unknown':
                row, reused = repository.finalize(row['id'], expected_feedback_type='needs_correction',
                    material_id='', result={'review_observation': payload.observation, 'formal_gt_changed': False,
                        'evaluation_id': payload.expected_evaluation_id, 'image_id': payload.image_id,
                        'frozen_test_protected': True, 'automatic_execution': False, 'requires_confirmation': True},
                    confirmed_at=self.dependencies.now_iso())
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {'ok': True, 'idempotent': reused, 'feedback': public_feedback(row),
                'automatic_execution': False, 'requires_confirmation': True, 'frozen_test_protected': True}

    def eligible_hard_sample_materials(self, project_id: str, algorithm_id: str, version_id: str, limit: int = 100):
        'A bounded read-only filter over canonical Materials and frozen Test truth.\n\n    This is not a separate candidate database. Final POST revalidates everything.\n    '
        from platform_core.hard_sample_mining import (
            HardSampleSafetyError, frozen_test_identifiers,
        )
        self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        count = max(1, min(100, int(limit)))
        try:
            blocked_ids, blocked_hashes = frozen_test_identifiers(self.dependencies.project_dir(project_id))
        except HardSampleSafetyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        materials = self.dependencies.material_store(project_id)
        eligible: list[str] = []
        display_items = []
        cursor = None
        # Two fixed 500-ID pages: no unbounded Material scan on the API thread.
        for _ in range(2):
            page = materials.list_ids(cursor=cursor, limit=500, annotated=False)
            ids = [str(value) for value in page.items if str(value) and str(value) not in blocked_ids]
            for offset in range(0, len(ids), 500):
                for item in materials.get_many(ids[offset:offset + 500]):
                    image_id = str(item.get("id") or "")
                    digest = str(item.get("content_sha256") or "").lower()
                    if (image_id in blocked_ids or digest in blocked_hashes
                        or not re.fullmatch(r"[0-9a-f]{64}", digest)
                        or item.get("source_available") is False):
                        continue
                    eligible.append(image_id)
                    display_items.append({'image_id': image_id, 'filename': item.get('original_name') or item.get('stored_name'),
                                          'content_sha256': digest})
                    if len(eligible) >= count:
                        break
                if len(eligible) >= count:
                    break
            if len(eligible) >= count or not page.next_cursor:
                break
            cursor = page.next_cursor
        return {"items": eligible, "display_items": display_items, "returned": len(eligible), "limit": count}

    def create_hard_sample_mining(self, project_id: str, algorithm_id: str, version_id: str,
                                  payload: HardSampleMiningCreateReq):
        return self._enqueue_hard_sample_mining(
            project_id, algorithm_id, version_id, payload.image_ids,
            source=payload.source, request_key=payload.request_key,
            expected_model_sha256=payload.expected_model_sha256, expected_source_hashes=payload.expected_source_hashes,
        )

    def _enqueue_hard_sample_mining(self,
        project_id: str, algorithm_id: str, version_id: str, image_ids: Sequence[str],
        *, source: str, request_key: str = "",
        expected_model_sha256: str = "", expected_source_hashes: dict[str, str] | None = None,
    ):
        from platform_core.hard_sample_mining import (
            HardSampleSafetyError, assert_not_frozen_test, sha256_file,
        )
        from platform_core.task_runtime import TaskRecord, TaskKind
        if source not in {"existing", "upload"}:
            raise HTTPException(status_code=422, detail="困难样本来源无效")
        algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        path = self.dependencies._testable_version_pt_path(version)
        if path is None:
            raise HTTPException(status_code=409, detail="当前算法版本没有可用的本地正式 PT，不能挖掘")
        requested = list(dict.fromkeys(str(value).strip() for value in image_ids if str(value).strip()))
        if not requested or len(requested) > 500:
            raise HTTPException(status_code=422, detail="单次困难样本挖掘必须选择 1 至 500 张素材")
        rows = []
        for offset in range(0, len(requested), 500):
            rows.extend(self.dependencies.material_store(project_id).get_many(requested[offset:offset + 500]))
        by_id = {str(row.get("id") or ""): row for row in rows}
        if set(by_id) != set(requested):
            raise HTTPException(status_code=409, detail="选择的素材已经变化或不存在，请刷新")
        source_hashes = {key: str(by_id[key].get("content_sha256") or "").strip().lower() for key in requested}
        if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in source_hashes.values()):
            raise HTTPException(status_code=409, detail="素材缺少可信内容 SHA256，无法挖掘")
        if any(by_id[key].get("source_available") is False
               or by_id[key].get("dataset_delete_claim")
               or by_id[key].get("material_batch_delete_claim") for key in requested):
            raise HTTPException(status_code=409, detail="素材处于不可用或删除状态")
        if source == "upload" and any(
            str(by_id[key].get("annotation_state") or "").lower() in {"annotated", "confirmed_empty"}
            or int(by_id[key].get("box_count") or 0) > 0 for key in requested
        ):
            raise HTTPException(status_code=409, detail="上传自动筛选仅允许未标注的正式素材")
        try:
            assert_not_frozen_test(self.dependencies.project_dir(project_id), requested, source_hashes)
        except HardSampleSafetyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        # Scope a human confirmation to the source model's TRAINING schema,
        # not every label on the project. Never mis-mark unrelated labels empty.
        snapshot_id = str(version.get("snapshot_id") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise HTTPException(status_code=409, detail="算法版本缺少可信训练标签快照")
        snapshot_path = self.dependencies.project_dir(project_id) / "snapshots" / f"{snapshot_id}.json"
        source_snapshot = self.dependencies.read_json(snapshot_path, {}) if snapshot_path.is_file() else {}
        if (not isinstance(source_snapshot, dict)
            or source_snapshot.get("snapshot_id") != snapshot_id
            or not isinstance(source_snapshot.get("label_schema"), list)):
            raise HTTPException(status_code=409, detail="算法版本的冻结标签结构无法验证")
        labels = list(dict.fromkeys(
            str(row.get("code") or "").strip()
            for row in source_snapshot["label_schema"]
            if isinstance(row, dict) and str(row.get("code") or "").strip()
        ))
        active_codes = {
            str(row.get("code") or "")
            for row in self.dependencies._annotation_label_catalog(self.dependencies.get_project(project_id))
        }
        if not labels or not set(labels).issubset(active_codes):
            raise HTTPException(status_code=409, detail="冻结模型标签与当前 canonical 标签不一致，请先核查")
        snapshot_hash = sha256_file(snapshot_path)
        digest = sha256_file(path)
        if expected_model_sha256 and digest != expected_model_sha256:
            raise HTTPException(409, detail='困难样本的来源模型已变化')
        if expected_source_hashes is not None and source_hashes != expected_source_hashes:
            raise HTTPException(409, detail='困难样本素材代际已变化')
        identity = {
            "algorithm_id": str(algorithm_id),
            "version_id": str(version_id),
            "model_sha256": digest,
            "image_ids": requested,
            "source_hashes": source_hashes,
            "source": source,
            "request_key": str(request_key or "")[:120],
        }
        # Deduplicate retry for the same upload receipt without adding another
        # persistent idempotency table. The existing TaskRepository remains truth.
        key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        task_id = "hm" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:14] if request_key else "hm" + uuid.uuid4().hex[:14]
        repository = self.dependencies.shared_task_repository()
        request = {
            "schema_version": 2,
            "mode": "hard_sample_yolo",
            "source": source,
            "task_name": "YOLO 困难样本挖掘",
            "image_ids": requested,
            "source_hashes": source_hashes,
            "labels": labels,
            "overwrite": False,
            "mining_algorithm_id": str(algorithm_id),
            "mining_version_id": str(version_id),
            "mining_model_path": str(path),
            "mining_model_sha256": digest,
            "mining_snapshot_id": snapshot_id,
            "mining_snapshot_sha256": snapshot_hash,
            "source_request_key": str(request_key or "")[:120],
        }
        with self.dependencies._storage_source_fence():
            previous = repository.get(task_id)
            if previous is not None:
                if previous.project_id != project_id or previous.kind is not TaskKind.AI_ANNOTATION:
                    raise HTTPException(status_code=409, detail="困难样本任务身份冲突")
                return self.dependencies.public_annotation_task(previous)
            self.dependencies.shared_task_artifacts().atomic_write_json(task_id, "request.json", request)
            task = repository.create(TaskRecord.new(
                task_id, project_id, TaskKind.AI_ANNOTATION,
                "request.json", f"mining:{digest[:16]}",
                priority=60, required_capabilities=("mining.ultralytics",),
            ))
        return self.dependencies.public_annotation_task(task)

    def v49_algorithm_report(self, project_id: str, algorithm_id: str, lightweight: bool = False):
        algo = next((x for x in self.dependencies.list_algorithms_internal(project_id, algorithm_id=algorithm_id) if x.get('id') == algorithm_id), None)
        if not algo:
            raise HTTPException(status_code=404, detail='算法不存在')
        rows, repository, durable = self.dependencies._training_history_context(project_id)
        canonical = {}
        for row in rows:
            if row.get('project_id') and str(row['project_id']) != str(project_id):
                continue
            identity = str(row.get('task_id') or row.get('id') or '').strip()
            if identity and (identity not in canonical or str(row.get('id') or '') == identity):
                canonical[identity] = dict(row)
        for identity, task in durable.items():
            if identity not in canonical:
                # The existing task-owned payload restores archived task identity;
                # it does not invent missing runtime duration or report evidence.
                key = (str(repository.path), identity)
                with self.dependencies._TRAINING_JOB_PROJECTION_LOCK():
                    cached = self.dependencies._TRAINING_COUNT_PAYLOADS().get(key)
                    if cached is None or cached[0] != task.updated_at:
                        payload = self.dependencies.shared_task_artifacts().read_json(identity, task.payload_ref, default={})
                        self.dependencies._TRAINING_COUNT_PAYLOADS()[key] = (task.updated_at, payload)
                    else:
                        payload = cached[1]
                if isinstance(payload, dict):
                    canonical[identity] = {**payload, 'id': identity, 'task_id': identity}
        jobs = []
        for identity, row in canonical.items():
            task = durable.get(identity)
            kind = task.kind.value if task else str(row.get('task_kind') or row.get('kind') or 'TRAINING').upper()
            if kind != 'TRAINING' or row.get('never_started'):
                continue
            if str(row.get('asset_algorithm_id') or row.get('algorithm_asset_id') or '') != str(algorithm_id):
                continue
            row['id'] = identity
            if task:
                row['status'] = task.status.value
                row['task_status'] = task.status.value
                row.setdefault('created_at', task.created_at)
                if task.finished_at:
                    row.setdefault('finished_at', task.finished_at)
            jobs.append(row)
        jobs.sort(key=lambda x: str(x.get('finished_at') or x.get('created_at') or ''))
        trend=[]; total_label_counts: Dict[str,int]={}; duration=0; duration_records=0
        for j in jobs:
            rep=j.get('training_report') or {}
            m=self._v49_metric_from_report(rep,'metrics/mAP50(B)','map50','mAP50')
            if m is None:
                try: m=float((j.get('metrics') or {}).get('map50'))
                except Exception: m=None
            # Historical label counts are expensive when frozen project Snapshots
            # are unavailable: the legacy helper reopens mutable annotations for
            # every selected image of every attempt. The report workbench requests
            # lightweight=True to preserve truthful, fast historical metadata.
            lc = {} if lightweight else self._v49_job_label_counts(project_id, j)
            for k, v in lc.items():
                total_label_counts[k] = total_label_counts.get(k, 0) + int(v)
            elapsed = j.get('elapsed_seconds')
            try:
                measured = float(elapsed) if elapsed is not None and elapsed != '' and not isinstance(elapsed, bool) else None
            except (TypeError, ValueError, OverflowError):
                measured = None
            if measured is not None and math.isfinite(measured) and measured >= 0:
                duration += measured
                duration_records += 1
            trend.append({'job_id':j.get('id'),'version':j.get('auto_version_name') or '', 'finished_at':j.get('finished_at') or j.get('updated_at') or j.get('created_at'), 'map50':m, 'status':j.get('status'), 'labels':lc, 'images':int((j.get('dataset_counts') or {}).get('train') or 0)})
        versions=algo.get('versions') or []
        current_id=str(algo.get('current_version_id') or '')
        current=next((v for v in versions if str(v.get('id') or '')==current_id), versions[0] if versions else None)
        aggregate=build_algorithm_report(versions)
        val_by_version_id = {str(item.get('version_id')): item.get('map50') for item in aggregate['trend']}
        # Summaries are derived only from immutable/current-version catalog facts.
        # Never infer historical Test quality from a Val mAP or mutable GT.
        quality_rows = []
        for version in sorted(versions, key=lambda v: str(
            v.get('finished_at') or v.get('created_at') or v.get('version_name') or ''
        ))[-40:]:
            evaluation = version.get('evaluation') or {}
            if not isinstance(evaluation, dict):
                evaluation = {}
            ev_metrics = evaluation.get('metrics') or {}
            if not isinstance(ev_metrics, dict):
                ev_metrics = {}
            test_map50 = self._v49_metric_from_report(
                {'metrics': ev_metrics}, 'metrics/mAP50(B)', 'map50', 'mAP50'
            ) if evaluation.get('status') == 'succeeded' else None
            quality_rows.append({
                'version_id': version.get('id'),
                'version_name': version.get('version_name') or '',
                'finished_at': version.get('finished_at') or version.get('created_at') or '',
                'val_map50': val_by_version_id.get(str(version.get('id') or '')),
                'test_map50': test_map50,
                'test_status': evaluation.get('status') or 'unavailable',
                'test_snapshot_id': evaluation.get('snapshot_id') or '',
                'train_snapshot_id': version.get('snapshot_id') or '',
                'is_current': str(version.get('id') or '') == current_id,
            })
        current_quality = next(
            (row for row in quality_rows if row['is_current']), None
        )
        latest_created = max((row for row in versions if row.get('created_at')),
                             key=lambda row: str(row['created_at']), default=None)
        success = self.dependencies._successful_training_counts(project_id, history_context=(rows, repository, durable)).get(str(algorithm_id), 0)
        return {'ok':True,'report_type':'algorithm','latest_vs_previous':aggregate['latest_vs_previous'],'best_version':aggregate['best_version'],'best_map50':aggregate['best_map50'],'version_trend':aggregate['trend'],'algorithm':{'id':algo.get('id'),'name':algo.get('name'),'industry':algo.get('industry') or '', 'algorithm_type':algo.get('algorithm_type') or '', 'remark':algo.get('remark') or '', 'version_count':len(versions),'current_version_id':current_id}, 'summary':{'training_count':success,'successful_count':success,'attempt_count':len(jobs),'duration_scope':'all_training_attempts_including_failed','duration_record_count':duration_records,'duration_unknown_count':len(jobs)-duration_records,'total_duration_seconds':int(duration),'avg_duration_seconds':int(duration/duration_records) if duration_records else 0,'label_counts':total_label_counts,
           'label_counts_scope': 'not_computed_fast' if lightweight else 'cumulative_training_boxes',
           'latest_version':current.get('version_name') if current else '', 'current_version':current.get('version_name') if current else '', 'latest_accuracy': val_by_version_id.get(str(current.get('id') or '')) if current else None}, 'trend':trend, 'jobs':trend[-20:] if lightweight else jobs[-20:],'jobs_total':len(jobs),'jobs_limit':20,
                'jobs_truncated':len(jobs)>20,
                'version_quality':quality_rows,
                'version_quality_total':len(versions),
                'version_quality_truncated':len(versions)>40,
                'current_quality':current_quality,
                'latest_created_version': ({key: latest_created.get(key) for key in ('id', 'version_name', 'created_at')}
                                           if latest_created else None)}

    def _advanced_trust_evidence(self, project_id, algorithm_id, version, model, *, offset=0, limit=20):
        from platform_core.evaluation_analysis import analyze_evaluation_trust, append_historical_test_independence
        from platform_core.training_material_usage import TrainingMaterialUsage
        evaluation = version.get('evaluation') or {}
        snapshot_id = str(evaluation.get('snapshot_id') or '')
        snapshot = {}
        if re.fullmatch(r'[a-f0-9]{64}', snapshot_id):
            snapshot = self.dependencies.read_json(self.dependencies.project_dir(project_id) / 'snapshots' / f'{snapshot_id}.json', {})
        analysis = analyze_evaluation_trust(evaluation, snapshot, version, verified_model=model,
                                            detail_offset=offset, detail_limit=limit)
        ancestry = (version.get('training_lineage') or {}).get('model_ancestry') or []
        return append_historical_test_independence(
            analysis, snapshot, TrainingMaterialUsage(self.dependencies.shared_task_repository()), project_id, algorithm_id,
            offset=offset, limit=limit,
            parent_task_ids=[str(item.get('task_id') or '') for item in ancestry if isinstance(item, dict) and item.get('task_id')])

    def _v49_job_label_counts(self, project_id: str, job: Dict[str, Any]) -> Dict[str, int]:
        snapshot_id = str(job.get('snapshot_id') or '').strip().lower()
        if re.fullmatch(r'[0-9a-f]{64}', snapshot_id):
            snapshot = self.dependencies.read_json(self.dependencies.project_dir(project_id) / 'snapshots' / f'{snapshot_id}.json', {})
            if (
                isinstance(snapshot, dict)
                and str(snapshot.get('snapshot_id') or '').strip().lower() == snapshot_id
                and isinstance(snapshot.get('label_counts'), dict)
            ):
                counts: Dict[str, int] = {}
                for label, value in snapshot['label_counts'].items():
                    code = str(label or '').strip()
                    try:
                        count = int(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if code and count > 0:
                        counts[code] = count
                return counts

        selected = job.get('dataset_selected_ids') or {}
        ids = list(dict.fromkeys(
            str(value).strip()
            for value in (
                selected.get('train')
                or selected.get('train_image_ids')
                or (job.get('data_summary') or {}).get('selected_ids', {}).get('train')
                or []
            )
            if str(value).strip()
        ))
        annotations: Dict[str, Dict[str, Any]] = {}
        for offset in range(0, len(ids), 500):
            annotations.update(self.dependencies.read_annotations_many(project_id, ids[offset:offset + 500]))
        counts: Dict[str, int] = {}
        for image_id in ids:
            ann = annotations.get(image_id) or {}
            for box in ann.get('boxes', []):
                label = str(box.get('label') or '').strip()
                if label:
                    counts[label] = counts.get(label, 0) + 1
        return counts

    def _v49_metric_from_report(self, report: Dict[str, Any], *keys: str):
        metrics = report.get('metrics') or {}
        for key in keys:
            if key in metrics and metrics.get(key) is not None:
                try: return float(metrics.get(key))
                except Exception: pass
        return None

    def _reviewed_mining_candidates(self, project_id, algorithm_id, version_id, task_id, *, offset=0, limit=24, image_ids=None):
        from itertools import islice
        from platform_core.hard_sample_mining import reviewed_mining_feedback_evidence, assert_not_frozen_test
        _, model = self._advanced_evaluation_context(project_id, algorithm_id, version_id)
        task = self.dependencies._require_annotation_review_task(project_id, task_id)
        if task.kind is not TaskKind.AI_ANNOTATION or task.status is not TaskStatus.SUCCEEDED or not task.result_ref:
            raise HTTPException(status_code=409, detail='困难样本任务尚未完成正式人工审核入库')
        artifacts = self.dependencies.shared_task_artifacts()
        request = artifacts.read_json(task_id, task.payload_ref, default={})
        if (request.get('mode') != 'hard_sample_yolo' or request.get('mining_algorithm_id') != algorithm_id
                or request.get('mining_version_id') != version_id or request.get('mining_model_sha256') != model.get('model_sha256')):
            raise HTTPException(status_code=409, detail='困难样本任务来源模型不匹配')
        store = CandidateStore(artifacts, task_id=task_id)
        if not store.path.is_file():
            raise HTTPException(status_code=409, detail='已审核候选索引不可用，不自动重建历史审核事实')
        items = list(store.get_many(image_ids).values()) if image_ids is not None else list(islice(store.iter_accepted_items(include_committed=True), offset, offset + limit))
        ids = [str(row.get('image_id') or '') for row in items]
        if image_ids is not None and set(ids) != set(image_ids):
            raise HTTPException(status_code=409, detail='部分候选已不存在')
        materials = {str(row['id']): row for row in self.dependencies.material_store(project_id).get_many(ids)}
        annotations = AnnotationRepository(self.dependencies.project_dir(project_id)).get_many(ids)
        journals = store.get_commit_summaries(ids)
        try:
            if ids:
                assert_not_frozen_test(self.dependencies.project_dir(project_id), ids, {key: row.get('content_sha256', '') for key, row in materials.items()})
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        result = []
        for item in items:
            image_id = str(item.get('image_id') or '')
            try:
                evidence = reviewed_mining_feedback_evidence(task_id=task_id, request=request, candidate=item,
                    material=materials.get(image_id) or {}, annotation=annotations.get(image_id) or {},
                    commit_summary=journals.get(image_id), project_id=project_id)
                result.append({'image_id': image_id, 'eligible': True, **evidence})
            except ValueError as error:
                result.append({'image_id': image_id, 'eligible': False, 'reason': str(error)})
        return result

    def _supplement_data_action(self,
        project_id: str, algorithm_id: str, version_id: str,
    ):
        algorithm, version = self.dependencies._algorithm_version_for_action(project_id, algorithm_id, version_id)
        if str(algorithm.get("current_version_id") or "") != str(version_id):
            raise HTTPException(status_code=409, detail="补数据候选只能基于算法当前版本，请刷新后重试")
        action = version.get("confirmed_iteration_action")
        source = dict(action.get("source") or {}) if isinstance(action, dict) else {}
        if (
            not isinstance(action, dict)
            or str(action.get("status") or "") != "confirmed"
            or str(action.get("action") or "") != "supplement_data"
            or str(source.get("algorithm_id") or "") != str(algorithm_id)
            or str(source.get("version_id") or "") != str(version_id)
        ):
            raise HTTPException(status_code=409, detail="当前版本没有已确认的补数据动作")
        return algorithm, version, action

    def _supplement_feedback_candidates(self, project_id: str, feedback_rows):
        from platform_core.online_feedback import build_supplement_candidate
        materials = self.dependencies.material_store(project_id)
        material_ids = [
            str(row.get("material_id") or "")
            for row in feedback_rows
            if str(row.get("material_id") or "")
        ]
        material_rows = {
            str(row.get("id") or ""): row
            for row in materials.get_many(material_ids)
        }
        annotations = AnnotationRepository(self.dependencies.project_dir(project_id))
        annotation_rows = annotations.get_many(list(material_rows)) if material_rows else {}
        return [
            build_supplement_candidate(
                row,
                material_rows.get(str(row.get("material_id") or "")),
                annotation_rows.get(str(row.get("material_id") or "")),
            )
            for row in feedback_rows
        ]

    def list_supplement_feedback_candidates(self,
        project_id: str, algorithm_id: str, version_id: str,
    ):
        _, version, action = self._supplement_data_action(project_id, algorithm_id, version_id)
        repository = self.dependencies._online_feedback_repository(project_id)
        rows, total = repository.list_confirmed_for_version(algorithm_id, version_id, limit=500)
        candidates = self._supplement_feedback_candidates(project_id, rows)
        eligible = sum(1 for row in candidates if row.get("eligible") is True)
        annotation_required = sum(
            1 for row in candidates if "ANNOTATION_REQUIRED" in set(row.get("reason_codes") or [])
        )
        return {
            "ok": True,
            "action_id": str(action.get("action_id") or ""),
            "total": total,
            "returned": len(candidates),
            "truncated": total > len(candidates),
            "eligible": eligible,
            "annotation_required": annotation_required,
            "items": candidates,
            "candidate_set": version.get("supplement_data_candidate_set"),
        }

    def freeze_supplement_feedback_candidates(self,
        project_id: str, algorithm_id: str, version_id: str,
        payload: FreezeSupplementFeedbackCandidatesReq,
    ):
        from filelock import FileLock
        from platform_core.online_feedback import build_supplement_candidate_set

        _, _, action = self._supplement_data_action(project_id, algorithm_id, version_id)
        requested = {
            str(row.feedback_id): str(row.candidate_digest).strip().lower()
            for row in payload.candidates
        }
        if len(requested) != len(payload.candidates):
            raise HTTPException(status_code=409, detail="补数据候选包含重复 feedback ID")
        if any(
            len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
            for digest in requested.values()
        ):
            raise HTTPException(status_code=400, detail="补数据候选 digest 无效")

        repository = self.dependencies._online_feedback_repository(project_id)
        feedback_rows = repository.get_many(requested)
        if len(feedback_rows) != len(requested):
            raise HTTPException(status_code=409, detail="部分补数据反馈已经不存在，请刷新后重试")
        for row in feedback_rows:
            if (
                str(row.get("status") or "") != "confirmed"
                or str(row.get("algorithm_id") or "") != str(algorithm_id)
                or str(row.get("version_id") or "") != str(version_id)
            ):
                raise HTTPException(status_code=409, detail="补数据反馈状态或版本已经变化，请刷新后重试")

        candidates = self._supplement_feedback_candidates(project_id, feedback_rows)
        by_id = {str(row["feedback_id"]): row for row in candidates}
        for feedback_id, digest in requested.items():
            candidate = by_id.get(feedback_id)
            if candidate is None or str(candidate.get("candidate_digest") or "") != digest:
                raise HTTPException(status_code=409, detail="补数据候选素材或标注已经变化，请刷新后重试")
            if candidate.get("eligible") is not True:
                raise HTTPException(status_code=409, detail="所选反馈尚未具备可训练的正式标注，请先完成复核")
        try:
            candidate_set = build_supplement_candidate_set(
                action,
                [by_id[feedback_id] for feedback_id in requested],
                frozen_at=self.dependencies.now_iso(),
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        lock_path = str(self.dependencies.algorithms_file(project_id).resolve()) + ".supplement-feedback.lock"
        with FileLock(lock_path, timeout=30):
            _, latest_version, latest_action = self._supplement_data_action(
                project_id, algorithm_id, version_id,
            )
            if str(latest_action.get("action_id") or "") != str(candidate_set["action_id"]):
                raise HTTPException(status_code=409, detail="补数据动作已经变化，请刷新后重试")
            previous = latest_version.get("supplement_data_candidate_set")
            if isinstance(previous, dict) and str(previous.get("candidate_set_id") or ""):
                if str(previous.get("candidate_set_id")) == candidate_set["candidate_set_id"]:
                    return {"ok": True, "idempotent": True, "candidate_set": previous}
                raise HTTPException(status_code=409, detail="该版本已经冻结另一组补数据候选，不能覆盖")
            stored = update_algorithm_version(
                self.dependencies.algorithms_file(project_id), algorithm_id, version_id,
                {"supplement_data_candidate_set": candidate_set},
                now=self.dependencies.now_iso(),
            )
        return {
            "ok": True,
            "idempotent": False,
            "candidate_set": stored.get("supplement_data_candidate_set") or candidate_set,
        }
