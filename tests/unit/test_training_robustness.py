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




def test_positive_multiclass_train_only_augmentation_reaches_verified_bundle(tmp_path):
    """Real person/smoke YOLO boxes survive augmentation; val/test remain isolated."""
    import hashlib
    import json
    import yaml
    from platform_core.training_tasks import (
        materialize_portable_dataset, resolve_remote_training_bundle,
        verify_portable_dataset,
    )
    from platform_core.training_robustness import augmentation_summary

    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    roles = {"train": ["person-train", "smoke-train"],
             "validation": ["person-val"], "test": ["smoke-test"]}
    colors = {"person-train": (81, 139, 207), "smoke-train": (173, 71, 92),
              "person-val": (46, 184, 71), "smoke-test": (91, 51, 155)}
    boxes = {
        "person-train": [{"label": "person", "x1": 4, "y1": 2, "x2": 20, "y2": 10}],
        "smoke-train": [{"label": "smoke", "x1": 12, "y1": 3, "x2": 28, "y2": 16}],
        "person-val": [{"label": "person", "x1": 4, "y1": 2, "x2": 20, "y2": 10}],
        "smoke-test": [{"label": "smoke", "x1": 12, "y1": 3, "x2": 28, "y2": 16}],
    }
    sources, rows, frozen = {}, [], []
    for role, ids in roles.items():
        for image_id in ids:
            source = source_dir / f"{image_id}.jpg"
            Image.new("RGB", (40, 20), colors[image_id]).save(source, format="JPEG")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            sources[image_id] = source
            rows.append({
                "id": image_id, "stored_name": source.name, "width": 40, "height": 20,
                "size_bytes": source.stat().st_size, "content_sha256": digest,
                "boxes": boxes[image_id],
            })
            frozen.append({
                "image_id": image_id, "role": role, "content_sha256": digest,
                "source_root_id": f"root-{image_id}",
                "source_group_id": f"group-{image_id}",
                "annotation_state": "annotated",
                "annotation_hash": hashlib.sha256(("formal:" + image_id).encode()).hexdigest(),
            })

    policy = normalize_policy({
        "mode": "enabled", "copies": 2,
        "presets": ["bt601_limited", "bt709_full"], "seed": 12,
        "selection": {"mode": "count", "count": 2},
    })
    snapshot = {
        "schema_version": 3, "snapshot_id": "p" * 64, "ids": roles,
        "label_schema": [{"code": "person", "class_id": 0},
                         {"code": "smoke", "class_id": 1}],
        "images": frozen, "robustness_policy": policy,
    }
    before = {image_id: source.read_bytes() for image_id, source in sources.items()}
    task_root = tmp_path / "task"
    bundle = materialize_portable_dataset(
        task_root, snapshot, rows, lambda row: sources[row["id"]],
        safety_reserve_bytes=0,
    )
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    splits = manifest["splits"]
    originals = [row for row in splits["train"] if not row.get("augmentation")]
    derived = [row for row in splits["train"] if row.get("augmentation")]
    assert len(originals) == 2 and len(derived) == 4
    assert [row["image_id"] for row in splits["validation"]] == roles["validation"]
    assert [row["image_id"] for row in splits["test"]] == roles["test"]
    assert not any(row.get("augmentation") for role in ("validation", "test")
                   for row in splits[role])
    assert set(row["augmentation"]["derived_from_image_id"] for row in derived) == set(roles["train"])
    assert len({row["image_ref"] for row in splits["train"]}) == 6
    assert len({row["label_ref"] for row in splits["train"]}) == 6
    assert len(list((bundle / "dataset/images/train").glob("*"))) == 6
    assert len(list((bundle / "dataset/labels/train").glob("*.txt"))) == 6
    assert len(list((bundle / "dataset/images/validation").glob("*"))) == 1
    assert len(list((bundle / "dataset/images/test").glob("*"))) == 1

    expected_boxes = {
        "person-train": (0, .3, .3, .4, .4),
        "smoke-train": (1, .5, .475, .4, .65),
    }
    original_by_id = {row["image_id"]: row for row in originals}
    for member in derived:
        origin_id = member["augmentation"]["derived_from_image_id"]
        original = original_by_id[origin_id]
        source_label = (bundle / original["label_ref"]).read_bytes()
        generated_label = (bundle / member["label_ref"]).read_bytes()
        assert source_label and generated_label == source_label
        assert member["label_sha256"] == hashlib.sha256(generated_label).hexdigest()
        label_values = tuple(map(float, generated_label.decode("utf-8").split()))
        assert label_values == pytest.approx(expected_boxes[origin_id], abs=1e-8)
        assert member["augmentation"]["source_root_id"] == f"root-{origin_id}"
        assert member["augmentation"]["source_group_id"] == f"group-{origin_id}"
        assert member["augmentation"]["source_training_sha256"] == original["content_sha256"]
        with Image.open(bundle / member["image_ref"]) as augmented:
            assert augmented.size == (40, 20)
            assert augmented.format == "PNG"
            with Image.open(bundle / original["image_ref"]) as source:
                assert augmented.convert("RGB").tobytes() != source.convert("RGB").tobytes()

    actual = augmentation_summary(manifest)
    assert actual["original_train_images"] == 2
    assert actual["augmented_images"] == 4
    assert actual["actual_train_images"] == 6
    assert actual["validation_images"] == 1
    assert actual["test_images"] == 1
    assert manifest["robustness_derived_count"] == 4
    yaml_data = yaml.safe_load((bundle / "dataset/data.yaml").read_text(encoding="utf-8"))
    assert yaml_data["train"] == "images/train"
    assert yaml_data["val"] == "images/validation"
    assert yaml_data["names"] == {0: "person", 1: "smoke"}
    assert "test" not in yaml_data
    assert not (bundle / "dataset/labels/test").exists()
    assert verify_portable_dataset(manifest_path)["verified_files"] == 8
    received = resolve_remote_training_bundle(manifest_path)
    assert received.verified_files == 8
    assert {key: source.read_bytes() for key, source in sources.items()} == before

    # Replaying the same frozen task preserves derived identities and hashes.
    fingerprint = sorted((row["image_ref"], row["content_sha256"], row["label_sha256"])
                         for row in derived)
    materialize_portable_dataset(
        task_root, snapshot, rows, lambda row: sources[row["id"]],
        safety_reserve_bytes=0,
    )
    replay = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sorted((row["image_ref"], row["content_sha256"], row["label_sha256"])
                  for row in replay["splits"]["train"] if row.get("augmentation")) == fingerprint
    assert verify_portable_dataset(manifest_path)["verified_files"] == 8

    # The verifier fails closed if any generated YOLO GT is changed afterwards.
    (bundle / derived[0]["label_ref"]).write_text("1 0.5 0.5 0.5 0.5", encoding="utf-8")
    with pytest.raises(ValueError, match="label SHA256"):
        verify_portable_dataset(manifest_path)


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
