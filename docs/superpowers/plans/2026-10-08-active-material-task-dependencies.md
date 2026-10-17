# AUDIT-084 / AUDIT-168 Implementation Plan

1. Add bounded active-input and active-delete selection queries to the existing
   MaterialBatch owner.
2. Add a MaterialRepository admission revalidation method and a distinct
   MaterialBatch delete-claim field; make formal annotation/training
   compatibility reject the claim.
3. Serialize deletion publication with active task dependency validation.
4. Serialize explicit training publication with active deletion validation.
5. Serialize Agent RKNN INT8 conversion publication with active deletion and
   frozen Material identity validation, while keeping storage I/O outside the
   fence.
6. Claim each source material before provider deletion, then finish canonical
   index/annotation deletion without a cancellation gap; preserve claim and
   tombstone for lease recovery after an ambiguous delete.
7. Add deterministic concurrency and lifecycle regressions, run focused tests,
   syntax/import checks, and `git diff --check`.
8. Increment PATCH version, update audit/handoff documents, commit, push the
   long-lived branch, and verify all checks for the exact pushed HEAD.
