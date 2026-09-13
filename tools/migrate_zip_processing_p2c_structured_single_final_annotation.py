from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


COCO_FUNCTION = '''def _v18_import_coco(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:
    json_files = []
    for jp in root.rglob('*.json'):
        try:
            data = json.loads(jp.read_text(encoding='utf-8', errors='ignore'))
            if isinstance(data, dict) and isinstance(data.get('images'), list) and isinstance(data.get('annotations'), list) and isinstance(data.get('categories'), list):
                json_files.append((jp, data))
        except Exception:
            continue
    if not json_files:
        return False
    project = get_project(project_id)
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    total_expected=sum(len(coco.get('images',[])) for _,coco in json_files) or 1
    progress_done=0
    for ann_json, coco in json_files:
        split = _v18_split_from_path(ann_json)
        cats = sorted(coco.get('categories', []), key=lambda c: int(c.get('id', 0)))
        cat_to_class = {}
        for c in cats:
            label = normalize_label(c.get('name') or f'class_{c.get("id")}')
            cid = int(c.get('id'))
            cat_to_class[cid] = ensure_label(project, label)
        anns_by_img: Dict[int, List[Dict[str, Any]]] = {}
        for a in coco.get('annotations', []):
            try:
                anns_by_img.setdefault(int(a.get('image_id')), []).append(a)
            except Exception:
                pass
        for im in coco.get('images', []):
            file_name = str(im.get('file_name') or '').replace('\\\\','/')
            src = by_rel.get(file_name) or by_name.get(Path(file_name).name)
            if not src and Path(file_name).stem in by_stem:
                src = by_stem[Path(file_name).stem][0]
            if not src or not src.exists():
                report['missing_images'] += 1
                continue
            boxes=[]
            image_annotations = anns_by_img.get(int(im.get('id')), [])

            def build_final_annotation(record):
                for a in image_annotations:
                    cid = int(a.get('category_id', -1))
                    if cid not in cat_to_class:
                        continue
                    bbox = a.get('bbox') or []
                    if len(bbox) < 4:
                        continue
                    x,y,w,h = [float(v) for v in bbox[:4]]
                    if w < 2 or h < 2:
                        report['invalid_boxes'] += 1
                        continue
                    cls = cat_to_class[cid]
                    boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':project['labels'][cls], 'x1':round(max(0,x),2), 'y1':round(max(0,y),2), 'x2':round(min(record['width'],x+w),2), 'y2':round(min(record['height'],y+h),2)})
                return boxes

            rec = add_image_record(
                project_id, src, Path(file_name).name or src.name, 'imported_coco', dataset_id,
                annotation_builder=build_final_annotation,
            )
            if not rec:
                report['skipped_images'] += 1
                continue
            _v18_set_image_split(project_id, rec['id'], split)
            report.setdefault('imported_image_ids', []).append(rec['id'])
            for _b in boxes:
                _lab = str(_b.get('label') or '').strip()
                if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
            report['imported_images'] += 1
            report['boxes'] += len(boxes)
            if boxes: report['annotated_images'] += 1
            progress_done += 1
            if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 COCO 图片 {progress_done}/{total_expected}')
    report['detected_format'] = 'COCO'
    return True
'''


VOC_FUNCTION = '''def _v18_import_voc(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:
    import xml.etree.ElementTree as ET
    xml_files = list(root.rglob('*.xml'))
    if not xml_files:
        return False
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    project = get_project(project_id)
    any_imported = False
    total_expected=max(1,len(xml_files)); progress_done=0
    for xp in xml_files:
        try:
            r = ET.parse(xp).getroot()
        except Exception:
            continue
        filename = (r.findtext('filename') or '').strip()
        src = by_name.get(filename) or by_stem.get(Path(filename).stem if filename else xp.stem, [None])[0]
        if not src:
            report['missing_images'] += 1
            continue
        split = _v18_split_from_path(xp)
        boxes=[]
        objects = list(r.findall('object'))

        def build_final_annotation(record):
            for obj in objects:
                label = normalize_label(obj.findtext('name') or 'object')
                if not label: continue
                cls = ensure_label(project, label)
                bb = obj.find('bndbox')
                if bb is None: continue
                try:
                    x1=float(bb.findtext('xmin')); y1=float(bb.findtext('ymin')); x2=float(bb.findtext('xmax')); y2=float(bb.findtext('ymax'))
                except Exception:
                    report['invalid_boxes'] += 1
                    continue
                if x2-x1<2 or y2-y1<2:
                    report['invalid_boxes'] += 1
                    continue
                boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':project['labels'][cls], 'x1':round(max(0,x1),2), 'y1':round(max(0,y1),2), 'x2':round(min(record['width'],x2),2), 'y2':round(min(record['height'],y2),2)})
            return boxes

        rec = add_image_record(
            project_id, src, src.name, 'imported_voc', dataset_id,
            annotation_builder=build_final_annotation,
        )
        if not rec:
            report['skipped_images'] += 1
            continue
        _v18_set_image_split(project_id, rec['id'], split)
        report.setdefault('imported_image_ids', []).append(rec['id'])
        for _b in boxes:
            _lab = str(_b.get('label') or '').strip()
            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
        report['imported_images'] += 1; report['boxes'] += len(boxes)
        if boxes: report['annotated_images'] += 1
        any_imported = True
        progress_done += 1
        if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 VOC 图片 {progress_done}/{total_expected}')
    if any_imported:
        report['detected_format'] = 'Pascal VOC'
    return any_imported
'''


def replace_block(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


def main() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    app = replace_block(
        app,
        "def _v18_import_coco(",
        "\n\ndef _v18_import_voc(",
        COCO_FUNCTION,
    )
    app = replace_block(
        app,
        "def _v18_import_voc(",
        "\n\ndef _v18_import_yolo(",
        VOC_FUNCTION,
    )
    APP_PATH.write_text(app, encoding="utf-8")


if __name__ == "__main__":
    main()
