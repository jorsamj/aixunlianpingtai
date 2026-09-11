export const UI_STATE_STORAGE_KEY = 'mc_train_ui_state_v34';

function readExisting(storage, key) {
  try {
    const raw = storage?.getItem?.(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

export function persistUiState(state, {storage = globalThis.localStorage, key = UI_STATE_STORAGE_KEY, now = Date.now} = {}) {
  if (!storage?.setItem) return null;
  const current = readExisting(storage, key);
  const next = {
    ...current,
    page: String(state?.page || current.page || ''),
    projectId: String(state?.project?.id || current.projectId || ''),
    datasetId: String(state?.datasetId || current.datasetId || ''),
    imageFilter: String(state?.imageFilter || current.imageFilter || 'all'),
    ts: Number(now()),
  };
  try {
    storage.setItem(key, JSON.stringify(next));
    return next;
  } catch (_) {
    return null;
  }
}
