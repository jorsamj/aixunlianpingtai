"""Optional management associations in the canonical material database.

These attributes never certify absence of a training target and never write GT.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import uuid

from .material_repository import material_annotation_lifecycle_fence


_DDL = (
    "CREATE TABLE IF NOT EXISTS negative_pool_members (material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE, joined_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_negative_pool_joined ON negative_pool_members(joined_at,material_id)",
    "CREATE TABLE IF NOT EXISTS negative_pool_categories (id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, enabled INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS negative_pool_links (material_id TEXT NOT NULL REFERENCES negative_pool_members(material_id) ON DELETE CASCADE, category_id TEXT NOT NULL REFERENCES negative_pool_categories(id) ON DELETE CASCADE, PRIMARY KEY(material_id,category_id))",
    "CREATE INDEX IF NOT EXISTS ix_negative_pool_category ON negative_pool_links(category_id,material_id)",
    "CREATE TABLE IF NOT EXISTS negative_pool_meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)",
    "INSERT OR IGNORE INTO negative_pool_meta VALUES (1,0)",
)
_LIVE = "json_extract(m.payload_json,'$._dataset_delete_claim') IS NULL AND json_extract(m.payload_json,'$._material_batch_delete_claim') IS NULL AND COALESCE(json_extract(m.payload_json,'$.deleted'),0)=0 AND json_extract(m.payload_json,'$.deleted_at') IS NULL"
_REVIEW = "CASE WHEN COALESCE(json_extract(m.payload_json,'$.annotation_needs_review'),0)<>0 OR COALESCE(json_extract(m.payload_json,'$.external_annotation_needs_review'),0)<>0 OR COALESCE(json_extract(m.payload_json,'$.needs_review'),0)<>0 THEN 'stale' ELSE COALESCE(json_extract(m.payload_json,'$.annotation_state'),json_extract(m.payload_json,'$.annotation_status'),CASE WHEN m.annotated<>0 THEN 'annotated' ELSE 'unannotated' END) END"


class NegativePool:
    def __init__(self, materials):
        self.materials = materials

    @staticmethod
    def _exists(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='negative_pool_members'").fetchone() is not None

    @staticmethod
    def _ids(values):
        if not isinstance(values, (list, tuple)) or len(values) > 50000:
            raise ValueError('image_ids/category_ids must be a list with at most 50000 entries')
        result = list(dict.fromkeys(str(v).strip() for v in values))
        if any(not v or len(v) > 256 for v in result):
            raise ValueError('invalid identity')
        return result

    def _mutate(self, operation):
        with material_annotation_lifecycle_fence(self.materials.project_path), closing(self.materials._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for sql in _DDL:
                    db.execute(sql)
                result = operation(db)
                db.execute('UPDATE negative_pool_meta SET revision=revision+1 WHERE id=1')
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def revision(self):
        with closing(self.materials._connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='negative_pool_meta'").fetchone():
                return '0'
            return str(db.execute('SELECT revision FROM negative_pool_meta WHERE id=1').fetchone()[0])

    def candidate_ids(self, category_ids=()):
        """Internal identity-only intersection; the public selection cap is separate."""
        categories=self._ids(category_ids)
        with closing(self.materials._connect()) as db:
            if not self._exists(db):
                return []
            clause=''
            if categories:
                clause=' AND EXISTS (SELECT 1 FROM negative_pool_links l WHERE l.material_id=m.id AND l.category_id IN ('+','.join('?' for _ in categories)+'))'
            return [r[0] for r in db.execute('SELECT m.id FROM negative_pool_members n JOIN materials m ON m.id=n.material_id WHERE '+_LIVE+clause+' ORDER BY m.id',categories)]

    def categories(self, query=''):
        with closing(self.materials._connect()) as db:
            if not self._exists(db):
                return []
            return [dict(r) for r in db.execute("SELECT c.*, (SELECT COUNT(*) FROM negative_pool_links l JOIN materials m ON m.id=l.material_id WHERE l.category_id=c.id AND " + _LIVE + ") AS material_count FROM negative_pool_categories c WHERE c.name LIKE ? ORDER BY c.name,c.id", ('%'+query+'%',))]

    def category(self, category_id=None, *, name=None, enabled=None, delete=False):
        if name is not None:
            name = str(name).strip()
            if not name or len(name) > 100:
                raise ValueError('category name must contain 1–100 characters')
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError('enabled must be boolean')
        def write(db):
            identity = category_id or uuid.uuid4().hex
            if category_id:
                if not db.execute('SELECT 1 FROM negative_pool_categories WHERE id=?', (identity,)).fetchone():
                    raise ValueError('category not found')
                if delete:
                    db.execute('DELETE FROM negative_pool_categories WHERE id=?', (identity,))
                    return {'id': identity, 'deleted': True}
                if name is not None:
                    db.execute('UPDATE negative_pool_categories SET name=? WHERE id=?', (name,identity))
                if enabled is not None:
                    db.execute('UPDATE negative_pool_categories SET enabled=? WHERE id=?', (int(enabled),identity))
            else:
                if name is None:
                    raise ValueError('name is required')
                db.execute('INSERT INTO negative_pool_categories VALUES (?,?,1)', (identity,name))
            return dict(db.execute('SELECT * FROM negative_pool_categories WHERE id=?', (identity,)).fetchone())
        return self._mutate(write)

    def members(self, image_ids, *, action='add', category_ids=(), categories_only=False):
        ids, categories = self._ids(image_ids), self._ids(category_ids)
        if action not in ('add','remove','set') or (action == 'set' and not categories_only):
            raise ValueError('invalid action')
        def write(db):
            db.execute('CREATE TEMP TABLE pool_requested(id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO pool_requested VALUES (?)', ((v,) for v in ids))
            valid = [r[0] for r in db.execute('SELECT m.id FROM materials m JOIN pool_requested r ON r.id=m.id WHERE '+_LIVE)]
            if len(valid) != len(ids):
                raise ValueError('material missing or being deleted; no associations changed')
            for category in categories:
                row = db.execute('SELECT enabled FROM negative_pool_categories WHERE id=?',(category,)).fetchone()
                if not row or (action != 'remove' and not row[0]):
                    raise ValueError('category missing or disabled')
            if categories_only and db.execute('SELECT COUNT(*) FROM negative_pool_members n JOIN pool_requested r ON r.id=n.material_id').fetchone()[0] != len(ids):
                raise ValueError('material is not in negative pool')
            if not categories_only:
                if action == 'remove':
                    db.execute('DELETE FROM negative_pool_members WHERE material_id IN (SELECT id FROM pool_requested)')
                    return {'affected':len(ids)}
                now = datetime.now(timezone.utc).isoformat()
                db.executemany('INSERT OR IGNORE INTO negative_pool_members VALUES (?,?)', ((v,now) for v in ids))
            if action == 'set':
                db.execute('DELETE FROM negative_pool_links WHERE material_id IN (SELECT id FROM pool_requested)')
            sql = 'DELETE FROM negative_pool_links WHERE material_id=? AND category_id=?' if action == 'remove' else 'INSERT OR IGNORE INTO negative_pool_links VALUES (?,?)'
            db.executemany(sql, ((v,c) for v in ids for c in categories))
            return {'affected':len(ids)}
        return self._mutate(write)

    def query(self, *, query='', category_ids=(), labels=(), joined_days=None, joined_from=None, joined_to=None, review_status=None, page=1, page_size=50, ids_only=False):
        if page < 1 or not 1 <= page_size <= 1000:
            raise ValueError('invalid pagination')
        clauses, params = [_LIVE], []
        if query:
            clauses.append("(m.filename LIKE ? OR m.id LIKE ? OR COALESCE(json_extract(m.payload_json,'$.name'),'') LIKE ?)")
            params.extend(['%'+query+'%']*3)
        for values, predicate in ((self._ids(category_ids), 'EXISTS (SELECT 1 FROM negative_pool_links l WHERE l.material_id=m.id AND l.category_id IN ({marks}))'), (self._ids(labels), 'EXISTS (SELECT 1 FROM material_labels ml WHERE ml.material_id=m.id AND ml.label_code IN ({marks}))')):
            if values:
                clauses.append(predicate.format(marks=','.join('?' for _ in values)))
                params.extend(values)
        if joined_days is not None:
            if joined_days not in (7,30):
                raise ValueError('joined_days must be 7 or 30')
            joined_from = (datetime.now(timezone.utc)-timedelta(days=joined_days)).isoformat()
        for value, operator in ((joined_from,'>='),(joined_to,'<=')):
            if value:
                parsed = datetime.fromisoformat(str(value).replace('Z','+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                # A date-only upper bound includes that whole UTC calendar day.
                bound_operator = operator
                if operator == '<=' and len(str(value)) == 10:
                    parsed += timedelta(days=1)
                    bound_operator = '<'
                clauses.append('n.joined_at '+bound_operator+' ?')
                params.append(parsed.astimezone(timezone.utc).isoformat())
        # Original formal annotation projection, never target-specific negative approval.
        if review_status:
            clauses.append(_REVIEW+' = ?')
            params.append(review_status)
        base = ' FROM negative_pool_members n JOIN materials m ON m.id=n.material_id WHERE '+' AND '.join(clauses)
        with closing(self.materials._connect()) as db:
            if not self._exists(db):
                return {'items':[], 'total':0, 'page':page,'page_size':page_size}
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*)'+base,params).fetchone()[0]
            if ids_only:
                if total > 50000:
                    raise ValueError('selection exceeds 50000; narrow filters')
                return {'items':[r[0] for r in db.execute('SELECT m.id'+base+' ORDER BY n.joined_at DESC,m.id',params)],'total':total,'limit':50000}
            rows = db.execute('SELECT m.*,n.joined_at,'+_REVIEW+' AS pool_review_status'+base+' ORDER BY n.joined_at DESC,m.id LIMIT ? OFFSET ?',params+[page_size,(page-1)*page_size]).fetchall()
            db.execute('CREATE TEMP TABLE pool_page(id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO pool_page VALUES (?)', ((r['id'],) for r in rows))
            links = {}
            for r in db.execute('SELECT l.material_id,c.* FROM negative_pool_links l JOIN negative_pool_categories c ON c.id=l.category_id JOIN pool_page p ON p.id=l.material_id'):
                links.setdefault(r['material_id'],[]).append({k:r[k] for k in ('id','name','enabled')})
            items=[]
            for row in rows:
                item=self.materials._row_payload(row)
                item['negative_pool']={'joined_at':row['joined_at'],'categories':links.get(row['id'],[]),'review_status':row['pool_review_status'],'training_usage':'unknown'}
                items.append(item)
            return {'items':items,'total':total,'page':page,'page_size':page_size,'total_pages':max(1,(total+page_size-1)//page_size)}
