// Shared upload identity/session rules without legacy DOM ownership.
// The server receipts remain authoritative; this module only finds them again.
export const UPLOAD_SESSION_LEGACY_PREFIX = 'material-upload-session:';
export const UPLOAD_SESSION_V2_PREFIX = 'material-upload-session:v2:';
export const UPLOAD_INDEX_PREFIX = 'material-upload-index:v1:';
export const MAX_REQUEST_IDS = 5000;
export const MAX_INDEX_ROWS = 50;

const text = value => String(value ?? '').trim();
const encode = value => encodeURIComponent(text(value));

export function uploadSessionStorageKey(actorKey, projectId) {
  return `${UPLOAD_SESSION_V2_PREFIX}${encode(actorKey)}:${encode(projectId)}`;
}
export function uploadSessionLegacyKey(projectId) {
  return `${UPLOAD_SESSION_LEGACY_PREFIX}${encode(projectId)}`;
}
export function uploadIndexStorageKey(actorKey, projectId) {
  return `${UPLOAD_INDEX_PREFIX}${encode(actorKey)}:${encode(projectId)}`;
}
export async function withUploadIdentityLock({actorKey, projectId, wait = false}, work) {
  const manager = globalThis.navigator?.locks;
  if (!manager?.request) {
    throw new Error('当前浏览器不支持上传并发保护（Web Locks），已停止修改上传身份；请使用支持该能力的浏览器或原上传入口');
  }
  let acquired = false, result;
  await manager.request(`material-upload-identity:${text(actorKey)}:${text(projectId)}`,
    {ifAvailable: !wait}, async lock => {
      if (!lock) return;
      acquired = true;
      result = await work();
    });
  if (!acquired) throw new Error('另一个标签页正在修改同一账号和项目的上传身份，已停止本次操作');
  return result;
}
export function uploadRequestIds(seed, chunkCount) {
  const prefix = text(seed);
  const count = Math.max(0, Math.floor(Number(chunkCount) || 0));
  return Array.from({length: count}, (_, index) =>
    `${prefix}-${String(index + 1).padStart(4, '0')}`.slice(0, 64));
}

function uniqueText(values, maximum = MAX_REQUEST_IDS) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map(text).filter(Boolean))].slice(0, maximum);
}

export function normalizeUploadSession(value, {actorKey = '', projectId = '', source = 'v2'} = {}) {
  if (!value || typeof value !== 'object') return null;
  const project = text(value.projectId || value.project_id || projectId);
  if (!project || project !== text(projectId)) return null;
  const owner = text(value.owner || value.actorKey || '');
  return {
    projectId: project,
    owner,
    totalFiles: Math.max(0, Number(value.totalFiles) || 0),
    requestIds: uniqueText(value.requestIds),
    batchIds: uniqueText(value.batchIds),
    status: text(value.status || 'UNKNOWN').toUpperCase(),
    failed: Math.max(0, Number(value.failed) || 0),
    requestSeed: text(value.requestSeed),
    deferred: value.deferred === true,
    pendingDecision: Math.max(0, Number(value.pendingDecision) || 0),
    confirmationState: text(value.confirmationState || (value.deferred ? 'DEFERRED' : '')),
    createdAt: text(value.createdAt || value.updatedAt || ''),
    updatedAt: text(value.updatedAt || ''),
    source,
    legacy: source === 'legacy',
    owned: owner ? owner === text(actorKey) : false,
  };
}

