"""Rebuildable evidence projection in the existing Task database.

Absence is unknown until an explicit, bounded historical reconciliation marks
coverage complete. Neither terminal failure nor process launch erases exposure.
"""
from __future__ import annotations

from .performance_diagnostics import connect_sqlite, observe_connection, stage, count

import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

from .training_splits import _relation_tokens


class TrainingMaterialUsage:
    # A frozen role is a temporary reservation only while its original Task
    # remains live. Terminal failures without execution do not become locks.
    _ACTIVE_STATUSES = ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED', 'AWAITING_CONFIRMATION')

    def __init__(self, repository):
        self.path = Path(getattr(repository, 'path', repository))

    def _connect(self, write=False):
        if write:
            if not self.path.is_file():
                raise FileNotFoundError('usage projection requires the existing task database')
            db = connect_sqlite(self.path, timeout=5)
        else:
            db = connect_sqlite(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        return observe_connection(db)

    @staticmethod
    def _schema(db):
        db.executescript('''
        CREATE TABLE IF NOT EXISTS training_material_usage (
          project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, task_id TEXT NOT NULL,
          snapshot_id TEXT NOT NULL, image_id TEXT NOT NULL, role TEXT NOT NULL,
          tokens_json TEXT NOT NULL, annotation_hash TEXT NOT NULL,
          evidence INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(task_id,image_id,role));
        CREATE INDEX IF NOT EXISTS training_usage_scope ON training_material_usage(project_id,algorithm_id);
        CREATE TABLE IF NOT EXISTS training_usage_tokens (
          project_id TEXT NOT NULL, token_kind TEXT NOT NULL, token_value TEXT NOT NULL,
          task_id TEXT NOT NULL, image_id TEXT NOT NULL, role TEXT NOT NULL,
          PRIMARY KEY(project_id,token_kind,token_value,task_id,image_id,role));
        CREATE INDEX IF NOT EXISTS training_usage_token_task ON training_usage_tokens(task_id,image_id,role);
        CREATE TABLE IF NOT EXISTS training_usage_token_schema (version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO training_usage_token_schema SELECT 1
          WHERE NOT EXISTS(SELECT 1 FROM training_material_usage LIMIT 1);
        CREATE TABLE IF NOT EXISTS training_usage_coverage (
          project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, complete INTEGER NOT NULL,
          PRIMARY KEY(project_id,algorithm_id));
        CREATE TABLE IF NOT EXISTS training_usage_meta (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
        INSERT OR IGNORE INTO training_usage_meta VALUES(1,0);
        CREATE TRIGGER IF NOT EXISTS usage_insert_revision AFTER INSERT ON training_material_usage
        BEGIN UPDATE training_usage_meta SET revision=revision+1 WHERE id=1; END;
        CREATE TRIGGER IF NOT EXISTS usage_update_revision AFTER UPDATE ON training_material_usage
        BEGIN UPDATE training_usage_meta SET revision=revision+1 WHERE id=1; END;
        CREATE TRIGGER IF NOT EXISTS usage_token_revision AFTER INSERT ON training_usage_tokens
        BEGIN UPDATE training_usage_meta SET revision=revision+1 WHERE id=1; END;
        CREATE TRIGGER IF NOT EXISTS usage_coverage_revision AFTER INSERT ON training_usage_coverage
        BEGIN UPDATE training_usage_meta SET revision=revision+1 WHERE id=1; END;
        ''')

    @staticmethod
    def _check_owner(db, owner):
        if owner is None:
            return
        task_id, token, generation = owner
        row = db.execute('SELECT status,lease_token,attempt,lease_expires_at FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if (row is None or row['status'] not in {'RUNNING','CANCEL_REQUESTED'} or (token is not None and row['lease_token'] != token)
            or int(row['attempt']) != int(generation) or not row['lease_expires_at']
            or datetime.fromisoformat(row['lease_expires_at']) <= datetime.now(timezone.utc)):
            raise PermissionError('training usage evidence execution is fenced')

    def record_selected(self, project_id, algorithm_id, task_id, snapshot, *, source_images=(), owner=None,
                        enforce_isolation=False, parent_task_ids=()):
        records = []
        sources = {str(row.get('id') or ''): row for row in source_images}
        for row in snapshot.get('images') or []:
            role = row.get('role')
            if role not in {'train', 'validation', 'test'}:
                continue
            image_id = str(row.get('image_id') or '')
            if not image_id:
                raise ValueError('usage snapshot image identity missing')
            tokens = [('image_id', image_id), *_relation_tokens({**row, 'id': image_id})]
            source = sources.get(image_id)
            if source is not None:
                if source.get('content_sha256') != row.get('content_sha256'):
                    raise ValueError('usage source does not match frozen snapshot SHA')
                tokens.extend(_relation_tokens(source))
            records.append((str(project_id), str(algorithm_id), str(task_id), str(snapshot['snapshot_id']),
                            image_id, role, json.dumps(tokens), str(row.get('annotation_hash') or '')))
        with closing(self._connect(True)) as db:
            self._schema(db)
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._check_owner(db, owner)
                old = db.execute('SELECT DISTINCT snapshot_id FROM training_material_usage WHERE task_id=?', (str(task_id),)).fetchall()
                if any(row[0] != str(snapshot['snapshot_id']) for row in old):
                    raise ValueError('usage task snapshot identity changed')
                prior = {(row['image_id'],row['role']): json.loads(row['tokens_json']) for row in db.execute(
                    'SELECT image_id,role,tokens_json FROM training_material_usage WHERE task_id=?', (str(task_id),))}
                records = [(*record[:6], json.dumps(sorted({tuple(token) for token in
                    [*json.loads(record[6]), *prior.get((record[4],record[5]), [])]})), record[7]) for record in records]
                if enforce_isolation:
                    self._assert_role_reservations(db, records, parent_task_ids=parent_task_ids)
                db.executemany('INSERT OR IGNORE INTO training_material_usage(project_id,algorithm_id,task_id,snapshot_id,image_id,role,tokens_json,annotation_hash) VALUES(?,?,?,?,?,?,?,?)', records)
                for record in records:
                    db.execute('UPDATE training_material_usage SET tokens_json=? WHERE task_id=? AND image_id=? AND role=? AND tokens_json<>?',
                               (record[6], record[2], record[4], record[5], record[6]))
                    db.executemany('INSERT OR IGNORE INTO training_usage_tokens VALUES(?,?,?,?,?,?)',
                        [(record[0], key, value, record[2], record[4], record[5])
                         for key, value in json.loads(record[6])])

    def _assert_role_reservations(self, db, records, *, parent_task_ids=()):
        """Serialize role claims with the existing usage index under BEGIN IMMEDIATE.

        Read-then-write admission alone is unsafe across concurrent workers.
        Historical maintenance intentionally uses record_selected without this
        guard so genuine old conflicting evidence is preserved for audit.
        """
        inherited = set(map(str, parent_task_ids))
        wanted = sorted({tuple(token) for row in records for token in json.loads(row[6])})
        matched = {}
        for start in range(0, len(wanted), 200):
            batch = wanted[start:start + 200]
            params = [part for token in batch for part in token]
            params.append(str(records[0][0]))
            for row in db.execute(self._token_lookup_sql(len(batch)), params):
                matched[(row['task_id'], row['image_id'], row['role'])] = dict(row)
        statuses = self._task_statuses(db, matched)
        # Index only opposite, live/observed claims by token. Do not compare
        # every selected image with every historical row (quadratic on 10k+).
        conflicts_by_token = {}
        algorithm_id, task_id = (records[0][1], records[0][2]) if records else ('', '')
        for old in matched.values():
            if old['task_id'] == task_id or (old['algorithm_id'] != algorithm_id and old['task_id'] not in inherited):
                continue
            if int(old['evidence']) <= 0 and statuses.get(old['task_id']) not in self._ACTIVE_STATUSES:
                continue
            category = 'test' if old['role'] == 'test' else 'development' if old['role'] in {'train', 'validation'} else ''
            if not category:
                continue
            for token in json.loads(old['tokens_json']):
                conflicts_by_token.setdefault(tuple(token), {}).setdefault(category, old)
        for record in records:
            _project_id, _algorithm_id, _task_id, _snapshot_id, _image_id, role, raw_tokens, _hash = record
            if role not in {'train', 'validation', 'test'}:
                continue
            opposite = 'development' if role == 'test' else 'test'
            for token in json.loads(raw_tokens):
                old = conflicts_by_token.get(tuple(token), {}).get(opposite)
                if old:
                    code = 'TRAINING_TEST_HISTORY_EXPOSURE' if role == 'test' else 'TRAINING_TEST_RESERVED'
                    raise ValueError(f'{code}: historical {old["role"]} role conflicts with {role}')

    @staticmethod
    def _task_statuses(db, rows):
        if not rows or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
            return {}
        statuses = {}
        ids = sorted({str(row[0]) for row in rows})
        for start in range(0, len(ids), 200):
            batch = ids[start:start + 200]
            for task_id, status in db.execute('SELECT task_id,status FROM tasks WHERE task_id IN (' +
                                             ','.join('?' for _ in batch) + ')', batch):
                statuses[task_id] = status
        return statuses

    def record_execution(self, task_id, *, first_batch=False, completed_epoch=False, validation_observed=False,
                         test_observed=False, generation=0, owner=None):
        level = 2 if completed_epoch else (1 if first_batch else 0)
        if not level and not validation_observed and not test_observed:
            return
        with closing(self._connect(True)) as db:
            self._schema(db)
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._check_owner(db, owner)
                # An epoch completion attests train exposure; validation is only
                # possibly exposed unless separate validation evidence is supplied.
                db.execute('''UPDATE training_material_usage SET
                    evidence=MAX(evidence,CASE WHEN role='train' THEN ? ELSE 1 END),
                    generation=MAX(generation,?) WHERE task_id=? AND generation<=? AND role IN ('train','validation')
                    AND evidence < CASE WHEN role='train' THEN ? ELSE 1 END''',
                    (level, generation, str(task_id), generation, level))
                if validation_observed:
                    db.execute("UPDATE training_material_usage SET evidence=2,generation=MAX(generation,?) WHERE task_id=? AND role='validation' AND evidence<2 AND generation<=?",
                               (generation, str(task_id), generation))
                if test_observed:
                    db.execute("UPDATE training_material_usage SET evidence=2,generation=MAX(generation,?) WHERE task_id=? AND role='test' AND evidence<2 AND generation<=?",
                               (generation, str(task_id), generation))

    def mark_coverage(self, project_id, algorithm_id, *, complete):
        """Maintenance only: caller must reconcile all original Task evidence first."""
        with closing(self._connect(True)) as db:
            self._schema(db)
            with db:
                db.execute('INSERT OR REPLACE INTO training_usage_coverage VALUES(?,?,?)',
                           (str(project_id), str(algorithm_id), int(bool(complete))))

    def query_index(self, project_id, algorithm_id):
        result = {'revision': 'unknown', 'coverage': 'unknown', 'records': [], 'by_image_id': {}}
        if not self.path.is_file():
            return result
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='training_material_usage'").fetchone()
            if not exists:
                if self._empty_project_history(db, project_id):
                    result['coverage'] = 'complete'
                return result
            records = [dict(row) for row in db.execute('SELECT * FROM training_material_usage WHERE project_id=? ORDER BY task_id,image_id,role', (str(project_id),))]
            coverage = db.execute('SELECT complete FROM training_usage_coverage WHERE project_id=? AND algorithm_id=?', (str(project_id),str(algorithm_id))).fetchone()
            revision = db.execute('SELECT revision FROM training_usage_meta WHERE id=1').fetchone()
        result['records'] = records
        result['coverage'] = 'complete' if coverage and coverage[0] else 'unknown'
        result['revision'] = str(revision[0]) if revision else 'unknown'
        return result

    def _empty_project_history(self, db, project_id):
        """Only empty authoritative Task AND algorithm history proves fresh."""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
            return False
        if db.execute("SELECT 1 FROM tasks WHERE project_id=? AND kind='TRAINING' LIMIT 1", (str(project_id),)).fetchone():
            return False
        project = self.path.parent.parent / 'projects' / str(project_id)
        if project.parent.resolve() != (self.path.parent.parent / 'projects').resolve():
            return False
        algorithm_db = project / 'algorithms.sqlite3'
        if algorithm_db.is_file():
            with closing(observe_connection(connect_sqlite(algorithm_db.resolve().as_uri()+'?mode=ro', uri=True))) as algorithms:
                if not algorithms.execute("SELECT 1 FROM sqlite_master WHERE name='algorithm_versions'").fetchone():
                    return False
                return algorithms.execute('SELECT 1 FROM algorithm_versions LIMIT 1').fetchone() is None
        return not (project / 'algorithms.json').exists()

    def read_revision(self):
        """O(1) invalidation token; no source file or usage-row enumeration."""
        if not self.path.is_file():
            return 'unknown'
        with closing(self._connect()) as db:
            return self._read_revision(db)

    def has_exposed_records(self, project_id, algorithm_id, *, role='train', include_train_history=True):
        """Indexed presence probe for the picker default history policy.

        Only evidence that the existing query_filter excludes is relevant;
        incomplete historical coverage must never be interpreted as unused.
        """
        if not self.path.is_file():
            return False
        roles = (('train', 'validation') if role == 'test' else
                 ('train', 'test') if include_train_history else ('test',))
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_usage_tokens'").fetchone():
                return False
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_material_usage'").fetchone():
                return False
            task_status_clause = (" OR EXISTS (SELECT 1 FROM tasks t WHERE t.task_id=u.task_id AND t.status "
                "IN ('QUEUED','RUNNING','CANCEL_REQUESTED','AWAITING_CONFIRMATION'))"
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone() else '')
            return db.execute(
                'SELECT 1 FROM training_material_usage u WHERE u.project_id=? AND u.algorithm_id=? '
                'AND (u.evidence>0' + task_status_clause + ') AND u.role IN (' +
                ','.join('?' for _ in roles) + ') LIMIT 1',
                (str(project_id), str(algorithm_id), *roles),
            ).fetchone() is not None

    @staticmethod
    def _read_revision(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='training_usage_meta'").fetchone():
            return 'unknown'
        row = db.execute('SELECT revision FROM training_usage_meta WHERE id=1').fetchone()
        return str(row[0]) if row else 'unknown'

    def rebuild_batch(self, project_id, task_ids, load_owner_evidence, *, limit=100):
        """Explicit bounded maintenance; never invoked by listing.

        load_owner_evidence(task_id) must authenticate the original Task/payload/
        Snapshot identity and return algorithm_id,snapshot,job,generation. Missing
        originals remain unresolved. Completion never implies full coverage here.
        """
        if not 1 <= limit <= 500:
            raise ValueError('usage maintenance limit must be 1..500')
        ids = list(dict.fromkeys(map(str, task_ids)))
        if len(ids) > limit:
            raise ValueError('usage maintenance batch exceeds limit')
        unresolved = []
        for task_id in ids:
            evidence = load_owner_evidence(task_id)
            if not evidence or not evidence.get('snapshot'):
                unresolved.append(task_id)
                continue
            self.record_selected(project_id, evidence['algorithm_id'], task_id, evidence['snapshot'])
            job = evidence.get('job') or {}
            self.record_execution(task_id, first_batch=job.get('training_started') is True,
                completed_epoch=job.get('usage_completed_epoch') is True,
                test_observed=evidence.get('test_observed') is True,
                generation=int(evidence.get('generation', 0)))
        return {'processed': len(ids)-len(unresolved), 'unresolved_task_ids': unresolved,
                'revision': self.read_revision()}

    def query_filter(self, project_id, algorithm_id, images, *, parent_task_ids=(), exclude_used=True, role='train'):
        images = list(images)
        count("usage_candidate_rows",len(images))
        index = self._query_candidates(project_id, algorithm_id, images)
        parent_ids = set(map(str, parent_task_ids))
        token_rows = {}
        for row in index['records']:
            for token in json.loads(row['tokens_json']):
                token_rows.setdefault(tuple(token), []).append(row)
        by_id = {}
        for image in images:
            image_id = str(image.get('id') or image.get('image_id') or '')
            matches = {}
            all_matches = {}
            for token in [('image_id', image_id), *_relation_tokens(image)]:
                for row in token_rows.get(token, ()):
                    all_matches[(row['task_id'], row['image_id'], row['role'])] = row
                    if row['algorithm_id'] == str(algorithm_id) or row['task_id'] in parent_ids:
                        matches[(row['task_id'], row['image_id'], row['role'])] = row
            rows = list(matches.values())
            exposed = [row for row in rows if row['evidence'] > 0 and
                       (row['role'] == 'train' or (role == 'test' and row['role'] == 'validation'))]
            if role == 'test':
                # A chosen ancestor checkpoint cannot certify its frozen pool
                # as unseen merely because old batch telemetry is unavailable.
                exposed += [dict(row, evidence=max(1, row['evidence'])) for row in rows
                            if row['task_id'] in parent_ids and row['role'] in {'train', 'validation'}]
            # Selected-only terminal tasks do not reserve anything. Observed
            # Test always does; an active Test holds a temporary reservation.
            protected = role != 'test' and any(row['role'] == 'test' and
                (row['evidence'] > 0 or row.get('task_status') in self._ACTIVE_STATUSES) for row in rows)
            if role == 'test':
                exposed.extend(dict(row, evidence=max(1, row['evidence'])) for row in rows
                               if row['role'] in {'train', 'validation'}
                               and row.get('task_status') in self._ACTIVE_STATUSES and row not in exposed)
            level = max((row['evidence'] for row in exposed), default=0)
            state = ('used' if level >= 2 else 'possible' if level else 'selected' if rows else
                     'unused' if index['coverage'] == 'complete' else 'unknown')
            if protected:
                state = 'test_reserved'
            elif not level and any(row['role'] in {'validation', 'test'} and row['evidence'] >= 2 for row in rows):
                state = 'eval_only'
            by_id[image_id] = {'state': state, 'excluded': bool(((exclude_used or role == 'test') and level) or protected),
                               'benchmark_protected': bool(protected),
                               'current_algorithm_trained': any(row['algorithm_id'] == str(algorithm_id) and row['role'] == 'train' and row['evidence'] > 0 for row in all_matches.values()),
                               'other_algorithm_trained': any(row['algorithm_id'] != str(algorithm_id) and row['role'] == 'train' and row['evidence'] > 0 for row in all_matches.values()),
                               'history_scope_complete': index['coverage'] == 'complete',
                               'task_ids': sorted({row['task_id'] for row in rows}),
                               'history_details': [{'task_id': row['task_id'], 'snapshot_id': row['snapshot_id'], 'algorithm_id': row['algorithm_id'],
                                   'role': row['role'], 'evidence': row['evidence']} for row in all_matches.values()]}
        return {'revision': index['revision'], 'coverage': index['coverage'], 'by_image_id': by_id,
                'excluded_image_ids': [key for key, value in by_id.items() if value['excluded']],
                'unknown_image_ids': [key for key, value in by_id.items() if value['state'] == 'unknown']}

    @staticmethod
    def _token_lookup_sql(batch_size):
        """Make each requested token an exact lookup on the existing composite PK.

        A 200-way OR previously let SQLite scan every token in a project before
        filtering. VALUES drives one indexed (project,kind,value) seek per token.
        Deduplicate only the narrow usage identity before reading full rows:
        DISTINCT on u.* forced a wide temporary sort and lost the index gain.
        """
        if not 1 <= batch_size <= 200:
            raise ValueError('token lookup batch size must be 1..200')
        placeholders = ','.join('(?,?)' for _ in range(batch_size))
        return (
            'WITH requested_tokens(token_kind,token_value) AS (VALUES ' + placeholders + ') '
            ', matched AS MATERIALIZED ('
            'SELECT DISTINCT t.task_id,t.image_id,t.role FROM requested_tokens r '
            'JOIN training_usage_tokens t ON t.project_id=? '
            'AND t.token_kind=r.token_kind AND t.token_value=r.token_value) '
            'SELECT u.* FROM matched m JOIN training_material_usage u '
            'ON u.task_id=m.task_id AND u.image_id=m.image_id AND u.role=m.role'
        )

    @stage("usage_lookup")
    def _query_candidates(self, project_id, algorithm_id, images):
        result = {'records': [], 'revision': 'unknown', 'coverage': 'unknown'}
        if not self.path.is_file():
            return result
        tokens = sorted({token for image in images for token in
            [('image_id', str(image.get('id') or image.get('image_id') or '')), *_relation_tokens(image)]})
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='training_usage_tokens'").fetchone():
                result['revision'] = self._read_revision(db)
                if self._empty_project_history(db, project_id):
                    result['coverage'] = 'complete'
                return result
            coverage = db.execute('SELECT complete FROM training_usage_coverage WHERE project_id=? AND algorithm_id=?', (str(project_id),str(algorithm_id))).fetchone()
            result['coverage'] = 'complete' if coverage and coverage[0] else 'unknown'
            ready_table = db.execute("SELECT 1 FROM sqlite_master WHERE name='training_usage_token_schema'").fetchone()
            if not ready_table or not db.execute('SELECT 1 FROM training_usage_token_schema WHERE version=1').fetchone():
                result['coverage'] = 'unknown'
            # Preserve the original malformed-schema error instead of silently
            # accepting a token index whose mandatory revision table vanished.
            revision = db.execute('SELECT revision FROM training_usage_meta WHERE id=1').fetchone()
            result['revision'] = str(revision[0]) if revision else 'unknown'
            matched = {}
            for start in range(0, len(tokens), 200):
                batch = tokens[start:start+200]
                params = [*(value for token in batch for value in token), str(project_id)]
                for row in db.execute(self._token_lookup_sql(len(batch)), params):
                    value = dict(row)
                    matched[(value['task_id'],value['image_id'],value['role'])] = value
            statuses = self._task_statuses(db, matched)
            result['records'] = [dict(row, task_status=statuses.get(row['task_id'], '')) for row in matched.values()]
        return result


def record_context_snapshot(context, task, payload, snapshot):
    index = TrainingMaterialUsage(context.repository)
    frozen = context.artifacts.read_json(task.task_id, payload.get('input_freeze_ref') or 'input-freeze.json', default={})
    sources = frozen.get('images') or [] if frozen.get('snapshot_id') == snapshot.get('snapshot_id') else []
    parents = (payload.get('history_admission') or {}).get('parent_task_ids') or ()
    context.run_owned(lambda: index.record_selected(task.project_id,
        payload.get('algorithm_asset_id') or payload.get('asset_algorithm_id') or '', task.task_id, snapshot,
        source_images=sources, owner=usage_owner(context), enforce_isolation=True, parent_task_ids=parents))
    return index


def usage_owner(context):
    lease = getattr(context, 'lease', None)
    if lease is None:
        return None
    return (context.task.task_id, lease.lease_token, int(getattr(context, 'execution_generation', getattr(context.task, 'attempt', 0))))


def _verified_weight_parents(project, base_selection, *, catalog=None):
    """A local, content-identical verified checkpoint links algorithms; names do not.

    Only inspect the *chosen* training weight. A remote URL, model family,
    advertised version ID, or filename similarity cannot establish ancestry.
    """
    from .algorithms import list_algorithms

    selected = str(base_selection.get('base_model_path') or '').strip()
    path = Path(selected).expanduser() if selected else None
    if path is None or not path.is_file() or path.suffix.lower() not in {'.pt', '.pdparams', '.pdmodel', '.pdiparams'}:
        return [], ''
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    selected_sha = digest.hexdigest()
    matches = []
    for candidate in (catalog if catalog is not None else list_algorithms(Path(project) / 'algorithms.json')):
        for version in candidate.get('versions') or []:
            if version.get('artifact_verified') is not True:
                continue
            verified = {str(item.get('sha256') or '').lower() for item in version.get('verified_models') or []
                        if isinstance(item, dict) and item.get('verified') is not False}
            # Older verified local archives predate verified_models. Their
            # original on-disk checkpoint can still prove an exact match.
            if not verified:
                for field in ('best_path', 'last_path', 'stored_path'):
                    archived = str(version.get(field) or '').strip()
                    if not archived:
                        continue
                    other_path = Path(archived).expanduser()
                    if other_path.is_file() and other_path.resolve() == path.resolve():
                        verified.add(selected_sha)
            if selected_sha in verified:
                matches.append((str(candidate.get('id') or ''), str(version.get('id') or '')))
    return sorted(set(matches)), selected_sha


def assert_formal_test_independence(index, snapshot, project_id, algorithm_id, *,
                                    parent_task_ids=(), benchmark_reuse=False):
    """Mandatory late fence before publishing any independent-Test scores.

    Works on original frozen pixel identities, not mutable material-list rows.
    A historical query's absence of matches is not proof while coverage is
    incomplete. Inference without ground-truth metrics does not call this.
    """
    rows = [dict(row, id=str(row.get('image_id') or '')) for row in snapshot.get('images') or []
            if isinstance(row, dict) and row.get('role') == 'test']
    declared_test = snapshot.get('test_image_ids')
    if declared_test is None and isinstance(snapshot.get('ids'), dict):
        declared_test = snapshot['ids'].get('test')
    if declared_test is not None and set(map(str, declared_test)) != {row['id'] for row in rows}:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: frozen Test identities and role rows differ')
    if not rows:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: formal Test has no frozen image evidence')
    if not str(snapshot.get('snapshot_id') or '') or any(not row['id'] or not row.get('content_sha256') for row in rows):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: formal Test snapshot identity missing')
    result = index.query_filter(project_id, algorithm_id, rows,
                                parent_task_ids=parent_task_ids, role='test')
    excluded = sorted(result['excluded_image_ids'])
    if excluded:
        raise ValueError('TRAINING_TEST_HISTORY_EXPOSURE: formal Test contains exposed Train/Val identities: '
                         + ', '.join(excluded[:5]))
    if result['coverage'] != 'complete' and not benchmark_reuse:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: historical coverage not verified before formal scoring')
    if any(result['by_image_id'][row['id']]['state'] == 'unknown' for row in rows) and not benchmark_reuse:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: Test image exposure is unknown')
    return {'status': 'passed', 'test_count': len(rows), 'revision': result['revision'],
            'coverage': result['coverage']}


def require_formal_history_admission(admission):
    """Prevents pre-enforcement or unbound requests certifying fresh Test scores."""
    if (not isinstance(admission, dict) or not str(admission.get('revision') or '')
            or not isinstance(admission.get('parent_task_ids'), list)
            or not isinstance(admission.get('model_ancestry'), list)):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: formal scoring requires frozen history admission')
    return admission


def assert_frozen_formal_test(project_dir, task_id, snapshot_id):
    """Local checkpoint/scoring worker late gate; original Task controls scope."""
    from .task_runtime.artifacts import ArtifactStore
    project = Path(project_dir).resolve()
    data_dir = project.parent.parent
    artifacts = ArtifactStore(data_dir / 'task_runtime' / 'artifacts')
    snapshot = artifacts.read_json(task_id, 'snapshot.json', default={})
    if not isinstance(snapshot, dict) or snapshot.get('snapshot_id') != snapshot_id:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: original frozen Test snapshot missing or changed')
    payload = artifacts.read_json(task_id, 'payload.json', default={})
    if not isinstance(payload, dict) or str(payload.get('snapshot_id') or '') != snapshot_id:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: original Task payload does not bind Test snapshot')
    algorithm_id = str(payload.get('algorithm_asset_id') or payload.get('asset_algorithm_id') or '')
    if not algorithm_id:
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: formal Test algorithm identity missing')
    admission = require_formal_history_admission(payload.get('history_admission'))
    frozen = artifacts.read_json(task_id, payload.get('input_freeze_ref') or 'input-freeze.json', default={})
    if (not isinstance(frozen, dict) or frozen.get('snapshot_id') != snapshot_id
            or frozen.get('history_admission') != admission):
        raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: frozen input history identity does not match Task')
    if not snapshot.get('test_image_ids') and not (snapshot.get('ids') or {}).get('test'):
        return {'status': 'not_requested', 'test_count': 0}
    return assert_formal_test_independence(
        TrainingMaterialUsage(data_dir / 'task_runtime' / 'tasks.sqlite3'), snapshot,
        project.name, algorithm_id, parent_task_ids=admission.get('parent_task_ids') or (),
        benchmark_reuse=bool(payload.get('benchmark_reuse')))


def admit_history_selection(context, task, project, algorithm, payload, split, *, base_version_id=None, verified_benchmark_reuse=False):
    """Recheck original indexed facts before freeze, using the original GT fence."""
    from .material_repository import MaterialRepository
    from .training_splits import SplitRequest, SplitMode
    policy = str(payload.get('history_policy') or 'new_for_algorithm')
    if policy not in {'new_for_algorithm', 'include_history'}:
        raise ValueError('invalid training history_policy')
    index = TrainingMaterialUsage(context.repository)
    from .algorithms import list_algorithms
    catalog = {str(item.get('id') or ''): item for item in list_algorithms(Path(project) / 'algorithms.json')}
    # The caller may already hold a freshly updated algorithm not yet visible
    # in a read-cache; it is the authoritative current-algorithm selection.
    catalog[str(algorithm['id'])] = algorithm
    versions = {str(row.get('id') or ''): row for row in algorithm.get('versions') or []}
    parent_ids, unknown_parents, visited, ancestry = [], [], set(), []
    from .training_label_tasks import _iteration_base
    previous, base_selection = _iteration_base(algorithm, str(payload.get('model') or ''), str(payload.get('framework') or 'ultralytics'))
    selected_id = str((previous or {}).get('id') or '')
    requested_id = str(base_version_id or payload.get('base_version_id') or '')
    if requested_id and requested_id != selected_id:
        raise ValueError('TRAINING_TEST_ANCESTRY_UNKNOWN: requested base version does not match selected checkpoint')
    matched, base_sha = _verified_weight_parents(project, base_selection, catalog=catalog.values())
    pending = [(str(algorithm['id']), selected_id)] if selected_id else []
    pending.extend(pair for pair in matched if pair not in pending)
    while pending:
        algorithm_id, current_id = pending.pop(0)
        key = (algorithm_id, current_id)
        if key in visited:
            continue
        if len(visited) >= 100:
            raise ValueError('training parent lineage is cyclic or exceeds safety bound')
        visited.add(key)
        origin = catalog.get(algorithm_id) or {}
        version = next((row for row in origin.get('versions') or [] if str(row.get('id') or '') == current_id), None)
        if not version:
            unknown_parents.append(f'{algorithm_id}:{current_id}')
            continue
        lineage = version.get('training_lineage') or {}
        parent_task = str(version.get('training_job_id') or version.get('task_id') or lineage.get('task_id') or '')
        snapshot_id = str(version.get('snapshot_id') or lineage.get('snapshot_id') or '')
        ancestry.append({'algorithm_id': algorithm_id, 'version_id': current_id,
                         'task_id': parent_task, 'snapshot_id': snapshot_id})
        if parent_task:
            parent_record = context.repository.get(parent_task)
            if parent_record is None or parent_record.project_id != task.project_id:
                unknown_parents.append(f'{algorithm_id}:{current_id}')
            else:
                snapshot = context.artifacts.read_json(parent_task, 'snapshot.json', default={})
                if snapshot_id and snapshot.get('snapshot_id') == snapshot_id and version.get('artifact_verified') is True:
                    parent_ids.append(parent_task)
                    parent_freeze = context.artifacts.read_json(parent_task, 'input-freeze.json', default={})
                    sources = parent_freeze.get('images') or [] if parent_freeze.get('snapshot_id') == snapshot_id else []
                    context.run_owned(lambda: index.record_selected(task.project_id, algorithm_id, parent_task, snapshot,
                        source_images=sources, owner=usage_owner(context)))
                    # A verified committed model attests Train/Val exposure;
                    # only a separately bound successful blind evaluation can
                    # attest Test observation if the old job telemetry is gone.
                    evaluation = version.get('evaluation') or {}
                    scope = evaluation.get('benchmark_scope') or {}
                    tested = (evaluation.get('status') == 'succeeded'
                              and evaluation.get('snapshot_id') == snapshot_id
                              and scope.get('binding_level') == 'bundle_verified')
                    context.run_owned(lambda: index.record_execution(parent_task, first_batch=True,
                        test_observed=tested, owner=usage_owner(context)))
                else:
                    unknown_parents.append(f'{algorithm_id}:{current_id}')
        else:
            unknown_parents.append(f'{algorithm_id}:{current_id}')
        base_id = str((lineage.get('base') or {}).get('version_id') or '')
        if base_id:
            pending.append((algorithm_id, base_id))
        for inherited in lineage.get('model_ancestry') or []:
            if not isinstance(inherited, dict):
                raise ValueError('TRAINING_TEST_ANCESTRY_UNKNOWN: invalid inherited model lineage')
            inherited_algo, inherited_version = str(inherited.get('algorithm_id') or ''), str(inherited.get('version_id') or '')
            if not inherited_algo or not inherited_version:
                raise ValueError('TRAINING_TEST_ANCESTRY_UNKNOWN: incomplete inherited model lineage')
            pending.append((inherited_algo, inherited_version))
    if unknown_parents and not verified_benchmark_reuse:
        raise ValueError('TRAINING_TEST_ANCESTRY_UNKNOWN: 父模型训练来源证据缺失，不能证明新试验集独立；请恢复血缘证据或使用已核验的冻结基准')
    if not versions:
        with closing(index._connect()) as db:
            has_tasks = db.execute("SELECT 1 FROM tasks WHERE project_id=? AND kind='TRAINING' AND task_id<>? LIMIT 1",
                                   (str(task.project_id), str(task.task_id))).fetchone()
        if not has_tasks:
            context.run_owned(lambda: index.mark_coverage(task.project_id, algorithm['id'], complete=True))
    rows = MaterialRepository(project).get_many((*split.train_image_ids, *split.test_image_ids))
    train = index.query_filter(task.project_id, algorithm['id'], rows,
                               parent_task_ids=parent_ids, exclude_used=policy == 'new_for_algorithm')
    test = index.query_filter(task.project_id, algorithm['id'], rows, parent_task_ids=parent_ids, role='test')
    train_ids = tuple(item for item in split.train_image_ids if item not in train['excluded_image_ids'])
    if not train_ids:
        raise ValueError('TRAINING_HISTORY_EMPTY: no training materials remain after history exclusion')
    # Incomplete legacy coverage is not proof of independent Test eligibility.
    # A previously observed and locked Test is allowed for a verified benchmark
    # comparison; an unknown candidate must not be silently made a new Test.
    uncertain = set() if verified_benchmark_reuse else {
        image_id for image_id, fact in test['by_image_id'].items()
        if fact['state'] == 'unknown' or (test['coverage'] != 'complete' and
           fact['state'] == 'selected')
    }
    forbidden = sorted(set(test['excluded_image_ids']) | uncertain)
    if split.mode == SplitMode.INDEPENDENT_TEST_SET and set(split.test_image_ids) & set(forbidden):
        raise ValueError('TRAINING_TEST_HISTORY_EXPOSURE: selected Test has prior exposure or unverified history')
    effective = SplitRequest(mode=split.mode, train_image_ids=train_ids, test_image_ids=split.test_image_ids,
                             experiment_percent=split.experiment_percent, validation_percent=split.validation_percent)
    return effective, {'policy': policy, 'revision': train['revision'], 'coverage': train['coverage'],
        'base_model_sha256': base_sha, 'model_ancestry': ancestry,
        'excluded_train_image_ids': sorted(set(split.train_image_ids)-set(train_ids)),
        'forbidden_test_image_ids': forbidden, 'parent_task_ids': sorted(set(parent_ids)),
        'unknown_parent_version_ids': unknown_parents}
