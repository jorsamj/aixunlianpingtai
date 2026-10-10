const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set([
  'ACCEPTED', 'QUEUED', 'WAITING_RESOURCE', 'PREPARING', 'RUNNING',
  'PAUSING', 'PAUSED', 'RESUMING', 'STOPPING', 'CANCEL_REQUESTED', 'RETRYING',
]);
const TERMINAL_STATUSES = new Set([
  'AWAITING_CONFIRMATION', 'PARTIAL_SUCCESS', 'SUCCEEDED', 'CANCELLED',
  'FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE',
]);

function statusOf(task = {}) {
  const raw = String(task.task_status || task.status || '').trim().toUpperCase();
  const aliases = {
    WAITING: 'WAITING_RESOURCE',
    PENDING: 'QUEUED',
    DONE: 'SUCCEEDED',
    FINISHED: 'SUCCEEDED',
    COMPLETED: 'SUCCEEDED',
    SUCCESS: 'SUCCEEDED',
    STOPPED: 'CANCELLED',
    CANCELED: 'CANCELLED',
  };
  return aliases[raw] || raw;
}

function activeIds(jobs) {
  return (Array.isArray(jobs) ? jobs : [])
    .filter(job => ACTIVE_STATUSES.has(statusOf(job)))
    .map(job => String(job?.task_id || job?.id || ''))
    .filter(Boolean);
}

