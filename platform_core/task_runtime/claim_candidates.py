"""Bounded read-only scans; cursor is advisory Worker-local fairness, never Task truth."""
import json

PAGE_SIZE=64
MAX_CANDIDATES=512
MAX_PREPARED=32
COLUMNS=('task_id','project_id','kind','status','payload_ref','resource_key','required_capabilities',
         'priority','queue_rank','created_at','attempt','stage','accepted','retry_of')
SEMANTIC_FIELDS=COLUMNS
ORDER='candidate.priority ASC,candidate.queue_rank DESC,candidate.created_at ASC,candidate.task_id ASC'
PROJECTION=','.join('candidate.'+field for field in COLUMNS)


def key(row):
    return (row['priority'],row['queue_rank'],row['created_at'],row['task_id'])


def sorted_key(row):
    p,q,c,t=key(row)
    return p,-q,c,t


def page(database, limit, cursor=None, *, kinds=()):
    # Disjoint lexicographic ranges preserve mixed ASC/DESC order and let
    # SQLite seek on the full aligned index, rather than filter an OR prefix.
    if cursor is None:
        ranges=[('',())]
    else:
        p,q,c,t=cursor
        ranges=[
            (' AND candidate.priority=? AND candidate.queue_rank=? AND candidate.created_at=? AND candidate.task_id>?',(p,q,c,t)),
            (' AND candidate.priority=? AND candidate.queue_rank=? AND candidate.created_at>?',(p,q,c)),
            (' AND candidate.priority=? AND candidate.queue_rank<?',(p,q)),
            (' AND candidate.priority>?',(p,)),
        ]
    kind_clause=(' AND candidate.kind IN ('+','.join('?' for _ in kinds)+')') if kinds else ''
    result=[]
    for condition,params in ranges:
        remaining=limit-len(result)
        if remaining<=0:
            break
        result.extend(database.execute(f"SELECT {PROJECTION} FROM tasks candidate WHERE candidate.status='QUEUED'{kind_clause}{condition} ORDER BY {ORDER} LIMIT ?",
            (*kinds,*params,remaining)).fetchall())
    return result


def prepare_candidates(database,kinds,available,prepare,cursor,now,budget):
    budget=max(PAGE_SIZE,min(MAX_CANDIDATES,int(budget)))
    # Read possible immediate recovery candidates too, without mutating them.
    # Final recovery either makes them QUEUED or conservatively keeps their owner.
    kind_clause=' AND candidate.kind IN ('+','.join('?' for _ in kinds)+')'
    expired=database.execute(f"SELECT {PROJECTION} FROM tasks candidate WHERE candidate.status='RUNNING' AND candidate.lease_expires_at<=?{kind_clause} AND (candidate.worker_id IS NULL OR candidate.worker_id NOT LIKE 'agent:%') ORDER BY {ORDER} LIMIT ?",
        (now,*kinds,min(32,budget//4))).fetchall()
    remaining=budget-len(expired)
    prepared=[]
    seen=set()
    def consume(row):
        if row['task_id'] in seen:
            return False
        seen.add(row['task_id'])
        if row['kind'] not in kinds or not set(json.loads(row['required_capabilities'] or '[]'))<=available:
            return False
        candidate=dict(row)
        if candidate['status']=='RUNNING':
            candidate['status']='QUEUED'
            candidate['stage']=('indexing_queued' if candidate['kind']=='MATERIAL_IMPORT' and candidate['accepted']==1
                and candidate['stage'] in {'indexing','lease_expired_process_alive','recovery_blocked_process_inspection','recovery_blocked_remote_agent_unverified'} else 'recovered')
        value=prepare(candidate) if callable(prepare) else None
        prepared.append((candidate,value))
        return True
    for row in expired:
        consume(row)
        if len(prepared)>=8:
            break
    head=page(database,min(PAGE_SIZE,max(1,remaining//2)),kinds=kinds)
    remaining-=len(head)
    head_end=None
    quota=len(prepared)+(MAX_PREPARED-len(prepared))//2
    for row in head:
        head_end=key(row)
        consume(row)
        if len(prepared)>=quota:
            break
    rotation=cursor if cursor is not None else head_end
    wrapped=False
    while remaining>0 and len(prepared)<MAX_PREPARED and head:
        requested=min(PAGE_SIZE,remaining)
        rows=page(database,requested,rotation,kinds=kinds)
        if not rows:
            if wrapped:
                rotation=None
                break
            wrapped=True
            rotation=None
            continue
        remaining-=len(rows)
        for row in rows:
            rotation=key(row)
            consume(row)
            if len(prepared)>=MAX_PREPARED:
                break  # Never advance past unread/unprepared rows in this page.
        if len(rows)<requested and len(prepared)<MAX_PREPARED:
            if wrapped:
                rotation=None
                break
            wrapped=True
            rotation=None
    prepared.sort(key=lambda item:sorted_key(item[0]))
    return prepared,rotation
