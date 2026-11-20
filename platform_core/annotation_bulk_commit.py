"""Internal execution of one sealed formal annotation batch."""
from filelock import FileLock

from .annotation_bulk_intents import _candidate_digest, _digest, load_sealed_intent
from .annotation_candidates import CandidateStore
from .annotation_task_service import (
    _candidate_commit_digest, _canonical_review_scope, candidate_commit_summary, commit_candidate_decisions,
)
from .task_runtime import TaskKind, TaskStatus

BATCH_SIZE = 100
_IDENTITY_KEYS = {"actor", "project_id", "task_id", "request_id"}


def _batch(manifest, ref, number):
    rows = manifest["images"][number * BATCH_SIZE:(number + 1) * BATCH_SIZE]
    if not rows:
        raise ValueError("bulk formal batch number is out of range")
    ids = [row["image_id"] for row in rows]
    operation = manifest["operation"]
    manifest_digest = ref.rsplit("sha256-", 1)[1].removesuffix(".json")
    identity = {
        **operation["identity"], "operation_id": operation["operation_id"],
        "manifest_digest": manifest_digest, "batch_number": number,
        "batch_operation_id": _digest(["bulk-formal-batch:v1", operation["operation_id"],
                                       manifest_digest, number, ids]),
    }
    return identity, {row["image_id"]: row for row in rows}


def _proof_state(store, annotations, identity, frozen):
    ids = list(frozen)
    events = store.bulk_formal_events(ids)
    candidates = store.get_many(ids)
    gt = annotations.get_many(ids)
    journal = store.get_commit_summaries(ids)
    receipts = annotations.candidate_commit_receipts(store.task_id, identity["batch_operation_id"], ids)
    if set(candidates) != set(ids) or (receipts and set(receipts) != set(ids)):
        raise ValueError("bulk formal evidence incomplete")
    if bool(journal) and (not receipts or set(journal) != set(ids)):
        raise ValueError("bulk formal journal evidence incomplete")
    if not receipts and annotations.candidate_committed_ids(store.task_id, ids):
        raise ValueError("bulk formal GT belongs to another operation")
    if not events:
        if receipts or journal:
            raise ValueError("formal evidence has no candidate operation ownership")
        return candidates, receipts, journal, None
    if len(events) != len(ids) or {event.get("image_id") for event in events} != set(ids):
        raise ValueError("bulk formal candidate ownership incomplete")
    before, after = events[0]["revision_before"], events[0]["revision_after"]
    if type(before) is not int or before < 0 or after != before + len(ids):
        raise ValueError("bulk formal candidate revision evidence invalid")
    for event in events:
        image_id = event["image_id"]
        candidate = candidates[image_id]
        baseline = frozen[image_id]
        if (any(event.get(key) != value for key, value in identity.items())
                or event["revision_before"] != before or event["revision_after"] != after
                or event["candidate_before"] != baseline["candidate_digest"]
                or event["candidate_after"] != _candidate_digest({**candidate, "gt_committed": False})
                or event["commit_digest"] != _candidate_commit_digest(candidate)):
            raise ValueError(f"bulk formal candidate operation conflict: {image_id}")
        if receipts:
            proof, current_gt = receipts[image_id], gt[image_id]
            if (proof["project_id"] != identity["project_id"] or proof["task_id"] != store.task_id
                    or proof["operation_id"] != identity["batch_operation_id"] or proof["image_id"] != image_id
                    or proof["expected_version"] != baseline["gt_version"]
                    or proof["source_sha256"] != baseline["source_content_sha256"]
                    or proof["candidate_digest"] != event["commit_digest"]
                    or proof["summary"]["image_id"] != image_id
                    or proof["summary"]["gt_write_performed"] is not True
                    or type(proof["version"]) is not int or proof["version"] != baseline["gt_version"] + 1
                    or proof["version"] != current_gt["version"]
                    or proof["content_digest"] != current_gt.get("content_digest")
                    or (journal and journal[image_id] != candidate_commit_summary(proof))):
                raise ValueError(f"bulk formal GT evidence conflict: {image_id}")
    return candidates, receipts, journal, after


