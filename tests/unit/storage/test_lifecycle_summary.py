from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.storage.cache import MaterialCache, resolve_material_cache_location, file_sha256
from platform_core.storage.lifecycle_summary import storage_lifecycle_summary
from PIL import Image
import json
import pytest


def test_summary_is_readonly_and_unknown_is_not_zero(tmp_path, monkeypatch):
    monkeypatch.delenv('MC_MATERIAL_CACHE_DIR', raising=False)
    result = storage_lifecycle_summary(tmp_path, 'p')
    assert all(metric['value'] is None for metric in result['metrics'].values())
    assert list(tmp_path.iterdir()) == []
    project = tmp_path / 'projects/p'
    materials = MaterialRepository(project)
    AnnotationRepository(project)
    materials.upsert({'id':'i', 'filename':'a.jpg', 'size_bytes':17})
    before = {str(path):path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    result = storage_lifecycle_summary(tmp_path, 'p')
    assert result['metrics']['original_index_logical_bytes']['value'] == 17
    assert result['metrics']['gt_index_logical_bytes']['value'] > 0
    assert result['metrics']['worker_workspace_logical_bytes']['value'] is None
    assert result['physical_space_released'] is None
    assert before == {str(path):path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    materials.upsert({'id':'missing', 'filename':'b.jpg', 'size_bytes':0})
    assert storage_lifecycle_summary(tmp_path, 'p')['metrics']['original_index_logical_bytes']['value'] is None


def test_summary_reuses_existing_cache_snapshot_instead_of_scanning(tmp_path, monkeypatch):
    monkeypatch.delenv('MC_MATERIAL_CACHE_DIR', raising=False)
    source = tmp_path / 'source.png'
    Image.new('RGB', (40,20), 'blue').save(source)
    cache = MaterialCache(resolve_material_cache_location(tmp_path).root)
    cache.thumbnail(file_sha256(source), lambda:source, max_edge=16)
    observed = cache.maintain()
    assert observed['thumbnail_logical_bytes'] > 0
    result = storage_lifecycle_summary(tmp_path, 'p')
    assert result['metrics']['thumbnail_cache_logical_bytes']['value'] == observed['thumbnail_logical_bytes']
    assert result['metrics']['shared_cache_logical_bytes']['value'] == observed['after_bytes']
    assert result['sampled_at']


@pytest.mark.parametrize('complete', [None, False, True])
def test_summary_requires_explicit_complete_cache_inventory(tmp_path, monkeypatch, complete):
    monkeypatch.delenv('MC_MATERIAL_CACHE_DIR', raising=False)
    cache = MaterialCache(resolve_material_cache_location(tmp_path).root)
    cache.maintain()
    path = cache.root / 'status.json'
    snapshot = json.loads(path.read_text())
    snapshot.update(after_bytes=1234, thumbnail_logical_bytes=123)
    if complete is None:
        snapshot.pop('inventory_complete', None)
    else:
        snapshot['inventory_complete'] = complete
    path.write_text(json.dumps(snapshot))
    result = storage_lifecycle_summary(tmp_path, 'p')['metrics']
    assert result['shared_cache_logical_bytes']['value'] == (1234 if complete is True else None)
    assert result['thumbnail_cache_logical_bytes']['value'] == (123 if complete is True else None)
