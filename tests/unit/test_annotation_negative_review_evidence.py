import pytest
from platform_core.annotation_repository import AnnotationRepository, AnnotationConflictError

def test_review_evidence_is_bound_to_atomic_gt_version_and_idempotent(tmp_path):
 repo=AnnotationRepository(tmp_path)
 box={'id':'p','label':'person','x1':0,'y1':0,'x2':20,'y2':20}
 first=repo.upsert('a',[box],'annotated',annotation_scope=['person'])
 evidence={'actor_id':'reviewer','reviewed_label_codes':['vest'],'source_content_sha256':'a'*64}
 saved=repo.upsert('a',[box],'annotated',annotation_scope=['person','vest'],expected_version=first['version'],review_evidence=evidence)
 event=repo.negative_review_evidence('a',first['version'],'reviewer',['vest'],'a'*64)
 assert event['annotation_version']==saved['version']
 assert event['annotation_digest']==saved['content_digest']
 assert event['reviewed_at'] and saved['boxes']==first['boxes']
 with pytest.raises(AnnotationConflictError):
  repo.upsert('a',[],'confirmed_empty',annotation_scope=['vest'],expected_version=first['version'],review_evidence=evidence)
 assert repo.get('a')==saved
 assert repo.negative_review_evidence('a',saved['version'],'reviewer',['vest'],'a'*64) is None


def test_repository_writers_cannot_carry_batch_absence_across_box_edits(tmp_path):
 repo=AnnotationRepository(tmp_path);box={'label':'person','x1':0,'y1':0,'x2':20,'y2':20}
 first=repo.upsert('a',[box],'annotated',annotation_scope=['person'])
 reviewed=repo.upsert('a',[box],'annotated',annotation_scope=['person','vest'],expected_version=first['version'],review_evidence={'actor_id':'r','reviewed_label_codes':['vest']})
 # Unrelated scope addition does not change object truth, but must not hide history.
 scope=repo.upsert('a',[box],'annotated',annotation_scope=['person','vest','car'],expected_version=reviewed['version'])
 edited=repo.upsert('a',[{**box,'x2':18}],'annotated',annotation_scope=scope['annotation_scope'])
 assert edited['annotation_scope']==['car','person']
 explicit=repo.upsert('a',[{**box,'x2':17}],'annotated',annotation_scope=['person','vest'],reviewed_label_codes=['vest'])
 assert explicit['annotation_scope']==['person','vest']
