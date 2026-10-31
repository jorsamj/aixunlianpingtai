# Storage Source active-task lifecycle implementation plan

1. Add a reentrant cross-process coordination fence to the existing Storage
   Source repository module; do not add a state table or dependency owner.
2. Derive active Source references from canonical task statuses and bounded
   task/material artifacts.
3. Fence destructive PATCH, preserve name-only edits, and make Secret pointer
   publication recoverable with versioned Secret references.
4. Fence final publication/retry paths for Import/Rescan, MaterialBatch,
   annotation, training preparation, and model conversion; keep external I/O
   outside the fence and revalidate staged generations.
5. Add focused lifecycle, barrier, rollback, training-prepare, and RKNN tests;
   run relevant regressions, syntax/import, and diff checks.
6. Increment the patch version, update audit/handoff evidence, commit, push the
   long-lived branch, and inspect exact-HEAD Actions and check-runs.
