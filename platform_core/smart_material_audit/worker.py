"""Original MATERIAL_BATCH Worker adapter; no alternate scheduler or GT writes."""
from __future__ import annotations

from contextlib import closing, ExitStack
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import uuid

from filelock import FileLock
import psutil

from ..annotation_repository import AnnotationRepository
from ..material_repository import MaterialRepository, DATASET_DELETE_CLAIM_FIELD, MATERIAL_BATCH_DELETE_CLAIM_FIELD
from ..storage.manager import StorageManager
from ..storage.source_repository import StorageSourceRepository
from ..storage.import_tasks import _provider
from ..storage.errors import StorageError, redact_storage_error
from ..storage.models import StorageType
from ..task_runtime import TaskStatus
from ..task_runtime.process_control import launch_process, ProcessController, ProcessIdentity, hash_command
from ..task_runtime.task_logs import append_task_log
from .service import configuration, project_path
from .contract import FEATURE, manifest_digest
from .evidence import load_evidence
from .results import build_results


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > 32*1024*1024:
        raise ValueError("智能分析工件超过内存安全上限")
    return json.loads(path.read_text(encoding="utf-8"))


def _active(context, stage):
    current = context.heartbeat(stage=stage)
    if current.status == TaskStatus.CANCEL_REQUESTED:
        raise InterruptedError("智能分析已请求取消")


def _stop_observed(identities):
    controller = ProcessController()
    for identity in reversed(list(identities.values())):
        try:
            controller.inspect(identity)
        except ProcessLookupError:
            continue
        controller.terminate_tree(identity,timeout=5)


def _materialize_input(manager,image,cached,cache_bytes):
    if image.get(DATASET_DELETE_CLAIM_FIELD) or image.get(MATERIAL_BATCH_DELETE_CLAIM_FIELD):
        raise ValueError('素材存在删除或恢复占用，保持原记录且未检查')
    material=manager.material(image)
    if material.get('source_available') is False:
        raise ValueError('原素材源标记不可用，未检查')
    provider=manager.provider_for(material['storage_source_id'])
    if provider.storage_type is StorageType.LOCAL:
        return manager.materialize(material,read_only=True)
    suffix=Path(str(material.get('filename') or material['object_key'])).suffix or Path(material['object_key']).suffix
    target=str(manager.cache.path_for(material['content_sha256'],suffix or '.bin'))
    if target in cached:
        return cached[target]  # Immutable matching bytes, already pinned; avoid lock reacquisition.
    if len(cached)>=128 or cache_bytes>=512*1024*1024:
        raise ValueError('共享缓存引用预算已用尽；不继续下载剩余素材')
    metadata=provider.stat(material['object_key'])
    if metadata.size_bytes<=0 or metadata.size_bytes>512*1024*1024-cache_bytes:
        raise ValueError('远程素材元数据大小超过共享缓存预算；未下载')
    return manager.materialize(material,read_only=True)