function displayRevision(task = {}) {
  const value = Number(task?.training_display_progress?.revision ?? task?.display_revision);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function installTrainingProgressStream({
  getState,
  projectId,
  trainingTaskRuntime,
  pollRegistry,
  EventSourceImpl,
  documentImpl,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingProgressStreamInstalled) return window.TrainingProgressStreamRuntime;

  const state = () => getState?.() || {};
  const runtime = trainingTaskRuntime || window.TrainingTaskRuntime;
  const registry = pollRegistry || window.PollRegistryRuntime;
  const Source = EventSourceImpl || window.EventSource;
  const doc = documentImpl || (typeof document !== 'undefined' ? document : null);

  let source = null;
  let sourceProjectId = '';
  let connected = false;
  let durableIds = new Set();
  let reconcilePromise = null;
  let destroyed = false;

  function setRealtime(active) {
    registry?.setTrainingRealtimeActive?.(Boolean(active));
  }

  function render() {
    const visibility = window.TrainingTaskVisibilityRuntime;
    if (typeof visibility?.render === 'function') return visibility.render();
    return runtime?.patch?.() ?? false;
  }

  function reconcile(reason = 'stream-reconcile') {
    if (reconcilePromise || typeof runtime?.refresh !== 'function') return reconcilePromise;
    reconcilePromise = Promise.resolve(
      runtime.refresh({render: true, force: true, source: reason}),
    ).finally(() => {
      reconcilePromise = null;
    });
    return reconcilePromise;
  }

  function updateCoverage() {
    const active = activeIds(state().jobs);
    if (!active.length && !durableIds.size) {
      setRealtime(false);
      return false;
    }
    const covered = active.every(id => durableIds.has(id));
    setRealtime(covered);
    return covered;
  }

  function applyUpdate(update) {
    if (!update || String(update.project_id || '') !== String(projectId?.() || '')) return false;
    const taskId = String(update.task_id || '');
    if (!taskId) return false;
    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    const index = jobs.findIndex(job => String(job?.task_id || job?.id || '') === taskId);
    if (index < 0) {
      void reconcile('stream-discovery');
      return false;
    }

    const current = jobs[index] || {};
    const incomingRevision = displayRevision(update);
    const currentRevision = displayRevision(current);
    if (incomingRevision !== null && currentRevision !== null && incomingRevision < currentRevision) {
      return false;
    }
    if (incomingRevision === null || currentRevision === null) {
      const incomingTime = Date.parse(String(update.updated_at || ''));
      const currentTime = Date.parse(String(current.updated_at || ''));
      if (Number.isFinite(incomingTime) && Number.isFinite(currentTime) && incomingTime < currentTime) {
        return false;
      }
    }

    const display = update.training_display_progress && typeof update.training_display_progress === 'object'
      ? update.training_display_progress
      : null;
    const next = {
      ...current,
      task_status: String(update.status || current.task_status || '').trim().toUpperCase(),
      persisted_status: String(update.persisted_status || current.persisted_status || '').trim().toUpperCase(),
      phase: update.phase ?? current.phase,
      task_stage: update.phase ?? current.task_stage,
      progress_percent: display?.overall_progress ?? update.progress_percent ?? current.progress_percent,
      current_item: display?.message ?? update.current_item ?? current.current_item,
      current_epoch: display?.current_epoch ?? update.current_epoch ?? current.current_epoch,
      total_epochs: display?.total_epochs ?? update.total_epochs ?? current.total_epochs,
      current_batch: display?.current_batch ?? update.current_batch ?? current.current_batch,
      total_batches: display?.total_batches ?? update.total_batches ?? current.total_batches,
      elapsed_seconds: display?.elapsed_seconds ?? update.elapsed_seconds ?? current.elapsed_seconds,
      eta_seconds: display?.eta_seconds ?? update.eta_seconds ?? current.eta_seconds,
      phase_progress: display?.phase_progress ?? update.phase_progress ?? current.phase_progress,
      telemetry_source: display?.telemetry_source ?? update.telemetry_source ?? current.telemetry_source,
      training_progress: update.training_progress ?? current.training_progress,
      training_display_progress: display ?? current.training_display_progress,
      display_revision: display?.revision ?? update.display_revision ?? current.display_revision,
      task_worker_id: update.worker_id ?? current.task_worker_id,
      task_lease_expires_at: update.lease_expires_at ?? current.task_lease_expires_at,
      resource_wait_reason: update.resource_wait_reason ?? current.resource_wait_reason,
      updated_at: update.updated_at ?? current.updated_at,
      finished_at: update.finished_at ?? current.finished_at,
      error: update.error ?? current.error,
    };
    const copy = [...jobs];
    copy[index] = next;
    state().jobs = copy;
    render();
    window.TrainingRecoveryRuntime?.acceptLiveTask?.(next);

    const status = statusOf(next);
    if (TERMINAL_STATUSES.has(status)) void reconcile('stream-terminal');
    return true;
  }

  function disconnect({fallback = true} = {}) {
    const current = source;
    source = null;
    sourceProjectId = '';
    connected = false;
    durableIds = new Set();
    try { current?.close?.(); } catch (_) {}
    setRealtime(false);
    if (!fallback) registry?.clear?.('training-jobs');
  }

  function connect() {
    if (destroyed || typeof Source !== 'function') return false;
    const pid = String(projectId?.() || '');
    const page = String(state().page || '');
    if (!pid || page !== TRAINING_PAGE) return false;
    if (doc?.visibilityState === 'hidden') return false;
    if (source && sourceProjectId === pid) return true;

    disconnect({fallback: true});
    const next = new Source(`/api/v64/projects/${encodeURIComponent(pid)}/training-events`);
    source = next;
    sourceProjectId = pid;

    next.addEventListener?.('training.ready', event => {
      if (source !== next) return;
      try {
        const payload = JSON.parse(String(event?.data || '{}'));
        durableIds = new Set((payload.task_ids || []).map(String));
        updateCoverage();
      } catch (_) {
        setRealtime(false);
      }
    });
    next.addEventListener?.('training.task', event => {
      if (source !== next) return;
      try {
        applyUpdate(JSON.parse(String(event?.data || '{}')));
      } catch (_) {
        void reconcile('stream-invalid-event');
      }
    });
    next.onopen = () => {
      if (source !== next) return;
      connected = true;
    };
    next.onerror = () => {
      if (source !== next) return;
      connected = false;
      setRealtime(false);
    };
    return true;
  }

  function syncPage(page = state().page) {
    const target = String(page || '');
    if (target === TRAINING_PAGE && doc?.visibilityState !== 'hidden') return connect();
    disconnect({fallback: false});
    return false;
  }

  const onVisibilityChange = () => {
    if (doc?.visibilityState === 'hidden') {
      disconnect({fallback: false});
    } else if (String(state().page || '') === TRAINING_PAGE) {
      connect();
    }
  };
  doc?.addEventListener?.('visibilitychange', onVisibilityChange);

  const api = {
    build: 'training-progress-stream-422500',
    connect,
    disconnect,
    syncPage,
    applyUpdate,
    state() {
      return {
        connected,
        projectId: sourceProjectId,
        durableTaskIds: [...durableIds],
        reconciling: Boolean(reconcilePromise),
      };
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('visibilitychange', onVisibilityChange);
      disconnect({fallback: false});
      if (window.TrainingProgressStreamRuntime === api) window.TrainingProgressStreamRuntime = null;
      window.__trainingProgressStreamInstalled = false;
    },
  };

  window.TrainingProgressStreamRuntime = api;
  window.__trainingProgressStreamInstalled = true;
  return api;
}
