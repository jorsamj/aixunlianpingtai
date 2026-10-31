from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time
from datetime import datetime, timezone

from platform_core import conversion_resource_detection as detection


def test_read_only_observation_and_concurrent_selected_detection():
    resource={'id':'isolated-conversion-probe','kind':'onnx','mode':'local','status':'unchecked'}
    assert detection.observe(resource)['detection']['state']=='not_checked'
    calls=[]; gate=Barrier(2)
    def inspect(row):
        assert detection.observe(row)['detection']['state']=='checking'
        calls.append(row['id']);time.sleep(.03)
        return {**row,'status':'ready','targets':['onnx']}
    def request():
        gate.wait();return detection.detect(resource,inspect,force=True)
    with ThreadPoolExecutor(2) as executor:
        rows=list(executor.map(lambda _:request(),range(2)))
    assert len(calls)==1
    assert all(r['detection']['state']=='available' for r in rows)
    detection.detect(resource,inspect)
    assert len(calls)==1
    changed={**resource,'python_path':'changed-interpreter'}
    assert detection.observe(changed)['detection']['state']=='not_checked'
    detection.detect(changed,inspect)
    assert len(calls)==2
    stale={**resource,'id':'isolated-stale-probe','status':'ready','last_checked_at':'2000-01-01T00:00:00+00:00'}
    assert detection.observe(stale)['detection']['state']=='expired'


def test_persisted_probe_failure_invalidates_older_process_local_ready_snapshot():
    resource={'id':'isolated-persistent-probe-change','kind':'sophon','mode':'remote','status':'missing'}
    detection.detect(resource,lambda row:{**row,'status':'ready','targets':['sophon']},force=True)
    assert detection.observe(resource)['detection']['state']=='available'
    # Another worker explicitly scanned the same configuration and persisted a
    # failure. The old ready TTL must never override its durable observation.
    failed={**resource,'status':'missing','last_checked_at':datetime.now(timezone.utc).isoformat()}
    observed=detection.observe(failed)
    assert observed['status']=='missing'
    assert observed['detection']['state']=='unavailable'