def run_audit(context, data_dir):
    from ..material_batches import BatchSelection
    config = configuration(data_dir)
    task_id = context.task.task_id
    project = project_path(data_dir, context.task.project_id)
    request = context.artifacts.read_json(task_id,context.task.payload_ref)
    selection_path = context.artifacts.artifact_path(task_id,"selection.sqlite3")
    with FileLock(str(selection_path)+".lock",timeout=60), closing(BatchSelection(selection_path)) as manifest, ExitStack() as pins:
        if not manifest.frozen():
            raise ValueError("智能分析缺少原任务冻结范围")
        ids = [r[0] for r in manifest.database.execute("SELECT image_id FROM selection ORDER BY image_id LIMIT ?",(config['max_images']+1,))]
        if not ids or len(ids) > config['max_images']:
            raise ValueError("智能分析范围超过已验证上限或为空")
        materials = MaterialRepository.open_readonly(project)
        sources = StorageSourceRepository.open_readonly(Path(data_dir)/"storage/storage_sources.sqlite3")
        try:
            annotations = AnnotationRepository.open_readonly(project)
        except (sqlite3.Error,ValueError):
            annotations = None
        manager = StorageManager(data_dir=data_dir,project_id=context.task.project_id,materials=materials,sources=sources,
            provider_resolver=lambda source,_secret:_provider(Path(data_dir),context.task.project_id,source),cache_maintenance=False)
        generation = context.execution_generation
        base = context.artifacts.artifact_path(task_id,f"smart-audit/{generation}/findings.sqlite3").parent
        working = base/("working-"+uuid.uuid4().hex)
        working.mkdir(parents=True)
        ownership = {"task_id":task_id,"project_id":context.task.project_id,"generation":generation}
        marker = working/"ownership.json"
        marker.write_text(json.dumps(ownership),encoding="utf-8")
        observed = {}
        inputs, failures, locked = [], [], set()
        cached_inputs={}
        cache_bytes = 0
        outcome = None
        peak_rss = peak_disk = 0
        try:
            _active(context,'smart_inputs')
            with manifest.transaction():
                manifest.database.execute("UPDATE selection SET state='pending',error=NULL")
                context.assert_current_execution()
            fresh=manifest.summary();fresh['execution_generation']=generation
            context.save_checkpoint(fresh)
            evidence = load_evidence(project,request.get('options',{}),context.repository,context.artifacts)
            for start in range(0,len(ids),500):
                _active(context,"smart_inputs")
                batch = ids[start:start+500]
                indexed = {r['id']:r for r in materials.get_many(batch)}
                gt = annotations.get_many(batch) if annotations else {}
                for image_id in batch:
                    _active(context,"smart_inputs")
                    manifest.transition([image_id],"running",commit_guard=context.assert_current_execution)
                    image = indexed.get(image_id)
                    try:
                        if not image or not image.get('content_sha256'):
                            raise ValueError("素材缺失或没有可信SHA；不自动补写或迁移")
                        local = _materialize_input(manager,image,cached_inputs,cache_bytes)
                        if local.path.resolve().is_relative_to(manager.cache.root):
                            if str(local.path) not in locked:
                                if len(locked) >= 128 or cache_bytes+local.size_bytes > 512*1024*1024:
                                    raise ValueError("共享缓存引用超出当前已验证上限")
                                pins.enter_context(FileLock(str(local.path)+'.lock',timeout=0))
                                locked.add(str(local.path));cache_bytes+=local.size_bytes
                                cached_inputs[str(local.path)]=local
                        record = gt.get(image_id)
                        row = {"image_id":image_id,"filename":image.get('filename',image_id),"path":str(local.path),
                            "content_sha256":local.content_sha256,"annotation_version":record.get('version') if record else None,
                            "annotation_digest":annotations.record_digest(record) if record is not None else None,
                            "annotation_state":record.get('annotation_state') if record else 'unknown',
                            "gt_boxes":record.get('boxes',[]) if record else []}
                        split = evidence['splits'].get(image_id,{})
                        if split.get('content_sha256') == local.content_sha256:
                            row['frozen_split'] = split['split']
                        prediction = evidence['predictions'].get(image_id,{})
                        if (prediction.get('prediction_evidence',{}).get('image_content_sha256') == local.content_sha256
                                and image.get('annotation_source_content_sha256') == local.content_sha256):
                            row.update(prediction)
                        inputs.append(row)
                    except (OSError,ValueError,StorageError) as error:
                        failures.append({'image_id':image_id,'reason':redact_storage_error(error)})
                        manifest.transition([image_id],'failed',redact_storage_error(error),commit_guard=context.assert_current_execution)
                    checkpoint = manifest.summary()
                    checkpoint['execution_generation']=generation
                    checkpoint['smart_audit_progress'] = {'stage':'smart_inputs','prepared':len(inputs),'failed':len(failures),'total':len(ids)}
                    context.save_checkpoint(checkpoint)
            if inputs:
                payload = {'project_id':context.task.project_id,'task_id':task_id,'execution_generation':generation,
                    'feature':FEATURE,'images':inputs,'threshold':request['options']['threshold']}
                if evidence['provenance'] and all(row.get('frozen_split') for row in inputs):
                    payload['frozen_split_evidence'] = evidence['provenance']['snapshot_id']
                source = working/'input.json';source.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
                output = working/'output.json';runtime = working/'engine'
                keep={'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','USERPROFILE','HOME',
                    'APPDATA','LOCALAPPDATA','PROGRAMDATA','NUMBER_OF_PROCESSORS','LANG','LC_ALL'}
                environment = {k:v for k,v in os.environ.items() if k.upper() in keep}
                environment.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
                with (working/'engine.log').open('w',encoding='utf-8') as log:
                    launched = launch_process([config['python'],'-X','utf8',str(Path(__file__).with_name('engine.py')),str(source),str(runtime),str(output)],
                        env=environment,stdout=log,stderr=subprocess.STDOUT)
                    observed[launched.identity.pid] = launched.identity
                    context.bind_process(launched.identity)
                    deadline = time.monotonic()+config['timeout_seconds']
                    try:
                        while launched.process.poll() is None:
                            _active(context,'smart_engine')
                            if time.monotonic()>deadline:
                                raise TimeoutError('智能分析超过截止时间；可安全重试，原清洗状态不变')
                            try:
                                root = psutil.Process(launched.identity.pid)
                                processes = [root,*root.children(recursive=True)]
                                rss = 0
                                for process in processes:
                                    try:
                                        observed[process.pid]=ProcessIdentity(process.pid,process.create_time(),hash_command(process.cmdline()))
                                        rss+=process.memory_info().rss
                                    except psutil.NoSuchProcess:
                                        pass
                                peak_rss=max(peak_rss,rss)
                            except psutil.NoSuchProcess:
                                pass
                            disk=0
                            for path in working.rglob('*'):
                                try:
                                    if path.is_file(): disk+=path.stat().st_size
                                except FileNotFoundError:
                                    pass  # Child cleanup can race this observational sample.
                            peak_disk=max(peak_disk,disk)
                            progress_path=runtime/'progress.json'
                            if progress_path.is_file():
                                progress=_read_json(progress_path)
                                checkpoint=manifest.summary();checkpoint['smart_audit_progress']=progress;checkpoint['execution_generation']=generation
                                context.save_checkpoint(checkpoint)
                            time.sleep(.5)
                        if launched.process.returncode:
                            tail=(working/'engine.log').read_text(encoding='utf-8',errors='replace')[-3000:]
                            append_task_log(context,'smart_engine_failed',redact_storage_error(tail))
                            if 'ModuleNotFoundError' in tail or 'PackageNotFoundError' in tail or 'ENGINE_VERSION_UNVERIFIED' in tail:
                                raise EnvironmentError('独立FiftyOne环境不可用；原业务未修改，请修复环境后重试')
                            raise RuntimeError('智能分析失败；原清洗/GT未改变，详情见原任务日志')
                        outcome=_read_json(output)
                        if any(outcome.get(key)!=expected for key,expected in (
                                ('project_id',context.task.project_id),('task_id',task_id),('execution_generation',generation),
                                ('input_digest',manifest_digest(payload)),('total',len(inputs)),('scanned',len(inputs)))):
                            raise ValueError('分析结果与本次任务/输入身份不一致')
                    finally:
                        _stop_observed(observed)
                for row in outcome.get('failures',[]):
                    failures.append(row)
                    manifest.transition([row['image_id']],'failed',row['reason'],commit_guard=context.assert_current_execution)
                failed_ids={r['image_id'] for r in failures}
                good=[r['image_id'] for r in inputs if r['image_id'] not in failed_ids]
                for start in range(0,len(good),500):
                    manifest.transition(good[start:start+500],'succeeded',commit_guard=context.assert_current_execution)
            else:
                outcome={'checks':{'visual_similarity':{'status':'not_checked','reason':'没有可核验输入'}},'similar_pairs':[],'annotation_candidates':[]}
            outcome['failures']=failures
            context.assert_current_execution()
            build_results(base/'findings.sqlite3',inputs,outcome,generation=generation)
        finally:
            _stop_observed(observed)
            # Exact private task-generation root only; no source/cache paths.
            if working.resolve().parent != base.resolve() or working.is_symlink() or _read_json(marker)!=ownership:
                raise PermissionError('临时目录归属不能确认，保留现场')
            shutil.rmtree(working)
        summary=manifest.summary()
        summary.update(engine='fiftyone',feature=FEATURE,checks=outcome['checks'],input_evidence_reason=evidence['reason'],
            finding_count=len(outcome.get('similar_pairs',[]))+len(outcome.get('annotation_candidates',[]))+len(failures),
            execution_generation=generation,temporary_data_cleaned=True,extra_permanent_image_copies=0,
            shared_cache_references=len(locked),peak_process_tree_rss_bytes=peak_rss,peak_temporary_logical_bytes=peak_disk)
        context.save_checkpoint(summary)
        reference=f'smart-audit/{generation}/result.json'
        context.artifacts.atomic_write_json(task_id,reference,summary)
        status=TaskStatus.FAILED if not inputs else TaskStatus.PARTIAL_SUCCESS if failures else TaskStatus.SUCCEEDED
        return status,reference
