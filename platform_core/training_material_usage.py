"""Rebuildable evidence projection in the existing Task database.

Absence is unknown until an explicit, bounded historical reconciliation marks
coverage complete. Neither terminal failure nor process launch erases exposure.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

from .training_splits import _relation_tokens


class TrainingMaterialUsage:
    def __init__(self, repository):
        self.path = Path(getattr(repository, 'path', repository))

    def _connect(self, write=False):
        if write:
            if not self.path.is_file():
                raise FileNotFoundError('usage projection requires the existing task database')
            db = sqlite3.connect(self.path, timeout=5)
        else:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        return db

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

    def record_selected(self, project_id, algorithm_id, task_id, snapshot, *, source_images=(), owner=None):
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
                db.executemany('INSERT OR IGNORE INTO training_material_usage(project_id,algorithm_id,task_id,snapshot_id,image_id,role,tokens_json,annotation_hash) VALUES(?,?,?,?,?,?,?,?)', records)
                for record in records:
                    db.execute('UPDATE training_material_usage SET tokens_json=? WHERE task_id=? AND image_id=? AND role=? AND tokens_json<>?',
                               (record[6], record[2], record[4], record[5], record[6]))
                    db.executemany('INSERT OR IGNORE INTO training_usage_tokens VALUES(?,?,?,?,?,?)',
                        [(record[0], key, value, record[2], record[4], record[5])
                         for key, value in json.loads(record[6])])

    def record_execution(self, task_id, *, first_batch=False, completed_epoch=False, validation_observed=False, generation=0, owner=None):
        level = 2 if completed_epoch else (1 if first_batch else 0)
        if not level and not validation_observed:
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
            with closing(sqlite3.connect(algorithm_db.resolve().as_uri()+'?mode=ro', uri=True)) as algorithms:
                if not algorithms.execute("SELECT 1 FROM sqlite_master WHERE name='algorithm_versions'").fetchone():
                    return False
                return algorithms.execute('SELECT 1 FROM algorithm_versions LIMIT 1').fetchone() is None
        return not (project / 'algorithms.json').exists()

    def read_revision(self):
        """O(1) invalidation token; no source file or usage-row enumeration."""
        if not self.path.is_file():
            return 'unknown'
        with closing(self._connect()) as db:
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
                generation=int(evidence.get('generation', 0)))
        return {'processed': len(ids)-len(unresolved), 'unresolved_task_ids': unresolved,
                'revision': self.read_revision()}

    def query_filter(self, project_id, algorithm_id, images, *, parent_task_ids=(), exclude_used=True, role='train'):
        images = list(images)
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
            # Historical test membership is not itself a benchmark lock. The
            # original benchmark owner applies its explicit frozen scope.
            protected = False
            level = max((row['evidence'] for row in exposed), default=0)
            state = ('used' if level >= 2 else 'possible' if level else 'selected' if rows else
                     'unused' if index['coverage'] == 'complete' else 'unknown')
            if not level and any(row['role'] in {'validation', 'test'} and row['evidence'] >= 2 for row in rows):
                state = 'eval_only'
            by_id[image_id] = {'state': state, 'excluded': bool((exclude_used and level) or protected),
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

    def _query_candidates(self, project_id, algorithm_id, images):
        result = {'records': [], 'revision': self.read_revision(), 'coverage': 'unknown'}
        if not self.path.is_file():
            return result
        tokens = sorted({token for image in images for token in
            [('image_id', str(image.get('id') or image.get('image_id') or '')), *_relation_tokens(image)]})
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='training_usage_tokens'").fetchone():
                if self._empty_project_history(db, project_id):
                    result['coverage'] = 'complete'
                return result
            coverage = db.execute('SELECT complete FROM training_usage_coverage WHERE project_id=? AND algorithm_id=?', (str(project_id),str(algorithm_id))).fetchone()
            result['coverage'] = 'complete' if coverage and coverage[0] else 'unknown'
            ready_table = db.execute("SELECT 1 FROM sqlite_master WHERE name='training_usage_token_schema'").fetchone()
            if not ready_table or not db.execute('SELECT 1 FROM training_usage_token_schema WHERE version=1').fetchone():
                result['coverage'] = 'unknown'
            revision = db.execute('SELECT revision FROM training_usage_meta WHERE id=1').fetchone()
            result['revision'] = str(revision[0]) if revision else 'unknown'
            matched = {}
            for start in range(0, len(tokens), 200):
                batch = tokens[start:start+200]
                clause = ' OR '.join('(t.token_kind=? AND t.token_value=?)' for _ in batch)
                params = [str(project_id), *(value for token in batch for value in token)]
                for row in db.execute('SELECT DISTINCT u.* FROM training_usage_tokens t JOIN training_material_usage u ON u.task_id=t.task_id AND u.image_id=t.image_id AND u.role=t.role WHERE t.project_id=? AND ('+clause+')', params):
                    value = dict(row)
                    matched[(value['task_id'],value['image_id'],value['role'])] = value
            result['records'] = list(matched.values())
        return result


def record_context_snapshot(context, task, payload, snapshot):
    index = TrainingMaterialUsage(context.repository)
    frozen = context.artifacts.read_json(task.task_id, payload.get('input_freeze_ref') or 'input-freeze.json', default={})
    sources = frozen.get('images') or [] if frozen.get('snapshot_id') == snapshot.get('snapshot_id') else []
    context.run_owned(lambda: index.record_selected(task.project_id,
        payload.get('algorithm_asset_id') or payload.get('asset_algorithm_id') or '', task.task_id, snapshot,
        source_images=sources, owner=usage_owner(context)))
    return index


def usage_owner(context):
    lease = getattr(context, 'lease', None)
    if lease is None:
        return None
    return (context.task.task_id, lease.lease_token, int(getattr(context, 'execution_generation', getattr(context.task, 'attempt', 0))))


def admit_history_selection(context, task, project, algorithm, payload, split, *, base_version_id=None, verified_benchmark_reuse=False):
    """Recheck original indexed facts before freeze, using the original GT fence."""
    from .material_repository import MaterialRepository
    from .training_splits import SplitRequest, SplitMode
    policy = str(payload.get('history_policy') or 'new_for_algorithm')
    if policy not in {'new_for_algorithm', 'include_history'}:
        raise ValueError('invalid training history_policy')
    index = TrainingMaterialUsage(context.repository)
    versions = {str(row.get('id') or ''): row for row in algorithm.get('versions') or []}
    parent_ids, unknown_parents, visited = [], [], set()
    from .training_label_tasks import _iteration_base
    previous, _base_selection = _iteration_base(algorithm, str(payload.get('model') or ''), str(payload.get('framework') or 'ultralytics'))
    current_id = str(base_version_id or payload.get('base_version_id') or (previous or {}).get('id') or '')
    while current_id:
        if current_id in visited or len(visited) >= 100:
            raise ValueError('training parent lineage is cyclic or exceeds safety bound')
        visited.add(current_id)
        version = versions.get(current_id)
        if not version:
            unknown_parents.append(current_id)
            break
        lineage = version.get('training_lineage') or {}
        parent_task = str(version.get('training_job_id') or lineage.get('task_id') or '')
        snapshot_id = str(version.get('snapshot_id') or lineage.get('snapshot_id') or '')
        if parent_task:
            parent_ids.append(parent_task)
            parent_record = context.repository.get(parent_task)
            if parent_record is None or parent_record.project_id != task.project_id:
                unknown_parents.append(current_id)
                current_id = str((lineage.get('base') or {}).get('version_id') or '')
                continue
            snapshot = context.artifacts.read_json(parent_task, 'snapshot.json', default={})
            if snapshot_id and snapshot.get('snapshot_id') == snapshot_id:
                parent_freeze = context.artifacts.read_json(parent_task, 'input-freeze.json', default={})
                sources = parent_freeze.get('images') or [] if parent_freeze.get('snapshot_id') == snapshot_id else []
                context.run_owned(lambda: index.record_selected(task.project_id, algorithm['id'], parent_task, snapshot,
                    source_images=sources, owner=usage_owner(context)))
                # A verified committed model attests exposure, without inventing
                # which epoch or exact batch touched any individual source.
                if version.get('artifact_verified') is True:
                    context.run_owned(lambda: index.record_execution(parent_task, first_batch=True, owner=usage_owner(context)))
            else:
                unknown_parents.append(current_id)
        else:
            unknown_parents.append(current_id)
        current_id = str((lineage.get('base') or {}).get('version_id') or '')
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
                               exclude_used=policy == 'new_for_algorithm')
    test = index.query_filter(task.project_id, algorithm['id'], rows, parent_task_ids=parent_ids, role='test')
    train_ids = tuple(item for item in split.train_image_ids if item not in train['excluded_image_ids'])
    if not train_ids:
        raise ValueError('TRAINING_HISTORY_EMPTY: no training materials remain after history exclusion')
    forbidden = sorted(set(test['excluded_image_ids']))
    if split.mode == SplitMode.INDEPENDENT_TEST_SET and set(split.test_image_ids) & set(forbidden):
        raise ValueError('TRAINING_TEST_HISTORY_EXPOSURE: selected Test has prior model exposure')
    effective = SplitRequest(mode=split.mode, train_image_ids=train_ids, test_image_ids=split.test_image_ids,
                             experiment_percent=split.experiment_percent, validation_percent=split.validation_percent)
    return effective, {'policy': policy, 'revision': train['revision'], 'coverage': train['coverage'],
        'excluded_train_image_ids': sorted(set(split.train_image_ids)-set(train_ids)),
        'forbidden_test_image_ids': forbidden, 'parent_task_ids': parent_ids,
        'unknown_parent_version_ids': unknown_parents}