function parse(storage, key) {
  try {
    const raw = storage?.getItem?.(key);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
function write(storage, key, value) {
  try { storage?.setItem?.(key, JSON.stringify(value)); return true; } catch { return false; }
}

export function readOwnedUploadSession({actorKey, projectId, storage = globalThis.localStorage} = {}) {
  const v2Key = uploadSessionStorageKey(actorKey, projectId);
  const v2 = normalizeUploadSession(parse(storage, v2Key), {actorKey, projectId, source: 'v2'});
  if (v2 && v2.owned) return {session: v2, key: v2Key, migrated: false};
  const legacyKey = uploadSessionLegacyKey(projectId);
  const legacyRaw = parse(storage, legacyKey);
  const legacy = normalizeUploadSession(legacyRaw, {actorKey, projectId, source: 'legacy'});
  if (legacy?.owned) {
    // Compatibility read only: keep the legacy key untouched and never assign
    // an owner-less record to the current account.
    return {session: legacy, key: legacyKey, migrated: false};
  }
  return {session: null, key: v2Key, migrated: false,
    unowned: legacy && !legacy.owner ? legacy : null};
}

export function isUploadSessionUnresolved(session) {
  if (!session?.requestIds?.length) return false;
  return !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(text(session.status).toUpperCase());
}
export function isUploadSessionProtected(session) {
  return isUploadSessionUnresolved(session)
    || Number(session?.pendingDecision || 0) > 0
    || session?.deferred === true
    || ['PENDING', 'DEFERRED'].includes(text(session?.confirmationState).toUpperCase());
}

function indexRecord(session) {
  return {
    id: session.requestIds[0] || `${session.createdAt}:${session.totalFiles}`,
    totalFiles: session.totalFiles,
    requestIds: session.requestIds,
    batchIds: session.batchIds,
    status: session.status,
    failed: session.failed,
    deferred: session.deferred === true,
    pendingDecision: Math.max(0, Number(session.pendingDecision) || 0),
    confirmationState: session.confirmationState || '',
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
  };
}

export function listUploadIndex({actorKey, projectId, storage = globalThis.localStorage} = {}) {
  const key = uploadIndexStorageKey(actorKey, projectId);
  const rows = parse(storage, key);
  if (!Array.isArray(rows)) return [];
  return rows
    .map(row => normalizeUploadSession({...row, projectId, owner: actorKey}, {actorKey, projectId, source: 'index'}))
    .filter(Boolean)
    .sort((left, right) => Number(isUploadSessionProtected(right)) - Number(isUploadSessionProtected(left))
      || String(right.updatedAt).localeCompare(String(left.updatedAt)))
    .slice(0, MAX_INDEX_ROWS);
}

function writeIndex({actorKey, projectId, storage}, session) {
  const key = uploadIndexStorageKey(actorKey, projectId);
  const rows = listUploadIndex({actorKey, projectId, storage});
  const record = indexRecord(session);
  const merged = [record, ...rows.filter(row => row.requestIds[0] !== record.id)]
    .sort((left, right) => Number(isUploadSessionProtected(right)) - Number(isUploadSessionProtected(left))
      || String(right.updatedAt).localeCompare(String(left.updatedAt)));
  const protectedRows = merged.filter(row => isUploadSessionProtected(row));
  if (protectedRows.length > MAX_INDEX_ROWS) return false;
  const ordinary = merged.filter(row => !isUploadSessionProtected(row));
  const keep = [...protectedRows, ...ordinary].slice(0, MAX_INDEX_ROWS);
  // Never claim success when the new pointer itself had to be evicted.
  if (!keep.some(row => row.requestIds[0] === record.id)) return false;
  return write(storage, key, keep.map(indexRecord));
}

function writeIndexSafely({actorKey, projectId, storage}, session) {
  const key = uploadIndexStorageKey(actorKey, projectId);
  try {
    const previous = storage?.getItem?.(key);
    const ok = writeIndex({actorKey, projectId, storage}, session);
    if (!ok && previous != null) {
      try { storage.setItem(key, previous); } catch { /* keep the previous pointer if possible */ }
    }
    return ok;
  } catch { return false; }
}

export function writeUploadSession({
  actorKey, projectId, patch = {}, storage = globalThis.localStorage, protectCurrent = false,
} = {}) {
  const key = uploadSessionStorageKey(actorKey, projectId);
  const existing = normalizeUploadSession(parse(storage, key), {actorKey, projectId, source: 'v2'});
  const now = new Date().toISOString();
  const session = {
    projectId, owner: text(actorKey),
    totalFiles: patch.totalFiles ?? existing?.totalFiles ?? 0,
    requestIds: uniqueText(patch.requestIds ?? existing?.requestIds ?? []),
    batchIds: uniqueText(patch.batchIds ?? existing?.batchIds ?? []),
    status: text(patch.status ?? existing?.status ?? 'UNKNOWN').toUpperCase(),
    failed: Math.max(0, Number(patch.failed ?? existing?.failed ?? 0) || 0),
    requestSeed: text(patch.requestSeed ?? existing?.requestSeed ?? ''),
    deferred: patch.deferred ?? existing?.deferred ?? false,
    pendingDecision: Math.max(0, Number(patch.pendingDecision ?? existing?.pendingDecision ?? 0) || 0),
    confirmationState: text(patch.confirmationState ?? existing?.confirmationState ?? ''),
    createdAt: existing?.createdAt || now,
    updatedAt: now,
  };
  let previousRaw;
  try { previousRaw = storage?.getItem?.(key) ?? null; } catch { previousRaw = null; }
  if (!write(storage, key, session)) return {ok: false, indexed: false, session: null};
  const indexed = writeIndexSafely({actorKey, projectId, storage}, session);
  if (!indexed) {
    // A session without an index pointer would be silently orphaned by the
    // next upload. Before any POST the caller asks us to restore the previous
    // pointer; after a POST the current pointer is kept so the user can still
    // recover the request that the server already accepted.
    if (!protectCurrent) {
      try {
        if (previousRaw == null) storage?.removeItem?.(key);
        else storage?.setItem?.(key, previousRaw);
      } catch { /* the caller still refuses to submit because ok is false */ }
      return {ok: false, indexed: false, session: null};
    }
    return {ok: false, indexed: false,
      session: normalizeUploadSession(session, {actorKey, projectId, source: 'v2'})};
  }
  return {ok: true, indexed: true, session: normalizeUploadSession(session, {actorKey, projectId, source: 'v2'})};
}

export function clearUploadSession({actorKey, projectId, storage = globalThis.localStorage} = {}) {
  try { storage?.removeItem?.(uploadSessionStorageKey(actorKey, projectId)); return true; }
  catch { return false; }
}

export async function updateUploadIndex({
  actorKey, projectId, id, patch = {}, storage = globalThis.localStorage,
} = {}) {
  const mutate = () => {
    const key = uploadIndexStorageKey(actorKey, projectId);
    const rows = listUploadIndex({actorKey, projectId, storage});
    const target = rows.find(row => row.requestIds[0] === id);
    if (!target) return false;
    const merged = {
      ...target,
      ...patch,
      projectId,
      owner: text(actorKey),
      requestIds: target.requestIds,
      updatedAt: new Date().toISOString(),
    };
    return writeIndexSafely({actorKey, projectId, storage}, merged);
  };
  try {
    return await withUploadIdentityLock({actorKey, projectId}, mutate);
  } catch {
    // Without an exclusive owner the index must stay unchanged; the display
    // still reads the server receipts, so a stale pending flag is safe.
    return false;
  }
}

export function listUploadSessions({actorKey, projectId, storage = globalThis.localStorage} = {}) {
  const current = readOwnedUploadSession({actorKey, projectId, storage}).session;
  const rows = listUploadIndex({actorKey, projectId, storage});
  const merged = current ? [current, ...rows] : rows;
  const seen = new Set();
  return merged.filter(row => {
    const id = row.requestIds[0] || `${row.createdAt}:${row.totalFiles}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  }).sort((left, right) => Number(isUploadSessionProtected(right)) - Number(isUploadSessionProtected(left))
    || String(right.updatedAt).localeCompare(String(left.updatedAt)))
    .slice(0, MAX_INDEX_ROWS);
}
