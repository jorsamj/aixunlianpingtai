"""Disposable task findings/review receipts, never a material/GT/task owner."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from filelock import FileLock

from ..annotation_repository import AnnotationRepository
from ..material_repository import MaterialRepository
from ..task_runtime.models import utc_now
from .service import reject


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _connect(path, *, write=False):
    db = sqlite3.connect(str(path) if write else Path(path).resolve().as_uri()+"?mode=ro", uri=not write, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def build_results(path, inputs, outcome, *, generation):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp-"+uuid.uuid4().hex)
    facts = {row["image_id"]: {key: value for key,value in row.items() if key != "path"} for row in inputs}
    try:
        with closing(_connect(temporary, write=True)) as db:
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
                CREATE TABLE inputs(image_id TEXT PRIMARY KEY,facts_json TEXT NOT NULL);
                CREATE TABLE findings(issue_id TEXT PRIMARY KEY,image_id TEXT NOT NULL,related_image_id TEXT,issue_type TEXT NOT NULL,evidence_json TEXT NOT NULL);
                CREATE INDEX ix_findings_type ON findings(issue_type,issue_id);
                CREATE TABLE reviews(issue_id TEXT PRIMARY KEY,review_json TEXT NOT NULL);
            """)
            db.execute("INSERT INTO metadata VALUES ('generation',?)", (_json(generation),))
            db.execute("INSERT INTO metadata VALUES ('checks',?)", (_json(outcome.get("checks", {})),))
            db.executemany("INSERT INTO inputs VALUES (?,?)", ((key,_json(value)) for key,value in facts.items()))
            findings = []
            for pair in outcome.get("similar_pairs", []):
                first, second = pair["image_ids"]
                same_sha = facts[first].get("content_sha256") == facts[second].get("content_sha256")
                issue_type = "same_sha_reference" if same_sha else "visual_similarity"
                leakage=outcome.get('checks',{}).get('leakage',{})
                if (leakage.get('status')=='completed' and facts[first].get('frozen_split') and facts[second].get('frozen_split')
                        and facts[first]['frozen_split']!=facts[second]['frozen_split']):
                    issue_type='cross_split_leakage'
                findings.append((issue_type, first, second, {**pair, "sha_relation": "same_sha" if same_sha else "different_sha"}))
            findings.extend(("suspected_annotation", row["image_id"], None, row) for row in outcome.get("annotation_candidates", []))
            findings.extend(("unverified", row["image_id"], None, row) for row in outcome.get("failures", []))
            for kind, image_id, related_id, evidence in findings:
                issue_id = _hash([kind,image_id,related_id])[:32]
                db.execute("INSERT OR REPLACE INTO findings VALUES (?,?,?,?,?)", (issue_id,image_id,related_id,kind,_json(evidence)))
            db.commit()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _current(project, image_ids):
    materials = MaterialRepository.open_readonly(project)
    try:
        annotations = AnnotationRepository.open_readonly(project)
    except (sqlite3.Error, ValueError):
        annotations = None
    output = {}
    ids = sorted(set(image_ids))
    for start in range(0,len(ids),500):
        batch = ids[start:start+500]
        images = {row["id"]: row for row in materials.get_many(batch)}
        gt = annotations.get_many(batch) if annotations else {}
        for image_id in batch:
            record = gt.get(image_id)
            image = images.get(image_id)
            output[image_id] = {"content_sha256": image.get("content_sha256") if image else None,
                "annotation_digest": annotations.record_digest(record) if record is not None else None,
                "annotation_version": record.get("version") if record is not None else None}
    return output


def _decorate(row, db, current):
    value = dict(row)
    ids = [value["image_id"]] + ([value["related_image_id"]] if value["related_image_id"] else [])
    sources = {r["image_id"]: json.loads(r["facts_json"]) for r in db.execute(
        "SELECT * FROM inputs WHERE image_id IN ("+",".join("?" for _ in ids)+")", ids)}
    value["inputs"] = sources
    value["evidence"] = json.loads(value.pop("evidence_json"))
    value["current_identity"] = {key:current.get(key) for key in ids}
    value["review_token"] = _hash([value["issue_id"],value["current_identity"]])
    value["stale"] = any(not current.get(key) or any(sources.get(key,{}).get(field) != current[key].get(field)
        for field in ("content_sha256","annotation_digest","annotation_version")) for key in ids)
    review = db.execute("SELECT review_json FROM reviews WHERE issue_id=?", (value["issue_id"],)).fetchone()
    value["review"] = json.loads(review[0]) if review else None
    value["review_valid"] = bool(review and value["review"].get("review_token") == value["review_token"])
    value["requires_confirmation"] = not value["review_valid"] or value["review"]["verdict"] == "unknown"
    return value


