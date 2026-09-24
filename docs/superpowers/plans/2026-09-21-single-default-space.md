# Single Default Space Implementation Plan

**Goal:** Keep the existing `f1fb1e6fa373` project as the only runtime space, prevent accidental creation or selection of another space, and leave unrelated UI state intact.

1. Add focused backend tests proving an existing project is returned as the sole space and a second runtime create is rejected.
2. Add focused frontend tests proving saved `projectId` is ignored, project loading failures do not trigger `POST /api/projects`, and downstream dataset/material/job requests use the server-selected project.
3. Make the project list/bootstrap owners choose the single existing project, ignore `preferred_project_id`, and fail closed on duplicate creation without changing the legacy physical schema.
4. Remove frontend automatic project creation and project selection from persisted UI state while preserving page, dataset, and filter state.
5. Verify `182cac36f20d` is empty in the actual `/data/platform-data` owner before deleting only that exact record/directory; never alter `f1fb1e6fa373`.
6. Run only the new project API/frontend tests plus syntax checks, then commit and fast-forward push the feature branch.
