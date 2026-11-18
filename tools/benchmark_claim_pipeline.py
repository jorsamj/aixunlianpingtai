"""Temporary SQLite claim microbenchmark; timings are single samples, not production P95."""
from __future__ import annotations
from contextlib import closing
import argparse
import inspect
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_core.task_runtime.repository import TaskRepository, _to_values
from platform_core.task_runtime.models import TaskRecord, TaskKind

class Cursor:
    def __init__(self, cursor, metrics, candidate):
        self.cursor, self.metrics, self.candidate = cursor, metrics, candidate
    def _count(self, rows):
        if self.candidate:
            self.metrics['candidate_rows'] += len(rows)
        return rows
    def fetchall(self): return self._count(self.cursor.fetchall())
    def fetchmany(self, *args): return self._count(self.cursor.fetchmany(*args))
    def fetchone(self):
        row = self.cursor.fetchone()
        self._count([] if row is None else [row])
        return row
    def __iter__(self):
        for row in self.cursor:
            self._count([row])
            yield row
    def __getattr__(self, name): return getattr(self.cursor, name)

class Connection:
    def __init__(self, connection, metrics):
        self.connection, self.metrics, self.started = connection, metrics, None
    def execute(self, sql, *args):
        normalized = ' '.join(sql.lower().split())
        self.metrics['total_sql'] += 1
        candidate = normalized.startswith('select') and 'from tasks candidate' in normalized
        if candidate: self.metrics['candidate_sql'] += 1
        if normalized.startswith('begin immediate'):
            self.metrics['begin_immediate'] += 1
            start = time.perf_counter()
            result = self.connection.execute(sql, *args)
            self.started = time.perf_counter()
            self.metrics['writer_acquire_seconds'] += self.started - start
        else: result = self.connection.execute(sql, *args)
        return Cursor(result, self.metrics, candidate)
    def _end(self):
        if self.started is not None:
            self.metrics['writer_seconds'] += time.perf_counter() - self.started
            self.started = None
    def commit(self):
        try: return self.connection.commit()
        finally: self._end()
    def rollback(self):
        try: return self.connection.rollback()
        finally: self._end()
    def close(self):
        try: return self.connection.close()
        finally: self._end()
    def __getattr__(self, name): return getattr(self.connection, name)


def sample(size, tail, budget):
    with tempfile.TemporaryDirectory(prefix='claim-benchmark-') as directory:
        repository = TaskRepository(Path(directory) / 'tasks.sqlite3')
        with closing(repository._connect()) as database:
            template = _to_values(TaskRecord.new('seed', 'benchmark', TaskKind.DEPLOYMENT_TEST,
                                                'request.json', 'benchmark-resource', required_capabilities=('missing',)))
            columns = tuple(template)
            values = []
            for index in range(size):
                row = dict(template, task_id=f'task-{index:08d}')
                if tail and index == size - 1: row['required_capabilities'] = '[]'
                values.append(tuple(row[key] for key in columns))
            database.executemany(f"INSERT INTO tasks ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
            database.commit()
        metrics = dict(candidate_rows=0, candidate_sql=0, total_sql=0, begin_immediate=0,
                       recovery_calls=0, writer_seconds=0.0, writer_acquire_seconds=0.0, prepare_calls=0)
        connect, recover = repository._connect, repository._release_expired_in
        repository._connect = lambda: Connection(connect(), metrics)
        def recovery(*args):
            metrics['recovery_calls'] += 1
            return recover(*args)
        repository._release_expired_in = recovery
        def admission(*args): return True, None
        def prepare(candidate):
            metrics['prepare_calls'] += 1
            return None
        admission.prepare = prepare
        kwargs = {}
        if budget is not None:
            parameters = inspect.signature(repository.claim_next).parameters
            for name in ('candidate_budget', 'scan_budget', 'max_candidates'):
                if name in parameters:
                    kwargs[name] = budget
                    break
            else:
                raise ValueError('claim_next has no supported budget parameter')
        plans = []
        from platform_core.task_runtime.claim_candidates import page
        with closing(connect()) as plan_database:
            class PlanConnection:
                def execute(self, sql, params):
                    plans.append([tuple(row) for row in plan_database.execute('EXPLAIN QUERY PLAN ' + sql, params)])
                    return plan_database.execute(sql, params)
            page(PlanConnection(), 64, kinds=('DEPLOYMENT_TEST',))
            page(PlanConnection(), 64, (50, 0, template['created_at'], 'task-00000063'), kinds=('DEPLOYMENT_TEST',))
        started = time.perf_counter()
        lease = repository.claim_next('benchmark-worker', [TaskKind.DEPLOYMENT_TEST], [], admission=admission, **kwargs)
        metrics.update(claim_seconds=time.perf_counter()-started, size=size,
                       scenario='tail_runnable' if tail else 'missing_capabilities', budget=budget,
                       claimed_task=lease.task.task_id if lease else None)
        first = dict(metrics)
        total_seconds = first['claim_seconds']
        total_rows = first['candidate_rows']
        max_rows = total_rows
        cycles = 1
        if tail:
            # Reuse the repository and worker: the advisory cursor advances per poll.
            for _ in range(size + 10):
                if lease is not None:
                    break
                before_rows = metrics['candidate_rows']
                started = time.perf_counter()
                lease = repository.claim_next('benchmark-worker', [TaskKind.DEPLOYMENT_TEST], [], admission=admission, **kwargs)
                total_seconds += time.perf_counter() - started
                rows = metrics['candidate_rows'] - before_rows
                total_rows += rows
                max_rows = max(max_rows, rows)
                cycles += 1
            if lease is None:
                raise RuntimeError('tail task was not reached within generous bounded poll limit')
        first.update(cycles_to_tail=cycles if tail else None, total_claim_seconds=total_seconds,
                     total_rows=total_rows, max_single_claim_rows=max_rows,
                     tail_claimed_task=lease.task.task_id if lease else None, queued_query_plans=plans)
        return first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sizes', default='1000,5000,10000,20000')
    parser.add_argument('--budgets', default='', help='Comma-separated supported explicit candidate budgets; empty uses default')
    args = parser.parse_args()
    results = [sample(int(size), tail, budget) for budget in ([int(x) for x in args.budgets.split(',')] if args.budgets else [None])
               for size in args.sizes.split(',') for tail in (False, True)]
    report = dict(description=__doc__, python=sys.version, results=results)
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding='utf-8')
    print(serialized)

if __name__ == '__main__': main()
