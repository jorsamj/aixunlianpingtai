"""Read-only training report projections (v44 job/version report).

Moved out of ``app.py``.  This module owns the HTTP surface of
``GET /api/v44/projects/{project_id}/jobs/{job_id}/report`` (both the legacy
``version`` composition and the Task-owned ``reader_view`` display), plus the
``results.csv`` history fallback that only that report uses.

It is a read projection, not a second owner: the durable TaskRecord/artifact
store stays the authority for finalized report evidence, the algorithm catalog
stays the authority for version identity, and the host application injects all
of those accessors through :func:`create_training_report_router`.  Nothing here
imports ``app``, writes report state, or opens a second repository.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, HTTPException

from platform_core.algorithm_repository import open_algorithm_repository
from platform_core.task_runtime import ArtifactStore, TaskKind

from .reports import build_version_report


def training_history(job: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Project one training run's ``results.csv`` into the bounded epoch history.

    The report must never read an unrelated working directory when the job did
    not record its own ``run_dir``.
    """
    recorded_dir = str(job.get('run_dir') or '').strip()
    if not recorded_dir:
        return []
    csv_path = Path(recorded_dir) / 'results.csv'
    if not csv_path.is_file(): return []
    try:
        rows=[]
        with csv_path.open('r',encoding='utf-8-sig',errors='replace',newline='') as fp:
            for raw in csv.DictReader(fp):
                def num(*names):
                    for n in names:
                        for k,v in raw.items():
                            if k and k.strip()==n:
                                try:return float(v)
                                except:return None
                    return None
                rows.append({'epoch':int(float(raw.get('epoch') or len(rows)+1)),
                             'precision':num('metrics/precision(B)'), 'recall':num('metrics/recall(B)'),
                             'map50':num('metrics/mAP50(B)'), 'map5095':num('metrics/mAP50-95(B)'),
                             'box_loss':num('train/box_loss'), 'cls_loss':num('train/cls_loss'), 'dfl_loss':num('train/dfl_loss'),
                             'val_box_loss':num('val/box_loss'), 'val_cls_loss':num('val/cls_loss'),
                             'val_dfl_loss':num('val/dfl_loss'), 'learning_rate':num('lr/pg0')})
        return rows[-500:]
    except Exception:
        return []


