from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]
app_path = root / "app.py"
p1_test_path = root / "tests" / "api" / "test_zip_processing_p1.py"

app = app_path.read_text(encoding="utf-8")
app = replace_once(
    app,
    '''def add_image_record(\n    project_id: str, src: Path, original_name: str,\n    source_type: str = "raw", dataset_id: str = "default",\n    storage_source_id: str = "default_local",\n) -> Optional[Dict[str, Any]]:\n''',
    '''def add_image_record(\n    project_id: str, src: Path, original_name: str,\n    source_type: str = "raw", dataset_id: str = "default",\n    storage_source_id: str = "default_local", annotation_builder=None,\n) -> Optional[Dict[str, Any]]:\n''',
    "add_image_record signature",
)
app = replace_once(
    app,
    '''    annotation_path = p / "annotations" / f"{img_id}.json"\n    batch = None\n    try:\n        with _v50_dataset_locks(project_id, [target_dataset_id]):\n            _v50_assert_dataset_writable_locked(project_id, target_dataset_id)\n            batch = _v50_active_image_batch(project_id)\n            if batch:\n                image_id = str(img_id)\n                buffered = dict(record)\n                pending_patch = batch["patches"].pop(image_id, None)\n                if pending_patch:\n                    buffered.update(pending_patch)\n                batch["records"][image_id] = buffered\n            else:\n                record = material_store(project_id).upsert(record)\n            if not annotation_path.exists():\n                write_annotation(project_id, img_id, [], 'unannotated')\n''',
    '''    annotation_path = p / "annotations" / f"{img_id}.json"\n    batch = None\n    try:\n        prepared_annotation_boxes = None\n        if annotation_builder is not None:\n            prepared_annotation_boxes = list(annotation_builder(dict(record)) or [])\n        with _v50_dataset_locks(project_id, [target_dataset_id]):\n            _v50_assert_dataset_writable_locked(project_id, target_dataset_id)\n            batch = _v50_active_image_batch(project_id)\n            if batch:\n                image_id = str(img_id)\n                buffered = dict(record)\n                pending_patch = batch["patches"].pop(image_id, None)\n                if pending_patch:\n                    buffered.update(pending_patch)\n                batch["records"][image_id] = buffered\n            else:\n                record = material_store(project_id).upsert(record)\n            if prepared_annotation_boxes is not None:\n                # Structured import paths already know the final GT. Persist it once\n                # before returning instead of durable unannotated -> final double writes.\n                write_annotation(project_id, img_id, prepared_annotation_boxes)\n            elif not annotation_path.exists():\n                write_annotation(project_id, img_id, [], 'unannotated')\n''',
    "prepared final annotation write",
)

start = app.index("def _v18_import_yolo(")
end = app.index("\n\n@app.post('/api/v18/projects/{project_id}/datasets/{dataset_id}/import')", start)
new_yolo = '''def _v18_import_yolo(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], progress_cb=None) -> bool:\n    label_files = [x for x in root.rglob('*.txt') if x.name.lower() not in {'classes.txt','obj.names','_darknet.labels','train.txt','val.txt','test.txt'}]\n    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)\n    if not image_files:\n        return False\n    names = _v18_collect_class_names(root, label_files)\n    project = get_project(project_id)\n    if names:\n        for n in names:\n            ensure_label(project, n)\n    elif not project.get('labels'):\n        ensure_label(project, 'object')\n        names = ['object']\n    imported_names = names or project.get('labels', [])\n    label_by_stem: Dict[str, List[Path]] = {}\n    for lf in label_files:\n        label_by_stem.setdefault(lf.stem, []).append(lf)\n    any_imported = False\n    total_expected=max(1,len(image_files)); progress_done=0\n    for img in image_files:\n        split = _v18_split_from_path(img)\n        cands = label_by_stem.get(img.stem, [])\n        label_file = None\n        if cands:\n            # 优先选与图片同 split 且路径包含 labels 的 txt\n            same_split = [x for x in cands if _v18_split_from_path(x) == split]\n            label_file = next((x for x in same_split if any(part.lower()=='labels' for part in x.parts)), same_split[0] if same_split else cands[0])\n        boxes=[]\n\n        def build_final_annotation(record):\n            if label_file and label_file.exists():\n                for line in label_file.read_text(encoding='utf-8', errors='ignore').splitlines():\n                    box = yolo_line_to_box(line, record['width'], record['height'])\n                    if not box:\n                        report['invalid_boxes'] += 1\n                        continue\n                    old_cls = int(box.get('class_id', -1))\n                    if old_cls < 0:\n                        report['invalid_boxes'] += 1\n                        continue\n                    if old_cls < len(imported_names):\n                        label = normalize_label(imported_names[old_cls])\n                        new_cls = get_label_id(project, label)\n                    elif old_cls < len(project.get('labels', [])):\n                        new_cls = old_cls\n                    else:\n                        report['skipped_labels'] += 1\n                        continue\n                    box['class_id'] = new_cls\n                    box['label'] = project['labels'][new_cls]\n                    box['id'] = uuid.uuid4().hex[:10]\n                    boxes.append(box)\n            else:\n                report['unmatched_labels'] += 1\n            return boxes\n\n        rec = add_image_record(\n            project_id, img, img.name, 'imported_yolo', dataset_id,\n            annotation_builder=build_final_annotation,\n        )\n        if not rec:\n            report['skipped_images'] += 1\n            continue\n        _v18_set_image_split(project_id, rec['id'], split)\n        report.setdefault('imported_image_ids', []).append(rec['id'])\n        for _b in boxes:\n            _lab = str(_b.get('label') or '').strip()\n            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1\n        report['imported_images'] += 1; report['boxes'] += len(boxes)\n        if boxes: report['annotated_images'] += 1\n        any_imported = True\n        progress_done += 1\n        if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,f'正在导入 YOLO 图片 {progress_done}/{total_expected}')\n    if any_imported:\n        report['detected_format'] = 'YOLO'\n    return any_imported\n'''
app = app[:start] + new_yolo + app[end:]
app_path.write_text(app, encoding="utf-8")

p1 = p1_test_path.read_text(encoding="utf-8")
p1 = replace_once(
    p1,
    '''    # P1 intentionally preserves the initial unannotated write plus final annotation write.\n    assert annotation_upserts == 200\n''',
    '''    # P2b persists the final YOLO truth before add_image_record returns, in one write.\n    assert annotation_upserts == 100\n''',
    "P1 annotation transaction expectation",
)
p1_test_path.write_text(p1, encoding="utf-8")
