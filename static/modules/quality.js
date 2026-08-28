function score(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

export function qualityChartModel(quality = {}) {
  const dimensions = Object.entries(quality.scores || {}).map(([label, value]) => ({
    label,
    score: score(value)
  }));
  const labels = Object.entries(quality.label_boxes || {})
    .map(([label, value]) => ({label, count: Math.max(0, Number(value) || 0)}))
    .sort((left, right) => right.count - left.count);
  return {dimensions, labels, maxLabelCount: labels[0]?.count || 0};
}
