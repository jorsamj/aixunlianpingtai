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


def test_sdk_capability_survives_five_minutes_but_not_environment_or_config_change(tmp_path):
    from datetime import timedelta
    checked = (datetime.now(timezone.utc)-timedelta(minutes=8)).isoformat()
    tool = tmp_path/'sdk-python';tool.write_bytes(b'version-one')
    original={'id':'isolated-sdk-fingerprint','kind':'rockchip','mode':'local',
              'config_revision':'rev-one','python_path':str(tool),
              'last_checked_at':checked,'status':'ready','targets':['rockchip']}
    row={**original,'detection_config_key':detection.resource_configuration_key(original),
         'detection_environment_fingerprint':detection.environment_fingerprint(original)}
    assert detection.observe(row)['detection']['state']=='available'
    assert detection.observe({**row,'config_revision':'rev-two'})['detection']['state']=='not_checked'
    tool.write_bytes(b'version-two-different')
    assert detection.observe(row)['detection']['state']=='expired'
    old={**original,'last_checked_at':'2000-01-01T00:00:00+00:00'}
    assert detection.observe(old)['detection']['state']=='expired'


def test_stale_cross_worker_detection_is_recoverable_without_false_ready():
    old={'id':'isolated-dead-worker','kind':'sophon','mode':'remote',
         'status':'ready','targets':['sophon'],'last_checked_at':datetime.now(timezone.utc).isoformat()}
    old['detection_run']={'id':'dead-run','state':'checking','config_key':detection.resource_configuration_key(old),
                          'started_at':'2000-01-01T00:00:00+00:00'}
    result=detection.observe(old)['detection']
    assert result['state']=='expired'
    assert result['reason']=='interrupted_detection'


def test_dead_worker_does_not_keep_checking_for_the_entire_lease():
    import socket
    original={'id':'isolated-dead-worker-pid','kind':'rockchip','mode':'local',
              'last_checked_at':datetime.now(timezone.utc).isoformat(),
              'status':'ready','targets':['rockchip']}
    original['detection_run']={'id':'dead-pid','state':'checking',
        'started_at':datetime.now(timezone.utc).isoformat(),
        'config_key':detection.resource_configuration_key(original),
        'owner_host':socket.gethostname(),'owner_pid':2147483647,
        'owner_started_at':1000.0}
    result=detection.observe(original)['detection']
    assert result['state']=='expired' and result['reason']=='interrupted_detection'
