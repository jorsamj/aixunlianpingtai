"""Real optional engine through the original durable material Worker, isolated data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import os
import time
import threading
import psutil

from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.material_batches import worker_registration,public_batch,estimate_batch,create_batch
from platform_core.smart_material_audit.service import estimate_audit,create_audit,CAPABILITY
from platform_core.smart_material_audit.results import findings_page
from platform_core.storage.source_repository import StorageSourceRepository
from platform_core.task_runtime import TaskRepository,ArtifactStore,TaskStatus
from platform_core.task_runtime.scheduler import Scheduler
from platform_core.task_runtime.worker import WorkerContext,ExecutionFencedError


def main():
    parser=argparse.ArgumentParser();parser.add_argument("python");parser.add_argument("--out",required=True)
    parser.add_argument('--case',choices=['success','bind_failure','partial_retry','missing_engine'],default='success')
    parser.add_argument('--missing-python',default='');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="smart-durable-owned-") as temporary:
        root=Path(temporary);project=root/"projects/p";(project/"uploads").mkdir(parents=True)
        os.environ['MC_MATERIAL_CACHE_DIR']=str(root/'cache/materials')
        image=Image.new("RGB",(96,72),"navy");ImageDraw.Draw(image).rectangle((10,8,50,55),fill="orange")
        image.save(project/"uploads/a.png");image.resize((192,144)).save(project/"uploads/b.jpg",quality=95)
        materials=MaterialRepository(project);annotations=AnnotationRepository(project)
        sources=StorageSourceRepository(root/"storage/storage_sources.sqlite3")
        for name in ("a.png","b.jpg"):
            path=project/"uploads"/name
            materials.upsert(dict(id=name.split('.')[0],filename=name,object_key="uploads/"+name,
                content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size))
        if args.case=='partial_retry':
            materials.upsert({**materials.get('b'),'content_sha256':'0'*64})
        original_materials=materials.read();original_gt=annotations.summary();original_sources=[s.to_public_dict() for s in sources.list()]
        (root/"smart_material_audit.json").write_text(json.dumps(dict(enabled=True,python=args.python)))
        repository=TaskRepository(root/"tasks.sqlite3");artifacts=ArtifactStore(root/"artifacts")
        estimate=estimate_audit(root,"p",dict(scope="FILTERED",filters={}))
        task=create_audit(root,"p",repository,artifacts,dict(selection_spec=estimate['selection_spec'],options={'request_id':'isolated-acceptance'}),actor={'actor_id':'isolated-user'})
        registration=worker_registration(root)
        assert CAPABILITY in registration['capabilities']
        legacy=Scheduler(repository,artifacts,'old-material-worker',registration['handlers'],{'materials.batch'})
        assert legacy.run_once() is False and repository.get(task.task_id).status == TaskStatus.QUEUED
        scheduler=Scheduler(repository,artifacts,'optional-material-worker',registration['handlers'],registration['capabilities'])
        launched=[]
        original_bind=WorkerContext.bind_process
        if args.case=='bind_failure':
            def failed_bind(self,identity):
                launched.append(identity)
                self.mark_lease_lost()
                raise ExecutionFencedError('isolated test-only process binding fence failure')
            WorkerContext.bind_process=failed_bind
        if args.case=='missing_engine':
            assert args.missing_python
            (root/'smart_material_audit.json').write_text(json.dumps(dict(enabled=True,python=args.missing_python)))
        try:
            assert scheduler.run_once()
        finally:
            WorkerContext.bind_process=original_bind
        completed=repository.get(task.task_id)
        if args.case in {'bind_failure','missing_engine'}:
            assert completed.status == (TaskStatus.RUNNING if args.case=='bind_failure' else TaskStatus.BLOCKED_BY_ENVIRONMENT),completed.error
            assert materials.read()==original_materials and annotations.summary()==original_gt
            assert not list(artifacts.root.rglob('working-*'))
            for identity in launched:
                try: assert psutil.Process(identity.pid).create_time()!=identity.create_time
                except psutil.NoSuchProcess: pass
            if args.case=='missing_engine':
                (root/'smart_material_audit.json').write_text(json.dumps(dict(enabled=False)))
                clean={'operation':'CLEAN','selection_spec':{'scope':'SELECTED','image_ids':['a','b']},'options':{}}
                clean['selection_spec']=estimate_batch('p',materials,clean)['selection_spec']
                basic=create_batch('p',materials,repository,artifacts,clean)
                assert scheduler.run_once()
                assert repository.get(basic.task_id).status==TaskStatus.SUCCEEDED
            receipt=dict(case=args.case,status=completed.status.value,owned_processes_remaining=0,
                temporary_roots_cleaned=True,formal_material_gt_unchanged=True,
                base_clean_task_passed=args.case=='missing_engine',scope='isolated original Worker + actual subprocess fault')
            Path(args.out).write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt,indent=2));return
        if args.case=='partial_retry':
            assert completed.status==TaskStatus.PARTIAL_SUCCESS,completed.error
            assert materials.read()==original_materials  # Analysis never repairs a historical SHA.
            repaired={**materials.get('b'),'content_sha256':hashlib.sha256((project/'uploads/b.jpg').read_bytes()).hexdigest()}
            materials.upsert(repaired)  # Explicit test-fixture repair, not an analysis action.
            original_materials=materials.read()
            repository.retry(task.task_id)
            queued=public_batch(repository.get(task.task_id),artifacts,repository)
            assert queued['processed']==0 and queued['succeeded']==0
            worker=threading.Thread(target=scheduler.run_once);worker.start()
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                current=repository.get(task.task_id)
                if current.process_pid:
                    checkpoint=artifacts.read_json(task.task_id,'checkpoints/worker.json')
                    assert checkpoint['execution_generation']==2 and checkpoint['succeeded']==0 and checkpoint['failed']==0
                    break
                time.sleep(.05)
            else: raise AssertionError('retry engine was not bound')
            worker.join(90);assert not worker.is_alive()
            completed=repository.get(task.task_id)
            assert completed.attempt==2 and len(repository.list(project_id='p',limit=50).items)==1
        assert completed.status == TaskStatus.SUCCEEDED, completed.error
        summary=artifacts.read_json(task.task_id,completed.result_ref)
        assert summary['processed']==2 and summary['failed']==0
        path=artifacts.artifact_path(task.task_id,f'smart-audit/{completed.attempt}/findings.sqlite3')
        result=findings_page(path,project)
        assert result['total']==1 and result['items'][0]['issue_type']=='visual_similarity'
        assert result['checks']['leakage']['status']=='not_checked'
        assert materials.read()==original_materials and annotations.summary()==original_gt
        assert [s.to_public_dict() for s in sources.list()]==original_sources
        assert len([p for p in root.rglob('*') if p.suffix in {'.png','.jpg'}])==2
        assert not list(artifacts.root.rglob('working-*'))
        receipt=dict(case=args.case,task_id=task.task_id,status=completed.status.value,attempt=completed.attempt,
            summary=summary,findings_count=result['total'],original_material_gt_sources_unchanged=True,
            legacy_worker_cannot_claim=True,source_image_files=2,permanent_extra_image_copies=0,
            scope='isolated original TaskRepository/Scheduler/MaterialBatchHandler + real FiftyOne, no web/production/GPU')
        Path(args.out).write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
