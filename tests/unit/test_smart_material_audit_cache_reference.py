import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.storage.cache import MaterialCache,MaterializedFile
from platform_core.smart_material_audit.worker import _pin_cached_reference


def test_analysis_reference_keeps_bytes_without_blocking_other_original_cache_readers(tmp_path):
    cache=MaterialCache(tmp_path/'cache',allow_maintenance=False)
    payload=b'immutable cached material';sha=hashlib.sha256(payload).hexdigest()
    source=cache.path_for(sha,'.jpg');source.parent.mkdir(parents=True);source.write_bytes(payload)
    local=MaterializedFile(source,sha,len(payload),True)
    working=tmp_path/'owned-working';working.mkdir()
    pinned=_pin_cached_reference(cache,local,working)
    assert source.stat().st_ino==pinned.path.stat().st_ino and source.stat().st_nlink==2
    provider=SimpleNamespace(materialize_to_local=lambda *_:pytest.fail('cache hit must not download'))
    # Original cache materialize acquires its object lock; it must remain immediately available.
    same=cache.materialize(provider,'unused',expected_sha256=sha,suffix='.jpg')
    assert same.cache_hit and same.path==source
    source.unlink()  # A simulated original-cache eviction cannot invalidate the active read reference.
    assert pinned.path.read_bytes()==payload
    pinned.path.unlink();assert not pinned.path.exists()


def test_cross_device_reference_fails_without_copy_or_shared_lock_leak(tmp_path,monkeypatch):
    cache=MaterialCache(tmp_path/'cache',allow_maintenance=False)
    payload=b'bytes';sha=hashlib.sha256(payload).hexdigest();source=cache.path_for(sha,'.jpg');source.parent.mkdir(parents=True);source.write_bytes(payload)
    monkeypatch.setattr('platform_core.smart_material_audit.worker.os.link',lambda *_a,**_k:(_ for _ in ()).throw(OSError('cross device')))
    with pytest.raises(ValueError,match='安全硬链接'):
        _pin_cached_reference(cache,MaterializedFile(source,sha,len(payload),True),tmp_path/'working')
    assert source.read_bytes()==payload and source.stat().st_nlink==1