def execute_bulk_formal_batch(artifacts, identity, operation_id, manifest_ref, batch_number, *, authorize):
    """Execute or recover an exact batch; only trusted internal callers may authorize."""
    from app import (
        _annotation_label_catalog, _require_annotation_review_task, _v50_annotation_repository,
        get_project, label_governance_fence, material_annotation_lifecycle_fence, material_store, project_dir,
    )

    if (set(identity) != _IDENTITY_KEYS or not all(isinstance(value, str) and value for value in identity.values())
            or type(batch_number) is not int or batch_number < 0):
        raise ValueError("invalid bulk formal execution identity")
    manifest, ref = load_sealed_intent(artifacts, identity)
    if ref != manifest_ref or operation_id != manifest["operation"]["operation_id"]:
        raise ValueError("bulk formal manifest reference mismatch")
    batch, frozen = _batch(manifest, ref, batch_number)

    def guard():
        if authorize(dict(batch)) is not True:
            raise PermissionError("bulk formal batch has no execution authority")

    guard()
    project_id, task_id = identity["project_id"], identity["task_id"]
    path = project_dir(project_id)
    store = CandidateStore(artifacts, task_id=task_id)
    annotations = _v50_annotation_repository(project_id)
    materials = material_store(project_id)
    contract = manifest["review_contract"]
    with FileLock(str(artifacts.artifact_path(task_id, "review.lock")), timeout=30), \
            label_governance_fence(path), material_annotation_lifecycle_fence(path):
        guard()
        task = _require_annotation_review_task(project_id, task_id)
        config = artifacts.read_json(task_id, task.payload_ref)
        if isinstance(config, dict) and task.kind is TaskKind.MATERIAL_BATCH:
            config = config.get("options")
        labels = {row["code"]: row["class_id"] for row in _annotation_label_catalog(get_project(project_id))}
        original = artifacts.read_json(task_id, "candidates/manifest.json", default={})
        if (task.status is not TaskStatus.AWAITING_CONFIRMATION or not isinstance(config, dict)
                or contract["policy"] != "task_uniform_legacy"
                or config.get("review_scope_policy", "task_uniform_legacy") != contract["policy"]
                or bool(config.get("overwrite")) != contract["overwrite"] or labels != contract["label_class_ids"]
                or _canonical_review_scope(config.get("labels") or original.get("labels") or [], {}, labels)
                != contract["labels"]):
            raise ValueError("bulk formal task or label contract changed")
        sources = {image_id: row["source_content_sha256"] for image_id, row in frozen.items()}
        admitted = materials.assert_formal_annotation_admission(sources)
        candidates, receipts, journal, after = _proof_state(store, annotations, batch, frozen)

        # A prior fully sealed batch is the only source of a later batch's
        # starting revision. The journal commit contributes exactly one revision.
        expected = manifest["operation"]["review_revision"]
        if batch_number:
            previous, previous_frozen = _batch(manifest, ref, batch_number - 1)
            _, _, previous_journal, previous_after = _proof_state(store, annotations, previous, previous_frozen)
            if not previous_journal:
                raise ValueError("previous bulk formal batch is incomplete")
            expected = previous_after + 1

        if after is not None and after - len(frozen) != expected:
            raise ValueError("bulk formal candidate revision chain changed")
        if receipts:
            if not journal:
                if store.review_revision() != after:
                    raise ValueError("bulk formal revision changed before journal recovery")
                guard()
                annotations.repair_candidate_commit_projections(receipts.values())
                store.record_commit_summaries(
                    [candidate_commit_summary(receipts[image_id]) for image_id in frozen], commit_guard=guard,
                )
        else:
            if any(int(admitted[image_id].get("annotation_version") or 0) > row["gt_version"]
                   for image_id, row in frozen.items()):
                raise ValueError("bulk formal material projection is ahead of frozen GT")
            if store.review_revision() != (after if after is not None else expected):
                raise ValueError("bulk formal candidate revision changed")
            for image_id, item in candidates.items():
                if (item.get("source_content_sha256") != sources[image_id]
                        or (after is None and _candidate_digest(item) != frozen[image_id]["candidate_digest"])
                        or item.get("draft_revision", 0) != frozen[image_id]["draft_revision"]):
                    raise ValueError(f"bulk formal candidate baseline changed: {image_id}")
            projected = ({image_id: store.preview_bulk_formal_candidate(item, labels)
                          for image_id, item in candidates.items()} if after is None else candidates)

            def prepare():
                store.prepare_bulk_formal_batch(batch, frozen, projected, labels, expected,
                                                _candidate_digest, _candidate_commit_digest, guard)

            def before_write():
                guard()
                current, _, _, revision = _proof_state(store, annotations, batch, frozen)
                if revision is None or store.review_revision() != revision or set(current) != set(frozen):
                    raise ValueError("bulk formal candidate preparation was superseded")

            commit_candidate_decisions(
                project_id, task_id, store, overwrite=contract["overwrite"], review_scope=contract["labels"],
                frozen_annotation_versions={image_id: row["gt_version"] for image_id, row in frozen.items()},
                frozen_annotation_digests={image_id: row["gt_content_digest"] for image_id, row in frozen.items()},
                selected_image_ids=frozen, operation_id=batch["batch_operation_id"],
                selected_candidates=list(projected.values()), persist_selected=prepare if after is None else None,
                before_formal_write=before_write, before_formal_journal=guard,
            )
        _, _, journal, after = _proof_state(store, annotations, batch, frozen)
        if not journal:
            raise ValueError("bulk formal completion requires a verified journal")
        return {"status": "completed", "batch_operation_id": batch["batch_operation_id"],
                "completed_image_ids": list(frozen), "candidate_revision_after": after,
                "journal_revision": after + 1}
