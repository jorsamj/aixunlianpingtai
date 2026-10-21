// Pure projection only. The caller retains the authoritative GT, CAS version,
// image SHA, history and review scope. No annotation state is stored here.
function dimensions({width, height} = {}) {
  if (![width, height].every(n => Number.isFinite(n) && n > 0)) throw new Error('Invalid image dimensions');
  return {width, height};
}

function pixels({x1, y1, x2, y2}, size) {
  const {width, height} = dimensions(size);
  if (![x1,y1,x2,y2].every(Number.isFinite) || x1 < 0 || y1 < 0 || x2 > width || y2 > height || x2 <= x1 || y2 <= y1)
    throw new Error('Invalid rectangle geometry: finite positive original pixels within image required');
  return {x1,y1,x2,y2};
}

function annotationId(id) {
  if (!['string', 'number'].includes(typeof id) || String(id).trim() === '') throw new Error('Missing rectangle id');
  return String(id);
}

/** Older repository imports can lack box IDs. Allocate only those identities
 * deterministically in the current live document; existing IDs are untouched.
 * Nothing is persisted until the original version-checked save succeeds. */
export function withLegacyBoxIdentities(boxes = [], {imageId} = {}) {
  if(!String(imageId||'').trim())throw new Error('Legacy rectangle identity requires an image id');
  const used=new Set(boxes.filter(box=>box.id!=null&&String(box.id).trim()!=='').map(box=>String(box.id)));
  return boxes.map((box,index)=>{
    if(box.id!=null&&String(box.id).trim()!=='')return box;
    const base=`legacy:${String(imageId)}:${index}`;let id=base,suffix=0;
    while(used.has(id))id=`${base}:${++suffix}`;
    used.add(id);return {...box,id};
  });
}

/** GT box -> official @annotorious/annotorious 3.9.5 ImageAnnotation. */
export function toAnno(box, size) {
  const id = annotationId(box?.id);
  const {x1,y1,x2,y2} = pixels(box, size);
  return {
    id,
    bodies: [{id: `${id}:label`, annotation: id, purpose: 'tagging', value: String(box.label ?? '')}],
    target: {annotation: id, selector: {type: 'RECTANGLE', geometry: {
      x:x1, y:y1, w:x2-x1, h:y2-y1,
      bounds: {minX:x1,minY:y1,maxX:x2,maxY:y2},
    }}},
  };
}

/** Returns a visible correction reason; never substitutes a default class. */
export function annotationLabelIssue(box, labels = []) {
  const label = labels.find(row => String(row.code) === String(box.label) && row.active !== false && (!row.status || row.status === 'active'));
  if (!label) return {code:'unknown_label', label:box.label, class_id:box.class_id};
  if (String(label.class_id) !== String(box.class_id)) return {code:'class_code_mismatch', label:box.label, class_id:box.class_id};
  return null;
}

/**
 * Official rectangle -> one GT box. originalBoxesById must be the caller's
 * current GT map, including hidden boxes; it is never mutated or cached.
 * Newly drawn annotations keep the library's freshly generated ID. Their
 * label must be supplied explicitly, never inferred from the first class.
 */
export function fromAnno(annotation, {width, height, originalBoxesById, labels = [], newLabel} = {}) {
  if (!(originalBoxesById instanceof Map)) throw new Error('originalBoxesById Map is required');
  const id = annotationId(annotation?.id);
  if (annotation?.target?.selector?.type !== 'RECTANGLE') throw new Error('Only rectangle annotations are supported');
  const geometry = annotation.target.selector.geometry;
  const {x, y, w, h, bounds, rot} = geometry || {};
  if (![x,y,w,h].every(Number.isFinite) || w <= 0 || h <= 0 || (rot !== undefined && rot !== 0)) throw new Error('Invalid rectangle geometry');
  const coords = pixels({x1:x,y1:y,x2:x+w,y2:y+h}, {width,height});
  // 3.9.5 RectangleEditor derives bounds from reactive rotatedCorners, which
  // may still describe the previous pointer frame. Validate the public shape,
  // but derive GT endpoints from x/y/w/h instead of trusting this index cache.
  if (!bounds || !['minX','minY','maxX','maxY'].every(key => Number.isFinite(bounds[key])))
    throw new Error('Invalid rectangle geometry bounds');
  const original = originalBoxesById.get(id);
  const tags = (annotation.bodies || []).filter(body => body.purpose === 'tagging');
  if (tags.length > 1) throw new Error('A rectangle must have one label');
  const code = tags.length ? String(tags[0].value ?? '') : original ? String(original.label ?? '') : String(newLabel?.code ?? '');
  if (!original && !code) throw new Error('A new rectangle requires an explicitly selected label');
  const label = labels.find(row => String(row.code) === code);
  const classId = original && code === String(original.label ?? '') ? original.class_id : label?.class_id ?? (newLabel?.code === code ? newLabel.class_id : null);
  // x + (x2 - x) can differ by one ULP. Preserve the exact original endpoints
  // when the official component has not changed this geometry.
  if (original && x === original.x1 && y === original.y1 && w === original.x2-original.x1 && h === original.y2-original.y1)
    Object.assign(coords, {x1:original.x1,y1:original.y1,x2:original.x2,y2:original.y2});
  return {...original, id:original?.id ?? id, class_id:classId, label:code, ...coords};
}
