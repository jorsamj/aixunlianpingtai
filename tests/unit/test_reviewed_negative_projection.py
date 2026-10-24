from copy import deepcopy
import pytest
from PIL import Image
from platform_core import training_tasks as base
from platform_core.training_label_tasks import project_training_rows, training_material_role

CONTRACT = {"effective_label_codes": ["vest"], "training_projection_policy": "reviewed_negative_original_v3_preserve_selected"}
def row(scope=("person", "vest")):
    return {"id": "n", "annotation_state": "annotated", "annotation_scope": list(scope), "boxes": [{"label": "person", "x1": 1, "y1": 1, "x2": 15, "y2": 15}]}

def test_reviewed_negative_retains_pixels_and_gt(tmp_path):
    original = row(); saved = deepcopy(original)
    projected = project_training_rows([original], CONTRACT)[0]
    assert training_material_role(original, CONTRACT)["role"] == "confirmed_negative"
    path = tmp_path / "n.png"; Image.new("RGB", (20,20), "blue").save(path)
    before = path.read_bytes()
    proof = base._apply_training_projection(path, projected, "train", {})
    assert path.read_bytes() == before
    assert proof["redacted_object_count"] == 0
    assert projected["boxes"] == []
    assert original == saved

def test_unreviewed_person_pending():
    assert training_material_role(row(("person",)), CONTRACT)["role"] == "pending_review"
    with pytest.raises(ValueError, match="审核范围"):
        project_training_rows([row(("person",))], CONTRACT)

def test_mixed_is_positive_and_legacy_policy_unchanged():
    mixed = row(); mixed["boxes"].append({"label":"vest", "x1":3,"y1":3,"x2":8,"y2":8})
    assert training_material_role(mixed, CONTRACT)["role"] == "positive"
    assert project_training_rows([mixed], CONTRACT)[0]["boxes"][0]["label"] == "vest"
    assert project_training_rows([row()], {"effective_label_codes":["vest"]})[0]["training_projection_policy"] == base.TRAINING_PROJECTION_POLICY

def test_invalid_selected_box_cannot_be_positive():
    bad = row(); bad["boxes"].append({"label":"vest", "x1":4,"y1":4,"x2":2,"y2":2})
    assert training_material_role(bad, CONTRACT)["role"] == "pending_review"


def test_v3_mixed_preserves_selected_pixels(tmp_path):
    mixed = row(); mixed["boxes"].append({"label":"vest", "x1":3,"y1":3,"x2":8,"y2":8})
    projected = project_training_rows([mixed], CONTRACT)[0]
    path = tmp_path / "mixed.png"
    image = Image.new("RGB", (20,20), "white")
    for x in range(3,8):
        for y in range(3,8):
            image.putpixel((x,y), (255,0,0))
    image.save(path)
    identity = base._apply_training_projection(path, projected, "train", {})
    assert Image.open(path).getpixel((5,5)) == (255,0,0)
    assert identity["redacted_object_count"] == 1


def test_incoming_projection_marker_cannot_bypass_review():
    candidate = row(("person",))
    candidate.update(training_projection_policy=CONTRACT["training_projection_policy"],
                     training_projection_digest="a"*64, negative_origin="reviewed_task_negative")
    with pytest.raises(ValueError, match="审核范围"):
        project_training_rows([candidate], CONTRACT)


def test_projection_marker_is_recomputed_from_contract():
    candidate = row(); candidate["training_projection_policy"] = "forged"
    candidate["training_projection_digest"] = "a"*64
    projected = project_training_rows([candidate], CONTRACT)[0]
    assert projected["training_projection_policy"] == CONTRACT["training_projection_policy"]
    assert projected["training_projection_digest"] != "a"*64


