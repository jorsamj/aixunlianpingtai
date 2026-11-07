import pytest
import app

@pytest.mark.parametrize('kind', ['RAW_UNANNOTATED', 'ANNOTATION_INVALID'])
def test_zip_report_raw_absence_is_normal_but_expected_annotation_errors_remain(kind):
    report={'imported_images':2,'annotated_images':0,'boxes':0,'unmatched_labels':2,'warnings':[]}
    app._v19_finalize_report_messages(report,scan_kind=kind)
    if kind=='RAW_UNANNOTATED':
        assert report['warnings']==[]
        assert report['result_kind']=='raw_unannotated'
    else:
        assert len(report['warnings'])==2
    assert report['boxes']==0


def test_raw_zip_keeps_real_integrity_errors_visible():
    report={'boxes':0,'missing_images':1,'skipped_images':2,'invalid_boxes':3,'warnings':['original']}
    app._v19_finalize_report_messages(report,scan_kind='RAW_UNANNOTATED')
    assert len(report['warnings'])==4
    assert report['warnings'][0]=='original'