class TrainingReportReader:
    """Compose the v44 training report from the existing owners.

    Every callable is injected by the host application and is expected to be a
    late-bound wrapper, so the existing module-level seams keep working.
    """

    def __init__(
        self,
        *,
        get_project,
        project_dir,
        algorithms_file,
        algorithm_repository=None,
        data_dir,
        read_json,
        enrich_job_runtime,
        list_algorithms_internal,
        durable_training_task,
        task_repository,
        task_artifacts,
        training_history,
        now_iso,
    ) -> None:
        self._get_project = get_project
        self._project_dir = project_dir
        self._algorithms_file = algorithms_file
        # Provider-neutral accessor: one authoritative algorithm source.
        self._algorithm_repository = algorithm_repository or (
            lambda project_id: open_algorithm_repository(
                self._algorithms_file(project_id)
            )
        )
        self._data_dir = data_dir
        self._read_json = read_json
        self._enrich_job_runtime = enrich_job_runtime
        self._list_algorithms_internal = list_algorithms_internal
        self._durable_training_task = durable_training_task
        self._task_repository = task_repository
        self._task_artifacts = task_artifacts
        self._training_history = training_history
        self._now_iso = now_iso

    def report(
        self,
        project_id: str,
        job_id: str,
        algorithm_id: str = '',
        version_id: str = '',
        reader_view: bool = False,
        history_offset: Optional[int] = None,
        history_limit: int = 200,
    ):
        if reader_view:
            if history_offset is not None and history_offset<0 or not 1<=history_limit<=200:raise HTTPException(422,detail='报告历史分页范围无效')
            from platform_core.training_reader_views import report_display

            self._get_project(project_id)
            try:ArtifactStore._validate_task_id(job_id)
            except ValueError as error:raise HTTPException(422,detail='报告任务ID无效') from error
            task=self._task_repository().get(job_id)
            if task and (task.project_id!=project_id or task.kind is not TaskKind.TRAINING):raise HTTPException(404,detail='训练任务不存在')
            store=self._algorithm_repository(project_id)
            if algorithm_id or version_id:
                if not (algorithm_id and version_id):raise HTTPException(409,detail='REPORT_IDENTITY_MISMATCH: 须同时指定算法与版本')
                version=store.asset_version(algorithm_id,version_id,detail=False)
                if str(version.get('training_job_id') or '')!=job_id:raise HTTPException(409,detail='REPORT_IDENTITY_MISMATCH: 版本与训练任务不一致')
            else:
                refs=store.training_version_refs(job_id)
                if len(refs)>1:raise HTTPException(409,detail='REPORT_IDENTITY_AMBIGUOUS: 请从具体版本进入')
                if refs:algorithm_id,version_id=refs[0]
            result=report_display(job_id,task,self._task_artifacts(),self._project_dir(project_id)/'jobs'/job_id/'job.json',algorithm_id=algorithm_id,version_id=version_id,history_offset=history_offset,history_limit=history_limit)
            if result['state']=='IDENTITY_CONFLICT':raise HTTPException(409,detail='REPORT_IDENTITY_MISMATCH: '+result['message'])
            return {'ok':True,'project_id':project_id,'job_id':job_id,'algorithm_id':algorithm_id,'version_id':version_id,**result}
        self._get_project(project_id);jf=self._project_dir(project_id)/'jobs'/job_id/'job.json'
        if not jf.exists(): raise HTTPException(status_code=404,detail='训练任务不存在')
        job=self._enrich_job_runtime(project_id,self._read_json(jf,{}),allow_version_archive=False);report=job.get('training_report') or {}
        # Prefer the existing SQL training-job index, then hydrate only its owning
        # algorithms. Historical versions with no indexed identity still retain
        # the original full-catalog fallback and its ambiguity safeguards.
        if algorithm_id:
            report_algorithms = self._list_algorithms_internal(project_id, algorithm_id=algorithm_id)
            indexed_refs = []
        else:
            catalog = self._algorithm_repository(project_id)
            # "not initialized yet" is a state; a provider failure must never
            # be reported as an empty catalog.
            indexed_refs = catalog.training_version_refs(job_id) if catalog.is_initialized() else []
            report_algorithms = (
                [row for owner_id in sorted({owner_id for owner_id, _ in indexed_refs})
                 for row in self._list_algorithms_internal(project_id, algorithm_id=owner_id)]
                if indexed_refs else self._list_algorithms_internal(project_id, algorithm_id=None)
            )
        matches = [(algorithm, version) for algorithm in report_algorithms
                   for version in algorithm.get('versions', [])
                   if (not algorithm_id or str(algorithm.get('id')) == algorithm_id)
                   and (not version_id or str(version.get('id')) == version_id)
                   and str(version.get('job_id') or (version.get('training_lineage') or {}).get('task_id') or '') == job_id]
        if not matches and indexed_refs:
            # An indexed row whose JSON task identity is stale must not hide a
            # genuine lineage-only match elsewhere in an older catalog.
            matches = [(algorithm, version) for algorithm in self._list_algorithms_internal(project_id, algorithm_id=None)
                       for version in algorithm.get('versions', [])
                       if (not version_id or str(version.get('id')) == version_id)
                       and str(version.get('job_id') or (version.get('training_lineage') or {}).get('task_id') or '') == job_id]
        if (algorithm_id or version_id) and (not algorithm_id or not version_id or len(matches) != 1):
            raise HTTPException(status_code=409, detail='REPORT_IDENTITY_MISMATCH: 所选算法版本与训练任务不一致')
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail='REPORT_IDENTITY_AMBIGUOUS: 训练任务关联多个版本，须明确选择')
        algorithm, version = matches[0] if matches else ({}, {})
        task_references = {str(value) for value in (version.get('job_id'), (version.get('training_lineage') or {}).get('task_id'), job.get('id')) if value}
        algorithm_references = {str(value) for value in (algorithm.get('id'), job.get('asset_algorithm_id'), job.get('algorithm_asset_id')) if value}
        if task_references - {job_id} or len(algorithm_references) > 1:
            raise HTTPException(status_code=409, detail='REPORT_IDENTITY_MISMATCH: 任务、算法与版本血缘存在冲突')
        if version and any(str(job[key]) != str(version['id']) for key in ('auto_version_id', 'version_id') if job.get(key)):
            raise HTTPException(status_code=409, detail='REPORT_IDENTITY_MISMATCH: 任务版本记录与算法版本冲突')
        if not report:
            metrics = job.get('metrics') or job.get('final_metrics') or {}
            elapsed = job.get('elapsed_seconds')
            report = {
                'generated_at': self._now_iso(),
                'framework': job.get('framework') or '',
                'status': job.get('status') or '',
                'metrics': metrics,
                'per_class': [],
                'weak_labels': [],
                'gate_events': job.get('gate_events') or [],
                'summary': {
                    'elapsed_seconds': elapsed,
                    'epochs': job.get('epochs') or 0,
                    'model': job.get('model') or '',
                    'dataset_name': job.get('dataset_name') or '全部数据',
                    'artifacts': [x for x in [job.get('best_model'), job.get('last_model')] if x],
                },
                'note': '该任务未生成逐类别评测明细；报告仅汇总已记录的训练结果。',
            }
        # Finalized TaskRecord artifacts own model-quality truth.  The mutable
        # job.json may be stale or may predate TQ-04; it must never supply a
        # synthetic credibility verdict.  A legacy report without durable
        # evidence explicitly has no metric_credibility.
        task = self._durable_training_task(project_id, job_id)
        finalized = (
            self._task_artifacts().read_json(job_id, 'result.json', default={})
            if task is not None else {}
        )
        if not isinstance(finalized, dict):
            finalized = {}
        committed_report = finalized.get('training_report')
        if isinstance(committed_report, dict) and committed_report:
            report = committed_report
        canonical = {**job, 'training_report': report}
        # The finalized validation metrics are the same evidence shown alongside
        # the frozen credibility assessment, never an older job-level metric copy.
        if isinstance(report.get('metrics'), dict) and report['metrics']:
            canonical['metrics'] = report['metrics']
        if isinstance(finalized.get('evaluation'), dict):
            canonical['evaluation'] = finalized['evaluation']
        if isinstance(finalized.get('metric_credibility'), dict):
            canonical['metric_credibility'] = finalized['metric_credibility']
        version_report = build_version_report(canonical)
        from platform_core.training_metrics import read_metrics
        metrics_path = self._task_artifacts().artifact_path(job_id, 'training-metrics.sqlite3') if task else jf.parent / 'training-metrics.sqlite3'
        telemetry = read_metrics(metrics_path, include_history=True)
        version_report['history'] = report.get('history') or self._training_history(job) or telemetry.get('epochs') or []
        version_report['runtime_metrics'] = telemetry
        version_report['generated_at'] = self._now_iso()
        version_report['per_class'] = report.get('per_class') or []
        from platform_core.reports import diagnose_training_history
        version_report['quality_analysis'] = diagnose_training_history(version_report['history'])
        snapshot_id = str(version_report.get('snapshot_id') or '')
        if re.fullmatch(r'[0-9a-f]{64}', snapshot_id):
            snapshot_path = self._project_dir(project_id) / 'snapshots' / f'{snapshot_id}.json'
            frozen = self._read_json(snapshot_path, {}) if snapshot_path.is_file() else {}
            if frozen.get('snapshot_id') == snapshot_id:
                from platform_core.quality import frozen_data_quality
                version_report['frozen_data_quality'] = frozen_data_quality(frozen)
                quality = frozen.get('input_quality') or {}
                version_report['frozen_audit'] = quality
                coverage = quality.get('class_coverage') or {}
                version_report['capture_source_summary'] = {key: value for key, value in coverage.items() if 'source' in key or 'component' in key or key == 'provenance_status'}
                version_report['frozen_data_quality']['negative_count'] = coverage.get('role_confirmed_negative_image_counts')
        version_report['configuration'] = {
            'framework': job.get('framework') or '', 'algorithm_name': job.get('algorithm_name') or '', 'model': job.get('model') or '',
            'epochs': job.get('epochs'), 'imgsz': job.get('imgsz'), 'batch': job.get('batch'), 'device': job.get('device') or '',
            **(job.get('advanced_params') or {})
        }
        version_report['data_summary'] = {
            'counts': job.get('dataset_counts') or {}, 'selected_ids': job.get('dataset_selected_ids') or {},
            'quality_gate': job.get('quality_gate') or {}
        }
        from platform_core.model_metadata import frozen_weight_labels, yolo_architecture
        from platform_core.reports import representative_error_samples, report_resource_evidence
        version_report['identity'] = {'project_id': project_id, 'algorithm_id': algorithm.get('id') or '',
            'algorithm_name': algorithm.get('name') or job.get('asset_algorithm_name') or '',
            'version_id': version.get('id') or version_report.get('version_id') or '', 'job_id': job_id}
        version_report['lineage'] = version.get('training_lineage') or job.get('training_lineage') or {}
        version_report['execution'] = version_report['lineage'].get('execution') or job.get('execution') or {}
        version_report['framework'] = job.get('framework') or report.get('framework') or ''
        version_report['model_architecture'] = yolo_architecture(version, algorithm) if version else ''
        labels = frozen_weight_labels(version) if version else None
        schema = {row.get('code'): row for row in version.get('label_schema') or [] if isinstance(row, dict)}
        version_report['class_mapping'] = [{'class_id': index, 'code': code,
            'name': schema.get(code, {}).get('display_name') or code} for index, code in enumerate(labels or [])]
        version_report['started_at'] = job.get('started_at') or ''
        version_report['elapsed_seconds'] = job.get('elapsed_seconds') if job.get('elapsed_seconds') is not None else (report.get('summary') or {}).get('elapsed_seconds')
        version_report['train_metrics'] = report.get('train_metrics')
        version_report['best_epoch'] = report.get('best_epoch') or telemetry.get('best_epoch')
        version_report['representative_errors'] = representative_error_samples(version_report['evaluation'], job_id=job_id, snapshot_id=snapshot_id)
        version_report.update(report_resource_evidence(job, telemetry))
        version_report['conversions'] = []
        if version and (Path(self._data_dir()) / 'model_artifacts' / 'artifacts.sqlite3').is_file():
            from platform_core.model_artifacts import ModelArtifactRepository
            version_report['conversions'] = [row for row in ModelArtifactRepository(self._data_dir()).list(
                project_id=project_id, algorithm_id=str(algorithm['id']), version_id=str(version['id']), limit=100)
                if row.get('target') != 'original']
        return {"ok":True,"report_type":"version","job":job,"report":version_report}


def create_training_report_router(reader: TrainingReportReader) -> APIRouter:
    """Build the training-report router around the injected reader."""
    router = APIRouter()

    @router.get('/api/v44/projects/{project_id}/jobs/{job_id}/report')
    def v44_training_report(project_id: str, job_id: str, algorithm_id: str = '', version_id: str = '', reader_view: bool=False, history_offset: Optional[int]=None, history_limit: int=200):
        return reader.report(
            project_id, job_id, algorithm_id=algorithm_id, version_id=version_id,
            reader_view=reader_view, history_offset=history_offset, history_limit=history_limit,
        )

    return router
