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
