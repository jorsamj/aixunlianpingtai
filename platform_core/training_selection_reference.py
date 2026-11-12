"""Immutable picker selections in the existing ArtifactStore/BatchSelection format.
The manifest is task intent, never GT or a second material authority.
"""
from contextlib import closing
from pathlib import Path
import hashlib,json,re,secrets,sqlite3,uuid,shutil,os,time
from filelock import FileLock
from .task_runtime.artifacts import ArtifactStore
from .material_batches import BatchSelection

MAX_FROZEN_SELECTION_IDS=1_000_000
MAX_FROZEN_SELECTION_BYTES=512*1024*1024


def _path(data_dir,reference):
    if not re.fullmatch(r'trainselection_[0-9a-f]{32}',str(reference)):
        raise ValueError('训练素材选择引用无效，请重新选择')
    root=Path(data_dir).resolve()/'task_runtime'/'artifacts'
    path=root/str(reference)/'selection.sqlite3'
    for item in (root,path.parent,path):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('selection manifest must not be a link')
    return path


def _write_selection(data_dir,context,image_ids,reference,request_scope):
    path=_path(data_dir,reference)
    ArtifactStore(Path(data_dir)/'task_runtime'/'artifacts').artifact_path(reference,'selection.sqlite3')
    with closing(BatchSelection(path)) as manifest:
        with manifest.transaction():
            # A single prepared statement consumes this bounded generator.
            # Keep all ID validation and the upper bound inside the same
            # transaction: a late invalid row must roll back the whole draft.
            def checked_rows():
                for index,image_id in enumerate(image_ids):
                    if index>=MAX_FROZEN_SELECTION_IDS:raise ValueError('冻结选择超过100万条上限，请缩小筛选范围')
                    identity=str(image_id).strip()
                    if not identity or len(identity)>256:raise ValueError('invalid selection identity')
                    yield (identity,)
            manifest.database.executemany('INSERT OR IGNORE INTO selection(image_id) VALUES (?)',checked_rows())
            count=manifest.database.execute('SELECT COUNT(*) FROM selection').fetchone()[0]
            if not count:raise ValueError('没有符合条件的可选训练素材')
            digest=hashlib.sha256()
            for row in manifest.database.execute('SELECT image_id FROM selection ORDER BY image_id'):
                digest.update((row[0]+'\0').encode())
            metadata={'context':context,'count':count,'sha256':digest.hexdigest(),'request_scope':request_scope,'created_at':time.time()}
            manifest.database.execute('INSERT INTO meta(key,value) VALUES (?,?)',('training_selection',json.dumps(metadata,sort_keys=True)))
            manifest.database.execute("INSERT INTO meta(key,value) VALUES ('frozen','1')")
            if manifest.database.execute('PRAGMA page_count').fetchone()[0]*manifest.database.execute('PRAGMA page_size').fetchone()[0]>MAX_FROZEN_SELECTION_BYTES:
                raise ValueError('selection manifest exceeds byte quota')
        manifest.database.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return {'selection_ref':reference,'count':count}


def _expired(metadata):
    return bool(metadata.get('expired')) or (not metadata.get('submitted_task_id') and
        time.time()-float(metadata.get('created_at',0))>max(60,int(os.environ.get('MC_TRAIN_SELECTION_DRAFT_TTL_SECONDS','86400'))))


def _draft_quota_count(data_dir,root,project_id,*,stop_at=None):
    # Admission only needs to know whether the quota is reached. Under heavy
    # task history, do not open/lock the remaining independent SQLite files
    # after that result is already conclusive. Unbounded callers still count all.
    active=0;compacted=False
    for path in root.glob('trainselection_*/selection.sqlite3'):
        if stop_at is not None and active>=stop_at:
            return active
        checked=_path(data_dir,path.parent.name)
        try:
            with FileLock(str(checked)+'.freeze.lock',timeout=0),closing(sqlite3.connect(checked)) as db:
                row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
                metadata=json.loads(row[0]) if row else {}
                if metadata.get('context',{}).get('project_id')!=project_id:continue
                if metadata.get('submitted_task_id'):continue
                if _expired(metadata):
                    if not compacted and not metadata.get('expired'):
                        # Only expired unsubmitted draft IDs, never model/GT/task data.
                        metadata['expired']=True
                        db.execute('DELETE FROM selection')
                        db.execute("UPDATE meta SET value=? WHERE key='training_selection'",(json.dumps(metadata,sort_keys=True),))
                        db.commit();db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('VACUUM')
                        compacted=True
                    continue
                active+=1
        except (OSError,sqlite3.Error,ValueError):
            active+=1  # Uncertain ownership is preserved and counted.
        except TimeoutError:active+=1
    return active


