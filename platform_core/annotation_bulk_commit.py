"""Internal execution of one sealed formal annotation batch."""
import json
from functools import partial

from filelock import FileLock

from .annotation_bulk_intents import _candidate_digest, _digest, load_sealed_intent
from .annotation_candidates import CandidateStore
from .annotation_task_service import (
    _candidate_commit_digest, _canonical_review_scope, candidate_commit_summary, commit_candidate_decisions,
)
from .task_runtime import TaskKind, TaskStatus
from .task_runtime.payload_publications import EVIDENCE_REF

BATCH_SIZE = 100
_IDENTITY_KEYS = {"actor", "project_id", "task_id", "request_id"}


def _batch_count(manifest):
    return (len(manifest["images"]) + BATCH_SIZE - 1) // BATCH_SIZE


class FormalBulkEvidenceError(ValueError):
    """Persisted evidence cannot prove this execution's durable state yet."""


def _gt_digest(annotations, row):
    """Version zero is the repository's legacy/non-persisted GT view."""
    return annotations.record_digest(row) if int(row.get("version") or 0) == 0 else row.get("content_digest")


def audit_formal_bulk_execution(store, annotations, manifest, ref):
    """Prove how far the sealed manifest is durably committed.

    Only receipts plus the candidate journal prove a completed batch.  The
    returned ``state`` is one of ``complete``, ``pending`` (next batch never
    obtained GT), ``journal_pending`` (GT durable, journal lagging) or
    ``unproven`` (contradictory/foreign evidence).
    """
    total = _batch_count(manifest)
    expected_before = manifest["operation"]["review_revision"]
    completed = committed = 0
    for number in range(total):
        batch, frozen = _batch(manifest, ref, number)
        count = len(frozen)
        try:
            _, receipts, journal, after = _proof_state(store, annotations, batch, frozen)
        except ValueError as error:
            return {"state": "unproven", "batch": number, "completed": completed,
                    "committed": committed, "detail": str(error)}
        if receipts and not journal:
            return {"state": "journal_pending", "batch": number, "completed": completed,
                    "committed": committed, "detail": "GT 已提交，候选日志尚未完成"}
        if receipts and journal:
            events = store.bulk_formal_events(list(frozen))
            if ({event.get("revision_before") for event in events} != {expected_before}
                    or after != expected_before + count):
                return {"state": "unproven", "batch": number, "completed": completed,
                        "committed": committed, "detail": "批量正式入库候选修订链不连续"}
            expected_before = after + 1
            completed += 1
            committed += count
            continue
        events = store.bulk_formal_events(list(frozen))
        current = annotations.get_many(list(frozen))
        changed = sum(
            1 for image_id, row in frozen.items()
            if current[image_id]["version"] != row["gt_version"]
            or _gt_digest(annotations, current[image_id]) != row["gt_content_digest"]
        )
        adopted = ([{"batch_number": number, "image_count": count,
                     "gt_changed_images": changed}] if events else [])
        return {"state": "pending", "batch": number, "completed": completed,
                "committed": committed, "candidate_only": adopted,
                "detail": ("该批次候选已采用，正式 GT 已发生外部变化" if events and changed
                           else "该批次候选已采用，尚未写入正式 GT" if events
                           else "该批次正式 GT 已发生外部变化" if changed
                           else "该批次尚未写入正式 GT")}
    return {"state": "complete", "batch": total, "completed": completed, "committed": committed}


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
                    or (journal and journal[image_id] != candidate_commit_summary(proof))):
                raise ValueError(f"bulk formal GT evidence conflict: {image_id}")
            # The receipt proves the write THIS operation performed. A later
            # lawful edit may advance the current GT beyond that version; the
            # historical fact must survive it. A rollback below the proven
            # version, or a different payload at the same version, is a conflict.
            current_version = int(current_gt.get("version") or 0)
            if current_version < proof["version"]:
                raise ValueError(f"bulk formal GT rolled back below proven version: {image_id}")
            if (current_version == proof["version"]
                    and proof["content_digest"] != current_gt.get("content_digest")):
                raise ValueError(f"bulk formal GT digest changed at proven version: {image_id}")
    return candidates, receipts, journal, after


