# P0 Product Usability Owner Closure

## Scope

Keep `VERSION.txt` at `42.24.0` and close four usability defects through the current owners only. No new router, polling system, task truth, or annotation truth is introduced.

## Design

1. `TrainingSubmitRuntime` accepts success only when the durable create response contains `ok=true`, a non-empty `task.task_id`, `kind/task_type=TRAINING`, an allowed active `status`, and the returned identity matches the requested task ID. `TaskRepository.create()` remains the durable commit boundary. The verified response is merged immediately into `TrainingTaskRuntime`; no confirmation polling is added.
2. `NavigationStability` gains a page-owner registry. Navigation commits `state.page` and invokes exactly one registered owner. `ServiceNodeRuntime` registers its renderer and paints cache or a service-node skeleton synchronously. Title mutation is no longer a route signal, and unknown pages render a neutral unknown-page shell instead of another business page.
3. `TrainingCreateHydrationRuntime` paints a modal shell synchronously, then runs required hydration in parallel and reuses existing caches. A monotonically scoped open token prevents a closed, replaced, or older dialog request from writing the current dialog.
4. The training-material page API batch-reads annotations for only the returned page IDs through `AnnotationRepository.get_many()`. Each row includes source dimensions, `annotation_state`, and formal boxes. The picker uses `object-fit: contain` and an SVG whose `viewBox` equals the source coordinate system.

## Verification

Use only focused unit/API tests and four browser smoke paths: navigation ownership, immediate training shell, annotation overlay, and durable task visibility across refresh. Do not run the full suite or wait for all Actions.
