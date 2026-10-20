"""Read-only model metadata/Weight receipt audit; local repair is explicitly opt-in.

Never sends provider requests or uploads. External edits remain with the existing publish Owner.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from platform_core.algorithm_sql_store import AlgorithmSqlStore
from platform_core.model_metadata import model_metadata


def read_rows(path, query, args=()):
    if not path.is_file(): return []
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(row) for row in db.execute(query,args)]


def object_json(raw):
    try:
        value=json.loads(raw or '{}')
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError): return {}


def audit(data_dir, project_id):
    root=Path(data_dir).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',project_id): raise ValueError('project_id非法')
    project=root/'projects'/project_id
    database=project/'algorithms.sqlite3'
    algorithms=[]
    if database.is_file():
        store=AlgorithmSqlStore(project/'algorithms.json')
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            for row in db.execute('SELECT id FROM algorithms WHERE project_id=?',(project_id,)):
                algorithms.append(store._read_one_conn(db,row['id']))
    artifacts=read_rows(root/'model_artifacts'/'artifacts.sqlite3','SELECT * FROM model_artifacts WHERE project_id=?',(project_id,))
    mappings=read_rows(root/'external_algorithm_publish'/'publications.sqlite3','SELECT * FROM external_artifact_publications WHERE active=1')
    result=[]
    for asset in artifacts:
        algorithm=next((a for a in algorithms if a['id']==asset['algorithm_id']),{})
        version=next((v for v in algorithm.get('versions',[]) if v['id']==asset['version_id']),{})
        meta=object_json(asset.get('metadata_json'))
        frozen=model_metadata(root,version,algorithm=algorithm)
        expected=frozen.get('tags')
        path=Path(asset.get('source_path') or '')
        verified=False
        if path.is_file() and path.stat().st_size==asset['size_bytes']:
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
            verified=digest.hexdigest()==asset['sha256']
        candidates=[m for m in mappings if m['artifact_id']==asset['artifact_id'] and m['provider']=='CHANG_LIAN']
        mapping=candidates[0] if len(candidates)==1 else {}
        confirmed=object_json(mapping.get('synced_payload_json'))
        conflict=bool(meta.get('tags') and expected and meta['tags']!=expected)
        state='CONFLICT' if conflict or frozen.get('label_validation_status')=='CONFLICT' else 'IDENTITY_UNVERIFIED' if not verified else 'LABELS_UNKNOWN' if not expected else 'LOCAL_REPAIR_REQUIRED' if meta.get('tags')!=expected else 'LOCAL_VERIFIED'
        result.append({**{key:asset.get(key) for key in ('artifact_id','algorithm_id','version_id','target','sha256','size_bytes','storage_source_id','object_key','public_url')},
            'file_identity_verified':verified,'frozen_tags':expected,'local_tags':meta.get('tags'),'local_state':state,
            'external_weight_id':mapping.get('external_weight_id'),'compute_platform_id':mapping.get('compute_platform_id'),
            'chip_code':mapping.get('remote_chip_code'),'sync_status':mapping.get('sync_status'),
            'confirmed_tags':confirmed.get('tags'),'remote_tags_status':'NOT_VERIFIED',
            'external_action':'EDIT_CANDIDATE_REQUIRES_REMOTE_IDENTITY' if expected and verified and not conflict and len(candidates)==1 and mapping.get('external_weight_id') and mapping.get('sync_status')!='UNKNOWN' and confirmed.get('tags')!=expected else 'UNKNOWN_REQUIRES_READBACK' if mapping.get('sync_status')=='UNKNOWN' else 'NO_AUTOMATIC_WRITE',
            'note':frozen.get('label_error') or ''})
    return {'project_id':project_id,'read_only':True,'artifacts':result,'external_requests_sent':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--apply-local',action='store_true',help='Explicitly authorized local canonical repair only; never external/OSS writes')
    parser.add_argument('--output')
    args=parser.parse_args(argv)
    report=audit(args.data_dir,args.project)
    if args.apply_local:
        from platform_core.model_artifacts import record_version_model_metadata
        versions={(r['algorithm_id'],r['version_id']) for r in report['artifacts'] if r['local_state']=='LOCAL_REPAIR_REQUIRED'}
        applied=[]
        for algorithm_id,version_id in sorted(versions):
            try:
                rows=record_version_model_metadata(Path(args.data_dir)/'projects'/args.project/'algorithms.json',algorithm_id,version_id)
                applied.append({'algorithm_id':algorithm_id,'version_id':version_id,'artifacts':[r['artifact_id'] for r in rows],
                    'conflicts':[r['artifact_id'] for r in rows if (r.get('metadata') or {}).get('label_validation_status')=='CONFLICT']})
            except Exception as error:
                applied.append({'algorithm_id':algorithm_id,'version_id':version_id,'error':str(error)})
        report=audit(args.data_dir,args.project)
        report.update(read_only=False,local_repair_results=applied)
    body=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(body,encoding='utf-8')
    else: print(body)
    return 0


if __name__=='__main__': raise SystemExit(main())