def execute_worker_bulk_formal_batch(context, artifacts, identity, operation_id, manifest_ref, batch_number,
                                     *, binding_ref=None, sealed=None):
    """Bind the internal GT kernel to a dedicated Worker execution."""
    if context.task.payload_ref != (binding_ref or manifest_ref):
        raise PermissionError("formal bulk manifest does not belong to this execution task")

    def authorize(_batch):
        context.assert_current_execution()
        cancelled, _ = context.repository.formal_bulk_cancel_state(context.lease, context.execution_generation)
        return not cancelled

    anchor = {"identity": dict(identity), "operation_id": operation_id,
              "manifest_ref": manifest_ref, "batch_number": batch_number}
    if binding_ref is not None:
        anchor["binding_ref"] = binding_ref
    return execute_bulk_formal_batch(
        artifacts, identity, operation_id, manifest_ref, batch_number, authorize=authorize, sealed=sealed,
        formal_write_barrier=partial(context.repository.formal_bulk_gt_write, context.lease,
                                     context.execution_generation, anchor),
    )


def reconcile_worker_bulk_formal_cancel(context, artifacts):
    """Recover every admitted GT batch; never call the GT writer."""
    from app import _v50_annotation_repository, label_governance_fence, material_annotation_lifecycle_fence, project_dir
    from .task_runtime.models import utc_now

    context.assert_current_execution()
    repository = context.repository
    execution = (context.lease, context.execution_generation)
    cancelled, anchor = repository.formal_bulk_cancel_state(*execution)
    if not cancelled:
        return False
    descriptor = json.loads(anchor) if anchor is not None else None
    manifest, ref, identity, binding_ref = _cancelled_intent(context, artifacts, descriptor)
    total = _batch_count(manifest)
    last = -1
    if descriptor is not None:
        last = descriptor["batch_number"]
        batch_identity, _ = _batch(manifest, ref, last)
        if (descriptor["identity"] != {key: batch_identity[key] for key in _IDENTITY_KEYS}
                or batch_identity["operation_id"] != descriptor["operation_id"]
                or batch_identity["batch_number"] != last):
            raise ValueError("formal bulk reconciliation batch identity mismatch")
    path = project_dir(identity["project_id"])
    with FileLock(str(artifacts.artifact_path(identity["task_id"], "review.lock")), timeout=30), \
            label_governance_fence(path), material_annotation_lifecycle_fence(path):
        repository.formal_bulk_cancel_state(*execution)
        store = CandidateStore(artifacts, task_id=identity["task_id"])
        annotations = _v50_annotation_repository(identity["project_id"])
        completed, committed, first_uncommitted = _verified_prefix(
            store, annotations, manifest, ref, total)
        if last >= total:
            raise ValueError("formal bulk active batch is out of range")
        if last >= 0 and last < completed - 1:
            raise ValueError("formal bulk active batch precedes verified batches")
        # F1's active_batch only records the last batch admitted to the GT
        # barrier. A batch that was admitted there but never obtained a receipt
        # is uncommitted too, so the scan must start at the verified prefix,
        # not at active_batch + 1.
        uncommitted = _uncommitted_batches(
            store, annotations, manifest, ref, first_uncommitted, total)
        adopted = [item for item in uncommitted if item["adopted"]]
        evidence = {
            "state": "cancelled",
            "binding_ref": binding_ref,
            "operation_id": manifest["operation"]["operation_id"],
            "manifest_ref": ref,
            "manifest_digest": EVIDENCE_REF.fullmatch(ref)["digest"],
            "total_images": len(manifest["images"]),
            "batch_size": BATCH_SIZE,
            "batch_count": total,
            "completed_batches": completed,
            "committed_images": committed,
            "committed_images_proven": True,
            "current_batch": last if last >= 0 else None,
            "first_uncommitted_batch": first_uncommitted,
            "candidate_only_batches": [
                {"batch_number": item["batch_number"], "image_count": item["image_count"],
                 "batch_operation_id": item["batch_operation_id"],
                 "gt_changed_images": item["gt_changed_images"]}
                for item in adopted
            ],
            "candidate_only_uncommitted_images": sum(item["image_count"] for item in adopted),
            "candidate_only_gt_changed_images": sum(item["gt_changed_images"] for item in adopted),
            "uncommitted_gt_changed_images": sum(item["gt_changed_images"] for item in uncommitted),
            "finished_at": utc_now(),
        }
        repository._finish_reconciled_formal_bulk_cancel(*execution, anchor, evidence)
    return True


def _cancelled_intent(context, artifacts, descriptor):
    """Resolve the sealed intent for either the bound or the F1 legacy task."""
    payload_ref = context.task.payload_ref
    if descriptor is not None and payload_ref == descriptor.get("manifest_ref"):
        identity = descriptor["identity"]
        manifest, ref = load_sealed_intent(artifacts, identity)
        if (ref != descriptor["manifest_ref"] or ref != payload_ref
                or manifest["operation"]["operation_id"] != descriptor["operation_id"]):
            raise ValueError("formal bulk reconciliation identity mismatch")
        return manifest, ref, identity, None

    from .annotation_bulk_execution import assert_binding_matches_manifest, binding_identity, load_binding

    binding = load_binding(artifacts, context.task.task_id, context.task.project_id, payload_ref)
    identity = binding_identity(binding)
    manifest, ref = load_sealed_intent(artifacts, identity)
    assert_binding_matches_manifest(binding, manifest, ref)
    if descriptor is not None and descriptor.get("binding_ref") not in (None, payload_ref):
        raise ValueError("formal bulk reconciliation binding mismatch")
    return manifest, ref, identity, payload_ref


