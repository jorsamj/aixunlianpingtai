from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]
repo_path = root / "platform_core" / "annotation_repository.py"
app_path = root / "app.py"

repo = repo_path.read_text(encoding="utf-8")
old_get = '''    def get(self, image_id):
        image_id = self._id(image_id)
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM annotations WHERE image_id=?", (image_id,)).fetchone()
        if row:
            result = dict(row)
            result['boxes'] = json.loads(result.pop('boxes_json'))
            result['annotation_scope'] = _normalize_scope(
                json.loads(result.pop('scope_json', '[]') or '[]')
            )
            if result['annotation_state'] == 'annotated' and not result['annotation_scope']:
                result['annotation_scope'] = _normalize_scope(
                    box.get('label') or box.get('code') for box in result['boxes']
                )
            if result['annotation_state'] == 'confirmed_empty' and not result['annotation_scope']:
                result['annotation_scope'] = self._default_negative_scope()
            return result
        path = self.project_path / 'annotations' / f'{image_id}.json'
'''
new_get = '''    def _decode_persisted_row(self, row):
        result = dict(row)
        result['boxes'] = json.loads(result.pop('boxes_json'))
        result['annotation_scope'] = _normalize_scope(
            json.loads(result.pop('scope_json', '[]') or '[]')
        )
        if result['annotation_state'] == 'annotated' and not result['annotation_scope']:
            result['annotation_scope'] = _normalize_scope(
                box.get('label') or box.get('code') for box in result['boxes']
            )
        if result['annotation_state'] == 'confirmed_empty' and not result['annotation_scope']:
            result['annotation_scope'] = self._default_negative_scope()
        return result

    def get(self, image_id):
        image_id = self._id(image_id)
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM annotations WHERE image_id=?", (image_id,)).fetchone()
        if row:
            return self._decode_persisted_row(row)
        path = self.project_path / 'annotations' / f'{image_id}.json'
'''
repo = replace_once(repo, old_get, new_get, "decode persisted annotation row")
repo = replace_once(
    repo,
    """    def upsert_many(self, rows, *, project_material: bool = True):
        written = []
        projections = {}
""",
    """    def upsert_many(
        self, rows, *, project_material: bool = True, return_rows: bool = False,
    ):
        written = []
        persisted_rows = []
        projections = {}
""",
    "upsert_many return-row option",
)
repo = replace_once(
    repo,
    """                projections[image_id] = {
""",
    """                if return_rows:
                    persisted = db.execute(
                        "SELECT * FROM annotations WHERE image_id=?", (image_id,)
                    ).fetchone()
                    if persisted is None:
                        raise RuntimeError("annotation upsert did not persist a row")
                    persisted_rows.append(self._decode_persisted_row(persisted))
                projections[image_id] = {
""",
    "same-connection persisted annotation read",
)
repo = replace_once(
    repo,
    """            MaterialRepository(self.project_path).patch(projections)
        return written

    def upsert(
""",
    """            MaterialRepository(self.project_path).patch(projections)
        return persisted_rows if return_rows else written

    def upsert(
""",
    "upsert_many return contract",
)
old_upsert = '''    def upsert(
        self, image_id, boxes, annotation_state=None, annotation_scope=None,
        *, project_material: bool = True,
    ):
        self.upsert_many([{
            'image_id': image_id,
            'boxes': boxes,
            'annotation_state': annotation_state,
            'annotation_scope': annotation_scope,
        }], project_material=project_material)
        return self.get(image_id)
'''
new_upsert = '''    def upsert(
        self, image_id, boxes, annotation_state=None, annotation_scope=None,
        *, project_material: bool = True,
    ):
        persisted = self.upsert_many([{
            'image_id': image_id,
            'boxes': boxes,
            'annotation_state': annotation_state,
            'annotation_scope': annotation_scope,
        }], project_material=project_material, return_rows=True)
        if not persisted:
            raise RuntimeError("annotation upsert did not return a persisted row")
        return persisted[0]
'''
repo = replace_once(repo, old_upsert, new_upsert, "single annotation same-connection return")
repo_path.write_text(repo, encoding="utf-8")

app = app_path.read_text(encoding="utf-8")
app = replace_once(
    app,
    '''def _v50_begin_image_batch(project_id: str):
    _IMAGE_BATCH_CTX.batch = {
        "project_id": project_id,
        "records": {},
        "patches": {},
    }

def _v50_queue_image_patch(project_id: str, image_id: str, patch: Dict[str, Any]) -> bool:
''',
    '''def _v50_begin_image_batch(project_id: str):
    _IMAGE_BATCH_CTX.batch = {
        "project_id": project_id,
        "records": {},
        "patches": {},
        # Lazily reused for all annotation writes in this import batch. The
        # repository is stateless between calls; each write still owns its
        # SQLite transaction, preserving current durability semantics.
        "annotation_repository": None,
    }


def _v50_annotation_repository(project_id: str) -> AnnotationRepository:
    batch = _v50_active_image_batch(project_id)
    if batch is not None:
        repository = batch.get("annotation_repository")
        if repository is None:
            repository = AnnotationRepository(project_dir(project_id))
            batch["annotation_repository"] = repository
        return repository
    return AnnotationRepository(project_dir(project_id))


def _v50_queue_image_patch(project_id: str, image_id: str, patch: Dict[str, Any]) -> bool:
''',
    "batch-scoped annotation repository",
)
app = replace_once(
    app,
    '''    saved = AnnotationRepository(project_dir(project_id)).upsert(
        image_id, boxes, annotation_state, project_material=False
    )
''',
    '''    saved = _v50_annotation_repository(project_id).upsert(
        image_id, boxes, annotation_state, project_material=False
    )
''',
    "write_annotation repository reuse",
)
app = replace_once(
    app,
    '''def read_annotation(project_id: str, image_id: str) -> Dict[str, Any]:
    return AnnotationRepository(project_dir(project_id)).get(image_id)
''',
    '''def read_annotation(project_id: str, image_id: str) -> Dict[str, Any]:
    return _v50_annotation_repository(project_id).get(image_id)
''',
    "read_annotation repository reuse",
)
app = replace_once(
    app,
    '''        AnnotationRepository(p).remove([img_id])
''',
    '''        _v50_annotation_repository(project_id).remove([img_id])
''',
    "add image failure repository reuse",
)
app_path.write_text(app, encoding="utf-8")
print("ZIP Processing P2a annotation connection migration applied")
