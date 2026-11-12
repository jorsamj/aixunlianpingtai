"""Inference reservations inside the existing task repository, never a second queue.

Permits cover network calls, not task leases: cancelling or reclaiming a Worker
must not make an already dispatched upstream request disappear from capacity.
Only the calling thread releases its permit; crash recovery uses a conservative
request budget. All database transactions are short and contain no network I/O.
"""
from contextlib import closing
import math
import time
import uuid

from .models import utc_now
from .sqlite_busy import retry_busy


def ensure_inference_runtime_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS inference_permits (
            permit_id TEXT NOT NULL, domain TEXT NOT NULL, task_id TEXT NOT NULL,
            execution_generation INTEGER NOT NULL, capacity INTEGER NOT NULL,
            expires_at REAL NOT NULL, PRIMARY KEY(permit_id,domain)
        );
        CREATE INDEX IF NOT EXISTS idx_inference_domain_expiry
            ON inference_permits(domain, expires_at);
        CREATE TABLE IF NOT EXISTS inference_domain_state (
            domain TEXT PRIMARY KEY, next_start REAL NOT NULL DEFAULT 0,
            cooldown_until REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
            rate_interval REAL NOT NULL DEFAULT 0, rate_valid_until REAL NOT NULL DEFAULT 0
        );
    ''')


class InferenceResourceMethods:
    @retry_busy
    def acquire_inference_permit(self, *, task_id, lease_token, execution_generation,
                                 domain, capacity=1, hold_seconds=900,
                                 requests_per_minute=0, shared_domain=None, rate_valid_until=None):
        capacity = max(1, min(8, int(capacity)))
        hold_seconds = max(60, min(3600, float(hold_seconds)))
        rate = max(0, min(60000, float(requests_per_minute or 0)))
        if not domain or len(str(domain)) > 200:
            raise ValueError('invalid inference quota domain')
        domains = sorted({str(domain), *([str(shared_domain)] if shared_domain else [])})
        if any(len(value) > 200 for value in domains):
            raise ValueError('invalid shared inference quota domain')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            owner = db.execute('''SELECT 1 FROM tasks WHERE task_id=? AND lease_token=?
                AND attempt=? AND status='RUNNING' AND lease_expires_at>?''',
                (str(task_id), str(lease_token), int(execution_generation), utc_now())).fetchone()
            if owner is None:
                raise PermissionError('inference dispatch is fenced or cancelled')
            db.execute('DELETE FROM inference_permits WHERE expires_at<=?', (now,))
            wait = 0
            rates = {}
            for scope in domains:
                state = db.execute('SELECT * FROM inference_domain_state WHERE domain=?', (scope,)).fetchone()
                interval = max(60/rate if rate else 0,
                               float(state['rate_interval']) if state and float(state['rate_valid_until']) > now else 0)
                validity = max(float(rate_valid_until or now+900) if rate else 0,
                               float(state['rate_valid_until']) if state and float(state['rate_valid_until']) > now else 0)
                rates[scope] = (interval, validity)
                wait = max(wait, max(float(state['next_start']), float(state['cooldown_until'])) - now) if state else wait
                rows = db.execute('SELECT capacity,expires_at FROM inference_permits WHERE domain=?', (scope,)).fetchall()
                effective_capacity = min([capacity, *[int(row['capacity']) for row in rows]])
                if len(rows) >= effective_capacity:
                    wait = max(wait, min(0.25, max(0.01, min(float(row['expires_at']) for row in rows) - now)))
            if wait:
                db.commit()
                return {'permit_id': None, 'retry_after_seconds': wait}
            token = uuid.uuid4().hex
            for scope in domains:
                db.execute('INSERT INTO inference_permits VALUES (?,?,?,?,?,?)',
                           (token, scope, str(task_id), int(execution_generation), capacity, now + hold_seconds))
                interval, validity = rates[scope]
                db.execute('''INSERT INTO inference_domain_state(domain,next_start,rate_interval,rate_valid_until)
                    VALUES (?,?,?,?) ON CONFLICT(domain) DO UPDATE SET next_start=excluded.next_start,
                    rate_interval=excluded.rate_interval,rate_valid_until=excluded.rate_valid_until''',
                    (scope, now + interval, interval, validity))
            db.commit()
        return {'permit_id': token, 'retry_after_seconds': 0}

    @retry_busy
    def release_inference_permit(self, permit_id):
        # A random unguessable receipt identifies only this specific HTTP call.
        with closing(self._connect()) as db:
            db.execute('DELETE FROM inference_permits WHERE permit_id=?', (str(permit_id),))

    @retry_busy
    def renew_inference_permit(self, permit_id, *, hold_seconds=900):
        # This is an in-flight call receipt, independent of a cancelled task's
        # right to dispatch NEW calls. Never release capacity merely on cancel.
        with closing(self._connect()) as db:
            changed = db.execute('UPDATE inference_permits SET expires_at=MAX(expires_at,?) WHERE permit_id=?',
                                 (time.time() + max(60, min(3600, float(hold_seconds))), str(permit_id))).rowcount
            if changed < 1:
                raise PermissionError('inference reservation expired')

    @retry_busy
    def defer_inference_domain(self, domain, seconds, *, failure=False):
        delay = float(seconds)
        if not math.isfinite(delay):
            delay = 86400
        delay = max(0, min(86400, delay))
        with closing(self._connect()) as db:
            db.execute('''INSERT INTO inference_domain_state(domain,cooldown_until,failures)
                VALUES (?,?,?) ON CONFLICT(domain) DO UPDATE SET
                cooldown_until=MAX(cooldown_until,excluded.cooldown_until,
                    CASE WHEN ? AND failures>=2 THEN ? ELSE 0 END),
                failures=CASE WHEN ? THEN failures+1 ELSE 0 END''',
                (str(domain), time.time() + delay, int(failure), int(failure), time.time()+30, int(failure)))

    def inference_domain_failures(self, domain):
        with closing(self._connect()) as db:
            row = db.execute('SELECT failures FROM inference_domain_state WHERE domain=?', (str(domain),)).fetchone()
            return int(row['failures']) if row else 0
