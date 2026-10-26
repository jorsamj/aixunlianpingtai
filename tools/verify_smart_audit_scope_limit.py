"""Isolated 10k/100k metadata admission boundary; NOT an engine scale benchmark."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import psutil

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_core.material_repository import MaterialRepository
from platform_core.material_batches import BatchRequestError
from platform_core.smart_material_audit.service import estimate_audit


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    results=[]
    with tempfile.TemporaryDirectory(prefix='smart-scope-boundary-owned-') as temporary:
        root=Path(temporary);project=root/'projects/p';owner=MaterialRepository(project)
        binary=root/'optional/Scripts/python.exe';binary.parent.mkdir(parents=True);binary.write_bytes(b'not executed')
        (binary.parent.parent/'pyvenv.cfg').write_text('include-system-site-packages = false\n')
        (root/'smart_material_audit.json').write_text(json.dumps(dict(enabled=True,python=str(binary),max_images=2000)))
        inserted=0
        for count in [10000,100000]:
            for start in range(inserted,count,1000):
                owner.upsert_many(dict(id=f'image-{index:06}',filename=f'{index}.jpg',content_sha256='a'*64)
                    for index in range(start,min(count,start+1000)))
            inserted=count
            database=project/'materials.sqlite3';before=digest(database);calls=[]
            connect=MaterialRepository._connect
            def traced(self):
                connection=connect(self);connection.set_trace_callback(calls.append);return connection
            MaterialRepository._connect=traced
            rss=psutil.Process().memory_info().rss;started=time.perf_counter()
            try:
                try:estimate_audit(root,'p',dict(scope='FILTERED',filters={}))
                except BatchRequestError as error:assert error.code=='SMART_AUDIT_SCOPE_LIMIT'
                else:raise AssertionError('unverified large engine scope was admitted')
            finally:MaterialRepository._connect=connect
            elapsed=time.perf_counter()-started
            assert not any('SELECT m.id FROM materials' in sql for sql in calls)
            assert before==digest(database)
            with closing(owner._connect()) as connection:assert connection.execute('SELECT COUNT(*) FROM materials').fetchone()[0]==count
            assert not (root/'tasks.sqlite3').exists() and not (root/'artifacts').exists()
            results.append(dict(material_metadata_count=count,scope_rejected_before_id_loading=True,
                original_database_unchanged=True,elapsed_seconds=round(elapsed,5),
                rss_end_minus_start_bytes=psutil.Process().memory_info().rss-rss,engine_started=False))
    Path(args.out).write_text(json.dumps(dict(scope='metadata-only admission safety, not actual image/engine throughput',
        cases=results,owned_temporary_root_cleaned=True),indent=2),encoding='utf-8')
    print(json.dumps(results),flush=True)


if __name__=='__main__':main()