def findings_page(path, project, *, offset=0, limit=25, issue_type="", issue_id=""):
    if isinstance(offset,bool) or isinstance(limit,bool) or offset < 0 or not 1 <= limit <= 50:
        reject("SMART_AUDIT_PAGE_INVALID", "每页必须为1–50条，offset必须非负", 422)
    clauses, params = [], []
    if issue_type:
        clauses.append("issue_type=?"); params.append(str(issue_type))
    if issue_id:
        clauses.append("issue_id=?"); params.append(str(issue_id))
    where = " WHERE "+" AND ".join(clauses) if clauses else ""
    with closing(_connect(path)) as db:
        total = db.execute("SELECT COUNT(*) FROM findings"+where,params).fetchone()[0]
        rows = db.execute("SELECT * FROM findings"+where+" ORDER BY issue_id LIMIT ? OFFSET ?", (*params,limit,offset)).fetchall()
        ids = {row[key] for row in rows for key in ("image_id","related_image_id") if row[key]}
        reviewed=db.execute('SELECT f.issue_id,f.image_id,f.related_image_id,f.issue_type,r.review_json FROM findings f JOIN reviews r ON r.issue_id=f.issue_id').fetchall()
        ids.update(row[key] for row in reviewed for key in ('image_id','related_image_id') if row[key])
        current = _current(project,ids) if ids else {}
        counts = dict(db.execute("SELECT issue_type,COUNT(*) FROM findings GROUP BY issue_type"))
        review_counts={'confirmed_issue':0,'no_issue':0,'corrected':0,'unknown':0,'stale':0}
        by_type={}
        for row in reviewed:
            related=[row['image_id']]+([row['related_image_id']] if row['related_image_id'] else [])
            token=_hash([row['issue_id'],{key:current.get(key) for key in related}])
            receipt=json.loads(row['review_json'])
            key=receipt['verdict'] if receipt.get('review_token')==token else 'stale'
            review_counts[key]+=1
            by_type.setdefault(row['issue_type'],{k:0 for k in review_counts})[key]+=1
        items=[_decorate(row,db,current) for row in rows]
        if not issue_id:
            for item in items:
                item['inputs']={key:{k:v for k,v in facts.items() if k not in {'gt_boxes','pred_boxes','prediction_evidence'}}
                    for key,facts in item['inputs'].items()}
        review_counts['pending']=sum(counts.values())-sum(review_counts[key] for key in ('confirmed_issue','no_issue','corrected'))
        return {"items":items,"total":total,"offset":offset,"limit":limit,'review_counts':review_counts,'review_counts_by_type':by_type,
            "counts":counts,"checks":json.loads(db.execute("SELECT value_json FROM metadata WHERE key='checks'").fetchone()[0]),
            "generation":json.loads(db.execute("SELECT value_json FROM metadata WHERE key='generation'").fetchone()[0]),
            "read_only_sources":True}


def review_finding(path, project, issue_id, payload, *, actor_id):
    if not isinstance(payload,dict) or set(payload)-{"verdict","expected_review_token","note"}:
        reject("SMART_AUDIT_REVIEW_INVALID", "审核字段无效", 422)
    verdict = payload.get("verdict")
    if verdict not in {"confirmed_issue","no_issue","corrected","unknown"} or len(str(payload.get("note", ""))) > 1000:
        reject("SMART_AUDIT_REVIEW_INVALID", "审核结论或备注无效", 422)
    with FileLock(str(path)+".review.lock",timeout=5):
        page = findings_page(path,project,issue_id=issue_id,limit=1)
        if not page["items"]:
            reject("SMART_AUDIT_FINDING_NOT_FOUND", "分析候选不存在",404)
        item = page["items"][0]
        if payload.get("expected_review_token") != item["review_token"]:
            reject("SMART_AUDIT_EVIDENCE_CHANGED", "原图或GT已变化，请重新核验")
        if any(not current or current["content_sha256"] != item["inputs"].get(key,{}).get("content_sha256")
                for key,current in item["current_identity"].items()):
            reject("SMART_AUDIT_EVIDENCE_CHANGED", "原图已变化或不存在，请重新分析")
        if verdict == "corrected":
            original = item["inputs"][item["image_id"]]
            current = item["current_identity"][item["image_id"]]
            if (not current.get("annotation_digest") or current["annotation_digest"] == original.get("annotation_digest")
                    or int(current.get("annotation_version") or 0) <= int(original.get("annotation_version") or 0)):
                reject("SMART_AUDIT_GT_SAVE_REQUIRED", "尚未核验到原正式接口保存的新GT版本，不能标记已修正")
        elif item["stale"] and verdict != "unknown":
            reject("SMART_AUDIT_EVIDENCE_CHANGED", "GT已变化，请重新分析或通过原标注接口保存后确认修正")
        review = {"verdict":verdict,"note":str(payload.get("note") or ""),"actor_id":str(actor_id),
                  "review_token":item["review_token"],"reviewed_at":utc_now()}
        with closing(_connect(path,write=True)) as db:
            db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?)",(issue_id,_json(review)))
            db.commit()
    return findings_page(path,project,issue_id=issue_id,limit=1)["items"][0]
