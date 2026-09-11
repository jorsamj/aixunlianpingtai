# v42.25 Negative Sample Contract

日期：2026-09-11  
状态：IMPLEMENTED ON `refactor/v42.25-runtime`; targeted Linux CI passed; NOT MERGED TO `main`; A800 real training not yet re-run after this change.

## 1. Formal annotation states

The training Ground Truth contract distinguishes:

- `unannotated`: unknown / not reviewed; never valid training Ground Truth.
- `annotated`: one or more formal bounding boxes.
- `confirmed_empty`: reviewer/import explicitly confirmed no target in scope; valid negative Ground Truth.

`boxes=[]` alone is not enough for training validity. Training split accepts an empty sample only when its state is `confirmed_empty`.

## 2. Negative sample scope

`annotation_scope` records which label codes were actually checked when an image was confirmed empty.

New empty confirmations without an explicit scope persist the active project label codes known at that time. A legacy `*` is retained only when no concrete label catalog is available.

This prevents a historical empty image from silently acquiring unrelated labels that are added to the project later.

## 3. Snapshot locking rule

YOLO detection cannot represent a partial negative with an empty `.txt`: an empty target means none of the classes in the locked training schema is present.

Therefore Snapshot v3 applies these rules:

```text
confirmed_empty + scope=["*"]
→ expand to the current locked label_schema

confirmed_empty + explicit scope
→ scope must cover every class in the locked label_schema
→ otherwise reject before training

annotated image
→ every box label must exist in locked label_schema
→ otherwise reject before dataset materialization
```

Snapshot persists the resolved scope and `negative_scope_counts` for audit.

## 4. YOLO materialization

A valid `confirmed_empty` sample is materialized as:

```text
images/<role>/<image>.jpg
labels/<role>/<image>.txt   # exists and is zero bytes
```

The empty label file is intentional Ground Truth, not a missing annotation.

`unannotated` images are rejected earlier and must never reach this stage.

## 5. Manual annotation UX

The annotation toolbar now exposes an explicit `确认无目标` action.

Behavior:

- if boxes exist, confirmation warns that boxes will be cleared;
- confirmed empty is displayed as `已确认负样本`;
- the UI preserves `confirmed_empty` as formally annotated even with `box_count=0`;
- normal zero-box save is blocked unless the sample is already confirmed empty or the user is executing the explicit negative-confirmation action;
- navigating away from a dirty zero-box annotation is blocked until the user explicitly confirms it as negative or restores boxes.

This prevents deleting the last box / autosave from silently creating negative Ground Truth.

## 6. Material/training UI semantics

`confirmed_empty` is projected with:

```text
annotated = true
box_count = 0
annotation_state = confirmed_empty
annotation_scope = [...]
processing_status = processed
```

Therefore the existing training material pool (`processed && annotated`) includes legitimate negative samples while still excluding `unannotated` material.

## 7. Import compatibility

YOLO import already distinguishes:

- empty label file → `confirmed_empty`
- missing label file → `unannotated`
- valid boxes → `annotated`

When older/import paths omit explicit scope, `AnnotationRepository` now freezes the concrete active project labels where available. Snapshot then intersects/validates that meaning against the locked training schema.

## 8. Validation evidence

Temporary GitHub Actions validation ran on Ubuntu 24.04 / Python 3.12.

Validated:

- `static/modules/negative-samples.js` syntax
- `static/modules/annotation.js` syntax
- `static/main.mjs` syntax
- `tests/unit/test_negative_sample_contract.py`
- `tests/unit/test_annotation_repository_scope.py`
- `tests/unit/test_training_splits.py`
- `tests/unit/test_training_components.py`
- `tests/unit/test_snapshots.py`
- `tests/unit/test_portable_dataset.py`

Result before the final UI guard commit:

```text
40 passed in 0.66s
```

The final UI guard commit triggered the same workflow again and completed successfully, including JS syntax and the same Python test set.

The temporary workflow was removed after validation; evidence remains in GitHub Actions history.

## 9. Non-regression rules

Future Codex/engineers must not reintroduce any of these behaviors:

- treating every `boxes=[]` image as training-ready;
- filtering `confirmed_empty` out merely because `box_count == 0`;
- converting legacy `*` into a timeless global meaning unrelated to the locked algorithm schema;
- using a partial negative scope as a full YOLO empty target;
- omitting the empty `.txt` file for a confirmed negative;
- changing `annotated` to false solely because a formal negative has zero boxes.

## 10. Remaining related work

Algorithm-level stable label schema is still a separate v42.25 item. Until that is completed, the training Snapshot continues to receive the label schema supplied by the current training pipeline. The negative-sample contract is designed to become stricter, not looser, once each algorithm owns an explicit stable schema.
