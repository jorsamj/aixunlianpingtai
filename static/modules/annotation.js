import {replaceMaterial} from './materials.js';

export function applyAnnotationResult(materials, response, boxes) {
  const preview = (boxes || []).slice(0, 64).map(box => ({
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
    annotated: preview.length > 0,
    box_count: preview.length,
    labels: [...new Set(preview.map(box => box.label).filter(Boolean))],
    annotation_preview: preview
  });
}
