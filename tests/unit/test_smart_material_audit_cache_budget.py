from types import SimpleNamespace
from pathlib import Path

import pytest

from platform_core.smart_material_audit.worker import _materialize_input
from platform_core.storage.models import StorageType
from platform_core.storage.cache import MaterializedFile


def manager_for(tmp_path,size):
    calls={'download':0,'stat':0}
    def stat(key):
        calls['stat']+=1
        return SimpleNamespace(size_bytes=size)
    def download(*args,**kwargs):
        calls['download']+=1
        raise AssertionError('budget check must precede download')
    provider=SimpleNamespace(storage_type=StorageType.S3,stat=stat)
    manager=SimpleNamespace(material=lambda value:value,provider_for=lambda key:provider,
        cache=SimpleNamespace(path_for=lambda sha,suffix:tmp_path/'shared.jpg'),materialize=download)
    image=dict(filename='one.jpg',object_key='one.jpg',content_sha256='a'*64,storage_source_id='fixture')
    return manager,image,calls


def test_exhausted_cache_budget_never_downloads_remaining_rows(tmp_path):
    manager,image,calls=manager_for(tmp_path,10)
    for _ in range(3):
        with pytest.raises(ValueError,match='预算已用尽'):
            _materialize_input(manager,image,{},512*1024*1024)
    assert calls=={'download':0,'stat':0}


def test_object_larger_than_remaining_budget_is_rejected_before_download(tmp_path):
    manager,image,calls=manager_for(tmp_path,512*1024*1024+1)
    with pytest.raises(ValueError,match='未下载'):
        _materialize_input(manager,image,{},0)
    assert calls=={'download':0,'stat':1}


def test_same_cached_sha_reuses_pinned_file_without_recursive_lock_or_download(tmp_path):
    manager,image,calls=manager_for(tmp_path,10)
    local=MaterializedFile(tmp_path/'shared.jpg','a'*64,10,True)
    assert _materialize_input(manager,image,{str(local.path):local},10) is local
    assert calls=={'download':0,'stat':0}

@pytest.mark.parametrize('field',['_dataset_delete_claim','_material_batch_delete_claim'])
def test_active_delete_claim_is_preserved_without_reading_source(tmp_path,field):
    manager,image,calls=manager_for(tmp_path,10);image[field]={'owner':'retain'}
    with pytest.raises(ValueError,match='删除或恢复占用'):
        _materialize_input(manager,image,{},0)
    assert image[field]=={'owner':'retain'} and calls=={'download':0,'stat':0}