def _verified_prefix(store, annotations, manifest, ref, total):
    """Return ``(completed_batches, committed_images, first_uncommitted_batch)``.

    Completion is proven only by per-batch GT receipts plus the matching
    candidate journal. A batch that was admitted into the GT barrier but has no
    receipt is **not** completed and must stay visible as uncommitted. This
    function never calls the GT writer.
    """
    completed = committed = 0
    for number in range(total):
        batch, frozen = _batch(manifest, ref, number)
        _, receipts, journal, after = _proof_state(store, annotations, batch, frozen)
        if not receipts:
            return completed, committed, number
        if not journal:
            if store.review_revision() != after:
                raise ValueError("bulk formal revision changed before journal recovery")
            annotations.repair_candidate_commit_projections(receipts.values())
            store.record_commit_summaries(
                [candidate_commit_summary(receipts[key]) for key in frozen],
            )
            _, _, journal, _ = _proof_state(store, annotations, batch, frozen)
        if not journal or len(journal) != len(frozen):
            raise ValueError("bulk formal cancellation requires a verified journal")
        completed += 1
        committed += len(journal)
    return completed, committed, total


def _uncommitted_batches(store, annotations, manifest, ref, start, total):
    """Describe every batch after the verified prefix; never writes GT.

    ``adopted`` distinguishes "candidates were adopted but GT was never
    committed" from "the batch was never started". ``gt_changed_images`` counts
    lawful external GT edits and is never attributed to this operation.
    """
    found = []
    for number in range(start, total):
        batch, frozen = _batch(manifest, ref, number)
        image_ids = list(frozen)
        receipts = annotations.candidate_commit_receipts(store.task_id, batch["batch_operation_id"], image_ids)
        if receipts:
            raise ValueError("bulk formal batch after the verified prefix already has GT receipts")
        events = store.bulk_formal_events(image_ids)
        adopted = bool(events)
        if adopted and (len(events) != len(image_ids) or any(
                event.get("batch_operation_id") != batch["batch_operation_id"] for event in events)):
            raise ValueError("bulk formal candidate-only evidence conflict")
        current = annotations.get_many(image_ids)
        changed = sum(
            1 for image_id, row in frozen.items()
            if current[image_id]["version"] != row["gt_version"]
            or _gt_digest(annotations, current[image_id]) != row["gt_content_digest"]
        )
        found.append({"batch_number": number, "image_count": len(image_ids),
                      "batch_operation_id": batch["batch_operation_id"],
                      "adopted": adopted, "gt_changed_images": changed})
    return found


def execute_bulk_formal_batch(artifacts, identity, operation_id, manifest_ref, batch_number, *,
                              authorize, formal_write_barrier=None, sealed=None):
    """Execute or recover an exact batch; only trusted internal callers may authorize."""
    from app import (
        _annotation_label_catalog, _require_annotation_review_task, _v50_annotation_repository,
        get_project, label_governance_fence, material_annotation_lifecycle_fence, material_store, project_dir,
    )

    if (set(identity) != _IDENTITY_KEYS or not all(isinstance(value, str) and value for value in identity.values())
            or type(batch_number) is not int or batch_number < 0):
        raise ValueError("invalid bulk formal execution identity")
    manifest, ref = sealed if sealed is not None else load_sealed_intent(artifacts, identity)
    if (ref != manifest_ref or operation_id != manifest["operation"]["operation_id"]
            or manifest["operation"]["identity"] != identity):
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
                # Entry was authorized and the complete GT batch is durable.
                # Its projections and journal must catch up even after cancellation.
                annotations.repair_candidate_commit_projections(receipts.values())
                store.record_commit_summaries(
                    [candidate_commit_summary(receipts[image_id]) for image_id in frozen],
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
                before_formal_write=before_write, formal_write_barrier=formal_write_barrier,
            )
        _, _, journal, after = _proof_state(store, annotations, batch, frozen)
        if not journal:
            raise ValueError("bulk formal completion requires a verified journal")
        return {"status": "completed", "batch_operation_id": batch["batch_operation_id"],
                "completed_image_ids": list(frozen), "candidate_revision_after": after,
                "journal_revision": after + 1}
