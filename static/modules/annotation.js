import {replaceMaterial} from './materials.js';

export function formalAnnotationState(response, boxes) {
  const allBoxes = boxes || [];
  const state = String(
    response?.annotation?.annotation_state ||
    response?.image?.annotation_state ||
    response?.annotation_state ||
    (allBoxes.length ? 'annotated' : 'unannotated')
  );
  return state;
}

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
  const state = formalAnnotationState(response, allBoxes);
  const isFormal = state === 'annotated' || state === 'confirmed_empty';
  const scope = response?.annotation?.annotation_scope || summary.annotation_scope || [];
  return replaceMaterial(materials, {
    ...summary,
    id: summary.id,
    annotated: isFormal,
    annotation_state: state,
    annotation_status: state,
    annotation_scope: Array.isArray(scope) ? scope : [],
    box_count: Number(summary.box_count ?? allBoxes.length),
    labels: [...new Set(allBoxes.map(box => box.label).filter(Boolean))],
    annotation_preview: preview,
    processing_status: isFormal ? 'processed' : summary.processing_status
  });
}