def mark_selection_submitted(data_dir,reference,task_id):
    path=_path(data_dir,reference)
    with FileLock(str(path)+'.freeze.lock',timeout=5),closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)) as db:
        row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
        metadata=json.loads(row[0]) if row else {}
        if _expired(metadata):raise ValueError('冻结素材选择已过期，请重新选择')
        owners=list(dict.fromkeys([*(metadata.get('submitted_task_ids') or []),*([metadata['submitted_task_id']] if metadata.get('submitted_task_id') else []),str(task_id)]))
        metadata['submitted_task_ids']=owners
        metadata['submitted_task_id']=owners[0]
        db.execute("UPDATE meta SET value=? WHERE key='training_selection'",(json.dumps(metadata,sort_keys=True),))
        db.commit()


def release_unpersisted_selection_claim(data_dir,reference,task_id):
    """Caller proves its parent Task was not persisted; retain other owners."""
    path=_path(data_dir,reference)
    with FileLock(str(path)+'.freeze.lock',timeout=5),closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)) as db:
        row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
        metadata=json.loads(row[0]) if row else {}
        owners=set(metadata.get('submitted_task_ids') or [])
        if metadata.get('submitted_task_id'):owners.add(metadata['submitted_task_id'])
        owners.discard(str(task_id))
        if owners:
            metadata['submitted_task_ids']=sorted(owners);metadata['submitted_task_id']=sorted(owners)[0]
        else:
            metadata.pop('submitted_task_id',None);metadata.pop('submitted_task_ids',None)
        db.execute("UPDATE meta SET value=? WHERE key='training_selection'",(json.dumps(metadata,sort_keys=True),));db.commit()


def freeze_selection(data_dir,context,image_ids,*,request_id=None,request_scope=''):
    if request_id:
        try:
            identity=uuid.UUID(str(request_id))
            if identity.version!=4:raise ValueError('request_id must be a random UUID4')
        except (ValueError,TypeError,AttributeError) as error:raise ValueError('invalid selection request_id') from error
        reference='trainselection_'+identity.hex
    else:reference='trainselection_'+secrets.token_hex(16)
    path=_path(data_dir,reference)
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with FileLock(str(path)+'.freeze.lock',timeout=5):
            if path.is_file():
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                    row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
                    existing=json.loads(row[0]) if row else {}
                if existing.get('context')!=context or existing.get('request_scope')!=request_scope:
                    raise ValueError('素材选择请求已绑定其他范围或证据已变化')
                ids=read_selection(data_dir,reference,context)
                return {'selection_ref':reference,'count':len(ids)}
            # Explicit bound; never delete a manifest that may back a queued task.
            quota=max(1,int(os.environ.get('MC_TRAIN_SELECTION_MAX_REFERENCES','128')))
            if _draft_quota_count(data_dir,path.parent.parent,context.get('project_id'),stop_at=quota)>=quota:
                raise ValueError('服务器冻结选择数量达到配额，请先按任务产物保留策略整理')
            if shutil.disk_usage(path.parent).free<512*1024*1024:
                raise ValueError('服务器冻结选择磁盘空间不足，至少需要512MiB预留')
            try:return _write_selection(data_dir,context,image_ids,reference,request_scope)
            except BaseException:
                # Only this newly generated, checked manifest; no recursive deletion.
                for suffix in ('','-wal','-shm'):
                    candidate=_path(data_dir,reference).with_name('selection.sqlite3'+suffix)
                    candidate.unlink(missing_ok=True)
                raise
    finally:
        if not request_id and not path.exists():
            Path(str(path)+'.freeze.lock').unlink(missing_ok=True)
            try:path.parent.rmdir()
            except OSError:pass


