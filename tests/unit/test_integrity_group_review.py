import sqlite3
import pytest
from platform_core.material_batches import set_integrity_group_review

def test_group_review_is_scoped_cas_and_never_changes_issue_evidence(tmp_path):
 path=tmp_path/'audit.sqlite3'
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE issue_groups(group_key TEXT PRIMARY KEY, details_json TEXT)')
  db.execute("INSERT INTO issue_groups VALUES ('g','immutable')")
 result=set_integrity_group_review(path,['g'],status='skipped',reason='SOURCE_UNAVAILABLE',actor_id='reviewer',expected_revision=0)
 assert result['revision']==1
 with pytest.raises(ValueError,match='changed'):
  set_integrity_group_review(path,['g'],status='pending',reason='',actor_id='reviewer',expected_revision=0)
 with pytest.raises(ValueError):
  set_integrity_group_review(path,['missing'],status='skipped',reason='USER_DEFERRED',actor_id='reviewer',expected_revision=0)
 with sqlite3.connect(path) as db:
  assert db.execute('SELECT details_json FROM issue_groups').fetchone()[0]=='immutable'
  assert db.execute('SELECT status,reason,actor_id FROM group_review').fetchone()==('skipped','SOURCE_UNAVAILABLE','reviewer')
 set_integrity_group_review(path,['g'],status='pending',reason='',actor_id='reviewer',expected_revision=1)
