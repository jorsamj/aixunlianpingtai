# 42.24.503 — Cross-algorithm model ancestry and formal Test scoring fence

Date: 2026-11-02. Development branch: `feature/external-algorithm-publishing`.
Environment: isolated checkout and temporary test data; **NOT PRODUCTION VERIFIED**.

## Implemented

1. The prepared training base resolves to one concrete local weight. Its SHA-256 is
   compared with server-archived, artifact-verified model versions **within the
   same project**. A copied checkpoint can therefore inherit the correct prior
   algorithms' Train/Val and observed Test claims. Architecture/model name alone
   is insufficient; it does not create a cross-algorithm edge.
2. A verified original Task and exact frozen Snapshot must be recoverable for
   each ancestor. A missing/cyclic/overlong parent chain fails closed. The
   authoritative original algorithm ID is retained when replaying evidence,
   rather than rewriting another algorithm's usage scope. Transitive ancestors
   are stored in the version's `training_lineage.model_ancestry` and re-resolved
   when used as another algorithm's base.
3. The selected base-weight digest is checked again against the training input
   freeze. Local blind scoring, final checkpoint validation, local version
   finalization, remote result commit, and legacy version archiving reject an
   exposed Test, incomplete unverified history, missing original admission or
   an unverified frozen benchmark before accepting formal scores. Normal
   single-image scenario inference has no GT scoring and is not blocked.
4. The existing version trust report remains read-only. It now calculates
   separate historical Train/Val exposure and unknown-coverage counts, and
   the model evaluation UI displays the result and reason details. Ancestor
   Task IDs from persisted lineage are included in retrospective checks.

## Historical maintenance

`tools/rebuild_training_material_usage.py` already supports a bounded
`--batch-size` (1–500), default dry-run, explicit `--apply`, owner Task/Snapshot
matching, and interruption-safe cursor resume. It deliberately **never** marks
history coverage complete merely because a batch was scanned or because a Task
ended successfully; unknown originals remain unknown. No historical production
batch was run in this change.

## Verification scope

- Python unit tests cover copied checkpoint versus same-architecture unrelated
  weight, A → B → C transitive inheritance, original Test protection, historical
  coverage, frozen Task payload binding, and missing ancestor handling.
- Local training/remote preparation integration and frontend trust-contract
  regressions are included in the existing test suites.
- Full deployment and genuine model evaluation on production data remain
  separate acceptance activities. Do not deploy or mutate production GT,
  materials, models, tasks, workers, object storage or GPU resources as part of
  this implementation.
