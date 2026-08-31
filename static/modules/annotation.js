import {replaceMaterial} from './materials.js';

export function applyAnnotationResult(materials, response, boxes) {
  const allBoxes = boxes || [];
  const preview = allBoxes.slice(0, 64).map(box => ({
    class_id: box.class_id,
    label: box.label,
    x1: box.x1,
    y1: box.y1,
    x2: box.x2,
    y2: box.y2
  }));
  const summary = response?.image || {};
  return replaceMaterial(materials, {
    ...summary,
    id: summary.id,
    annotated: allBoxes.length > 0,
    box_count: Number(summary.box_count ?? allBoxes.length),
    labels: [...new Set(allBoxes.map(box => box.label).filter(Boolean))],
    annotation_preview: preview
  });
}
