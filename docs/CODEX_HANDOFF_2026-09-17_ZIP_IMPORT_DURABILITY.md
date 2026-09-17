# ZIP Import Durability Closure — 2026-09-17

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Formal `VERSION.txt`: `42.24.0` (unchanged)

This handoff records the closure of the browser ZIP import durability/runtime issue reported in September 2026. It does not reopen previously CLOSED frontend/runtime work and does not merge `main`, create a tag, or create a release.

## 1. User-visible problems that were addressed

The reported failures were:

1. A ZIP import task became invisible after a browser refresh even though the backend task could still exist.
2. A second ZIP upload could appear stuck at “准备后台解析” when an earlier ZIP import for the same project was still occupying the serialized backend import owner.
3. Frontend state and backend durable state could diverge: the browser could lose task context even though the v19 backend persisted the import job.
4. During the runtime migration, the durable owner initially omitted the legacy completion notification even though the backend had already reached `done` and scoped refreshes had completed.

## 2. Runtime ownership after closure

The browser ZIP import runtime is owned by:

- `static/modules/zip-import-runtime.js`
- `static/zip-import-bootstrap.mjs`

The browser restores ZIP task truth from the backend v19 job list:

`GET /api/v19/projects/{project_id}/import/jobs`

The frontend does not use localStorage as the durable task source. Local storage is only used as a small start-intent compatibility fence so a refresh does not blindly repost a start request whose outcome is ambiguous.

Once the server has returned a ZIP job ID, a browser refresh can restore the task from persisted backend state. The runtime displays backend-reported progress directly instead of inventing a new aggregate percentage.

## 3. Same-project queue semantics

The backend ZIP import path is serialized per project. A later ZIP import can therefore be accepted by the server but remain in a selecting/waiting state until the earlier import advances or finishes.

The frontend now makes that state explicit:

- queue head selecting job: eligible for background start;
- later selecting job: “等待前序 ZIP 导入任务”;
- queue position/ahead count is derived from the server-visible active job order;
- a later ZIP is not presented as an unexplained “准备后台解析” stall.

This is intended to align frontend wording with actual backend ownership rather than simulate parallelism that does not exist.

## 4. Completion side effects

When a durable ZIP job reaches `done` outside bootstrap restoration, the canonical runtime performs the scoped completion chain once per job:

1. bind/open the existing ZIP import review result (`completeZipImportReview412`);
2. invalidate import-quality state;
3. refresh project labels through the scoped label path;
4. if the user is on the dataset page, refresh the material page through `reloadMaterialPage61` instead of broad application reload;
5. show `后台导入完成：N 张图片`.

The final completion notification fix is product commit:

`ddba9a0ba2fac394d2bb91bd4b72e56718f44f8d`

That commit changes only the missing completion notification in the durable completion owner; it does not change queue ordering, backend progress, refresh restoration, or dataset paging behavior.

## 5. Permanent verification

Permanent workflow:

`.github/workflows/zip-import-durable-runtime.yml`

It verifies:

- JavaScript syntax on Ubuntu and Windows;
- refresh/queue/server-progress contracts;
- durable v19 job persistence;
- bounded 10k-candidate hot job state;
- Real Chrome refresh recovery.

For product commit `ddba9a0ba2fac394d2bb91bd4b72e56718f44f8d`, ZIP Import Durable Runtime run `35164218612` passed all four jobs:

- `contract (ubuntu-24.04)` — success;
- `contract (windows-latest)` — success;
- `backend-persistence` — success;
- `real-chrome-refresh` — success.

The main Frontend Runtime Stabilization run `35164218618` also passed:

- frontend syntax/owner/unit guards — success;
- full Real Chrome runtime regression sequence — success.

Navigation Action Fencing run `35164218590` passed its unit/source guards and Real Chrome stale-mutation contract.

A temporary diagnostic workflow used while isolating the failing browser assertion was deleted after the permanent suites were green. Cleanup commit:

`947743478df7d42ffd5b7f1f5081fe0e54de3eec`

Do not restore the temporary ZIP diagnostic workflow as a permanent CI owner.

## 6. What is proven vs. not proven

Proven by automated acceptance:

- server-created ZIP jobs can be restored after browser refresh;
- the frontend exposes same-project serialized waiting instead of silently appearing stuck;
- backend progress remains the progress truth;
- completion uses scoped label/material refreshes without broad reload;
- the canonical completion owner preserves the import-review contract and completion notice;
- Windows and Linux-oriented contract paths remain compatible at the JavaScript/runtime level.

Not proven by this closure:

- resumable upload before the server returns a ZIP job ID. Refreshing or closing the browser while the raw HTTP upload itself is still in flight can interrupt that upload; true resumable upload would require a separate upload-session/chunk/resume protocol;
- genuine production wall-clock throughput for a real 10k-image ZIP on the A800 server. The bounded hot-state/scalability contracts are green, but no production speed percentage is claimed and the paused genuine-10k acceptance scope remains paused;
- multi-node/GPU scheduling work unrelated to ZIP import.

## 7. Current constraints remain unchanged

- do not merge `main`;
- do not modify formal `VERSION.txt` from `42.24.0` without explicit approval;
- do not tag or release;
- do not revive legacy browser-memory task ownership;
- do not replace backend progress with timer-derived fake progress;
- do not weaken existing regression tests to make CI pass.