def test_reviewed_person_generates_empty_vest_yolo_and_original_image(tmp_path):
    import hashlib
    original = row(); source = tmp_path / "source.png"
    Image.new("RGB", (20,20), "blue").save(source)
    original.update(filename=source.name, stored_name=source.name, width=20, height=20,
                    content_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    projected = project_training_rows([original], CONTRACT)[0]
    snapshot = {"schema_version":3, "snapshot_id":"negative", "ids":{"train":["n"],"validation":[],"test":[]},
                "label_schema":[{"code":"vest","class_id":0}], "images":[{"image_id":"n","role":"train",
                "content_sha256":original["content_sha256"],"annotation_state":"confirmed_empty","annotation_scope":["vest"]}]}
    bundle = base.materialize_portable_dataset(tmp_path / "task", snapshot, [projected], lambda _: source, safety_reserve_bytes=0)
    assert (bundle / "dataset/labels/train/n.txt").read_text() == ""
    assert (bundle / "dataset/images/train/n.png").read_bytes() == source.read_bytes()
    assert original["boxes"][0]["label"] == "person"


def test_first_vest_training_requires_real_vest_and_freezes_v3(tmp_path):
    import json
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.training_label_tasks import resolve_training_label_contract
    project = tmp_path / "projects/p"; project.mkdir(parents=True)
    (project / "meta.json").write_text(json.dumps({"labels":["vest","person"]}))
    repo = AnnotationRepository(project)
    repo.upsert("person", row()["boxes"], annotation_state="annotated", annotation_scope=["person","vest"])
    payload = {"model":"yolo11n.pt", "train_image_ids":["person"], "train_labels":["vest"]}
    with pytest.raises(ValueError, match="缺少 vest 正样本"):
        resolve_training_label_contract(tmp_path, project, payload, {"id":"a","versions":[]})
    repo.upsert("vest", [{"label":"vest","x1":1,"y1":1,"x2":8,"y2":8}], annotation_state="annotated")
    payload["train_image_ids"].append("vest")
    contract = resolve_training_label_contract(tmp_path, project, payload, {"id":"a","versions":[]})
    assert contract["effective_label_codes"] == ["vest"]
    assert contract["training_projection_policy"] == CONTRACT["training_projection_policy"]


def test_picker_preview_resolves_explicit_target_without_positive_selection(tmp_path):
    import json
    from platform_core.training_label_tasks import resolve_training_label_contract
    project = tmp_path / "projects/p"; project.mkdir(parents=True)
    (project / "meta.json").write_text(json.dumps({"labels":["vest","person"]}))
    payload = {"model":"yolo11n.pt", "train_labels":["vest"]}
    algorithm = {"id":"a","versions":[]}
    contract = resolve_training_label_contract(tmp_path, project, payload, algorithm, require_positive_evidence=False)
    assert contract["effective_label_codes"] == ["vest"]
    assert training_material_role(row(("person",)), contract)["role"] == "pending_review"
    with pytest.raises(ValueError, match="缺少 vest 正样本"):
        resolve_training_label_contract(tmp_path, project, payload, algorithm)
    payload["require_positive_evidence"] = False
    with pytest.raises(ValueError, match="缺少 vest 正样本"):
        resolve_training_label_contract(tmp_path, project, payload, algorithm)


@pytest.mark.parametrize("flags", [
    {"source_available":False}, {"annotation_needs_review":True}, {"needs_review":True},
    {"external_annotation_needs_review":True},
    {"annotation_source_content_sha256":"a"*64,"content_sha256":"b"*64},
])
def test_stale_or_unavailable_material_is_pending(flags):
    candidate = row(); candidate.update(flags)
    assert training_material_role(candidate, CONTRACT)["role"] == "pending_review"


def test_v3_positive_without_exclusions_is_not_reencoded(tmp_path):
 candidate=row();candidate['boxes']=[{'label':'vest','x1':1,'y1':1,'x2':8,'y2':8}]
 projected=project_training_rows([candidate],CONTRACT)[0]
 path=tmp_path/'positive.png';Image.new('RGB',(20,20),'red').save(path)
 before=path.read_bytes();identity=base._apply_training_projection(path,projected,'train',{})
 assert path.read_bytes()==before and identity['redacted_object_count']==0