def read_selection(data_dir,reference,context):
    path=_path(data_dir,reference)
    if not path.is_file():raise ValueError('训练素材选择已失效，请重新选择')
    if path.stat().st_size>MAX_FROZEN_SELECTION_BYTES:raise ValueError('selection manifest exceeds byte quota')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
        if not row:raise ValueError('训练素材选择证据不完整')
        metadata=json.loads(row[0])
        if _expired(metadata):raise ValueError('冻结素材选择已过期，请重新选择')
        if not _same_selection_context(metadata,context):raise ValueError('算法、策略或素材证据已更新，请重新选择训练素材')
        expected=metadata.get('count')
        if isinstance(expected,bool) or not isinstance(expected,int) or not 0<expected<=MAX_FROZEN_SELECTION_IDS:raise ValueError('invalid selection size')
        if db.execute('SELECT COUNT(*) FROM selection').fetchone()[0]!=expected:raise ValueError('selection count mismatch')
        ids=[]
        cursor=db.execute('SELECT image_id FROM selection ORDER BY image_id')
        while True:
            chunk=cursor.fetchmany(1000)
            if not chunk:break
            ids.extend(row[0] for row in chunk)
            if len(ids)>MAX_FROZEN_SELECTION_IDS:raise ValueError('selection exceeds row quota')
    digest=hashlib.sha256()
    for identity in ids:digest.update((identity+'\0').encode())
    if len(ids)!=metadata['count'] or digest.hexdigest()!=metadata['sha256']:
        raise ValueError('训练素材选择清单损坏，请重新选择')
    return ids


def selection_context(data_dir,project_id,payload,role='train'):
    from .material_repository import MaterialRepository
    from .annotation_repository import AnnotationRepository
    from .training_material_usage import TrainingMaterialUsage
    from .negative_pool import NegativePool
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(project_id)):raise ValueError('invalid project identity')
    if role not in {'train','test'}:raise ValueError('invalid selection role')
    materials=MaterialRepository(Path(data_dir)/'projects'/str(project_id))
    annotations=AnnotationRepository(materials.project_path)
    contract={key:str(payload.get(key) or '') for key in ('base_version_id','framework')}
    legacy_contract={**contract,'train_labels':sorted(set(payload.get('train_labels') or []))}
    return {'project_id':str(project_id),'algorithm_id':str(payload.get('algorithm_asset_id') or ''),
        'role':role,'history_policy':str(payload.get('history_policy') or 'new_for_algorithm'),
        'revisions':[str(materials.current_revision()),str(annotations.current_revision()),
            str(TrainingMaterialUsage(Path(data_dir)/'task_runtime'/'tasks.sqlite3').read_revision()),
            str(NegativePool(materials).revision()),str(annotations.task_negative_confirmation_revision())],
        'contract':hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest(),
        # v2: ordinary fixed-ID selections must survive choosing task labels
        # *after* the picker closes. Role-filtered selections remain label-bound.
        'legacy_contract':hashlib.sha256(json.dumps(legacy_contract,sort_keys=True).encode()).hexdigest(),
        'contract_schema':2}


def _same_selection_context(metadata, current):
    frozen=metadata.get('context') or {}
    if 'contract_schema' not in current:
        # AI annotation and other owners use their own exact context shape.
        return frozen==current
    if frozen.get('contract_schema')!=2:
        # Existing manifests keep their original, strict label-bound contract.
        legacy={key:value for key,value in current.items() if key not in ('contract_schema','legacy_contract')}
        legacy['contract']=current.get('legacy_contract')
        return frozen==legacy
    scope=metadata.get('request_scope') or ''
    if not scope:
        role_filtered=False
    else:
        try:role_filtered=bool(json.loads(scope).get('sample_role'))
        except (TypeError,ValueError,AttributeError):return False
    if role_filtered:
        return frozen==current
    # For unfiltered/fixed-ID selections the immutable IDs, algorithm, base
    # version, framework, policy and all five revisions stay exactly bound.
    return {k:v for k,v in frozen.items() if k!='legacy_contract'}=={
        k:v for k,v in current.items() if k!='legacy_contract'}


def validate_payload_references(data_dir,project_id,payload):
    """Worker repeats identity/revision and exact expanded-ID checks before freeze."""
    for role in ('train','test'):
        reference=payload.get(role+'_selection_ref')
        if not reference:continue
        context=selection_context(data_dir,project_id,payload,role)
        ids=read_selection(data_dir,reference,context)
        if ids!=list(payload.get(role+'_image_ids') or []):
            raise ValueError('训练输入与冻结素材选择引用不一致')


def selection_membership(data_dir,reference,context,image_ids):
    if not isinstance(image_ids,list) or len(image_ids)>100:raise ValueError('selection preview limited to100')
    path=_path(data_dir,reference)
    if not path.is_file():raise ValueError('selection no longer exists')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT value FROM meta WHERE key='training_selection'").fetchone()
        if row and _expired(json.loads(row[0])):raise ValueError('冻结素材选择已过期，请重新选择')
        if not row or not _same_selection_context(json.loads(row[0]),context):raise ValueError('选择证据已变化，请重新选择')
        return [r[0] for r in db.execute('SELECT image_id FROM selection WHERE image_id IN (SELECT value FROM json_each(?))',(json.dumps(image_ids),))]
