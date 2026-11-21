from platform_core.annotation_comparison import compare_boxes

def box(label='person', x=0):
    return dict(label=label,x1=x,y1=0,x2=x+10,y2=10)

def test_one_to_one_and_incomplete_baseline():
    r=compare_boxes([box()], [box(),box()], complete=True)
    assert (r['tp'],r['fp'],r['fn'])==(1,1,0)
    assert r['duplicates']==[1]
    assert compare_boxes([], [box()], complete=False)['metrics'] is None

def test_label_conflict_and_spatial_evidence():
    r=compare_boxes([box()], [box('other')], complete=True)
    assert r['tp']==0 and r['label_conflicts'][0]['iou']==1
    r=compare_boxes([box(x=20),box(x=70)], [box(x=18),box(x=72)], complete=True, image_width=100)
    assert [m['dx'] for m in r['matches']]==[-2,2]
    assert r['metrics']['precision']==1
    assert r['diagnosis']['spatial']['both_sides_outward'] is True
    assert r['diagnosis']['spatial']['cause']=='not_determined'
