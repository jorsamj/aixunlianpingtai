export function replaceMaterial(items, replacement) {
  if (!replacement?.id) return items;
  const target = String(replacement.id);
  let found = false;
  const next = items.map(item => {
    if (String(item.id) !== target) return item;
    found = true;
    return {...item, ...replacement};
  });
  return found ? next : items;
}

export function filterByAnyLabel(rows, selectedLabels) {
  const selected = new Set(selectedLabels || []);
  if (!selected.size) return [...rows];
  return rows.filter(row => (row.labels || []).some(label => selected.has(label)));
}

export function labelDisplay(code, library) {
  const normalized = String(code || '').trim();
  const item = (library || []).find(label => String(label?.code || '') === normalized);
  const displayName = String(item?.display_name || item?.display_name_zh || '').trim();
  return displayName && displayName !== normalized ? `${normalized} · ${displayName}` : normalized;
}

export function labelsFromReferences(rows, selectedIds) {
  const selected = new Set((selectedIds || []).map(String));
  const labels = new Set();
  for (const row of rows || []) {
    if (!selected.has(String(row?.id))) continue;
    for (const label of row?.labels || []) {
      const value = String(label || '').trim();
      if (value) labels.add(value);
    }
  }
  return [...labels].sort();
}
