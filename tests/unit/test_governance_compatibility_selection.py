import pytest
from platform_core.training_compatibility import TrainingCompatibilityResult
import platform_core.training_compatibility as compatibility


def test_resolve_all_issue_types_is_exact_deduplicated_and_audit_free():
    result=TrainingCompatibilityResult({},tuple(
        {'image_id':f'i{x}','issue_type':kind,'filename':f'image{x}.jpg'}
        for x in range(1001) for kind in ('scope_missing','duplicate_annotation_conflict')
    ),4,8,{})
    resolved=compatibility.resolve_training_compatibility_selection(result,{
        'selection_action':'RESOLVE_SELECTION','expected_material_revision':4,'expected_annotation_revision':8,
        'selection':{'all_issues':True,'excluded_image_ids':['i0']}})
    assert resolved['selected_count']==1000
    assert len(resolved['matching_image_ids'])==len(set(resolved['matching_image_ids']))
    assert 'i0' not in resolved['matching_image_ids']
    assert resolved['summary']['issue_count']==2002


def test_resolve_filter_and_selected_ids_cannot_expand_current_issues():
    result=TrainingCompatibilityResult({},({'image_id':'i1','issue_type':'scope_missing','filename':'one'},),1,2,{})
    base={'expected_material_revision':1,'expected_annotation_revision':2}
    with pytest.raises(ValueError,match='SELECTION_CHANGED'):
        compatibility.resolve_training_compatibility_selection(result,{**base,'selection':{'image_ids':['foreign']}})
    with pytest.raises(ValueError,match='STALE'):
        compatibility.resolve_training_compatibility_selection(result,{**base,'expected_annotation_revision':1,'selection':{'all_issues':True}})
