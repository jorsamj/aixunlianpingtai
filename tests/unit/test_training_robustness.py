import pytest
from PIL import Image
from platform_core.training_robustness import normalize_policy, transform_rgb, select_train_ids, read_global_policy, save_global_policy


def test_four_color_presets_are_real_deterministic_mismatch_simulations():
    image = Image.new('RGB', (3, 2), (71, 137, 213))
    expected={'bt601_limited':(70,132,204),'bt601_full':(58,138,232),'bt709_limited':(81,135,197),'bt709_full':(73,142,223)}
    assert len(set(expected.values()))==4
    for preset in expected:
        result = transform_rgb(image, preset)
        assert result.tobytes() != image.tobytes()
        assert result.tobytes() == transform_rgb(image, preset).tobytes()
        assert result.size == image.size
        assert result.getpixel((0,0))==expected[preset]


def test_selection_is_stable_and_manual_rejects_validation():
    policy = normalize_policy({'mode': 'enabled', 'selection': {'mode': 'count', 'count': 2}})
    assert select_train_ids(['a','b','c'], policy) == select_train_ids(['c','b','a'], policy)
    with pytest.raises(ValueError,match='CSC_SELECTION_COUNT_EXCEEDS_TRAIN'):
        select_train_ids(['a'],policy)
    policy['selection'] = {'mode': 'manual', 'image_ids': ['val']}
    with pytest.raises(ValueError, match='train'):
        select_train_ids(['a'], policy)


def test_global_policy_cas_defaults_off(tmp_path):
    original = read_global_policy(tmp_path)
    assert original['policy']['enabled'] is False
    saved = save_global_policy(tmp_path, {'enabled': True}, original['revision'])
    assert saved['policy']['enabled'] is True
    with pytest.raises(ValueError, match='revision'):
        save_global_policy(tmp_path, {'enabled': False}, original['revision'])


@pytest.mark.parametrize('field', ['copies','seed','count'])
@pytest.mark.parametrize('value', [1.5, True])
def test_integer_policy_fields_do_not_truncate_or_accept_bool(field, value):
    policy = {field: value} if field != 'count' else {'selection': {'mode':'count','count':value}}
    with pytest.raises(ValueError):
        normalize_policy(policy)


@pytest.mark.parametrize('policy', [
    {'presets':'bt601_full'}, {'selection': {'mode':'manual','image_ids':'A'}},
])
def test_policy_collections_are_lists(policy):
    with pytest.raises(ValueError):
        normalize_policy(policy)


def test_materialized_augmentation_preserves_negative_source_and_replays(tmp_path):
    import hashlib
    import json
    from platform_core.training_tasks import materialize_portable_dataset, verify_portable_dataset
    source = tmp_path / 'source.png'
    Image.new('RGB', (8, 8), (71, 137, 213)).save(source)
    original = source.read_bytes()
    sha = hashlib.sha256(original).hexdigest()
    rows = [{'id': 'one', 'stored_name': 'source.png', 'width': 8, 'height': 8,
             'size_bytes': len(original), 'content_sha256': sha, 'boxes': []}]
    snapshot = {'schema_version': 2, 'snapshot_id': 'snapshot-one',
        'ids': {'train': ['one'], 'validation': [], 'test': []}, 'label_schema': [],
        'images': [{'image_id': 'one', 'role': 'train', 'content_sha256': sha,
                    'source_root_id': 'root-original', 'source_group_id': 'source-group'}],
        'robustness_policy': normalize_policy({'mode': 'enabled', 'copies': 3,
            'selection': {'mode': 'ratio', 'ratio': 100}})}
    root = materialize_portable_dataset(tmp_path/'task', snapshot, rows, lambda row: source, safety_reserve_bytes=0)
    manifest = json.loads((root/'manifest.json').read_text())
    assert len(manifest['splits']['train']) == 4
    from platform_core.training_robustness import augmentation_summary
    summary=augmentation_summary(manifest)
    assert summary['original_train_images']==1 and summary['augmented_images']==3 and summary['actual_train_images']==4
    derived = manifest['splits']['train'][1]['augmentation']
    assert derived['source_root_id'] == 'root-original'
    assert derived['derived_from_image_id'] == 'one'
    assert derived['source_group_id'] == 'source-group'
    assert derived['transformation_params']['seed'] == 0
    assert derived['transformation_params']['encode_standard'] != derived['transformation_params']['decode_standard']
    assert derived['transformation_params']['encode_range'] != derived['transformation_params']['decode_range']
    assert all((root/item['label_ref']).read_bytes() == b'' for item in manifest['splits']['train'])
    assert source.read_bytes() == original
    assert verify_portable_dataset(root/'manifest.json')['verified_files'] == 4
    expected = [(item['image_ref'], item['content_sha256']) for item in manifest['splits']['train']]
    materialize_portable_dataset(tmp_path/'task', snapshot, rows, lambda row: source, safety_reserve_bytes=0)
    replay = json.loads((root/'manifest.json').read_text())
    assert [(item['image_ref'], item['content_sha256']) for item in replay['splits']['train']] == expected


def test_noop_pixels_cannot_be_counted_as_successful_augmentation(tmp_path):
    import hashlib
    from platform_core.training_robustness import augment_bundle
    root=tmp_path
    (root/'dataset/images/train').mkdir(parents=True)
    (root/'dataset/labels/train').mkdir(parents=True)
    image=root/'dataset/images/train/source.png'
    Image.new('RGB',(4,4),(0,0,0)).save(image)
    label=root/'dataset/labels/train/source.txt';label.write_bytes(b'')
    before=image.read_bytes()
    policy=normalize_policy({'mode':'enabled','presets':['bt601_full'],'selection':{'mode':'ratio','ratio':100}})
    row={'image_id':'a','image_ref':'dataset/images/train/source.png','label_ref':'dataset/labels/train/source.txt','content_sha256':hashlib.sha256(before).hexdigest()}
    splits={'train':[row],'validation':[],'test':[]}
    with pytest.raises(ValueError,match='CSC_NO_PIXEL_CHANGE'):
        augment_bundle(root,{'ids':{'train':['a']},'images':[]},splits,policy,safety_reserve_bytes=0)
    assert splits['train']==[row] and image.read_bytes()==before and label.read_bytes()==b''
    assert not list((root/'dataset/images/train').glob('robustness_*.png'))
