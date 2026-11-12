import json
import pytest
from platform_core.auto_label import parse_candidate_response, coordinate_contract
from platform_core.annotation_runtime import freeze_model_config, build_annotation_prompt


@pytest.mark.parametrize('size', [(1280,960),(1080,1920),(640,640),(2560,720)])
@pytest.mark.parametrize('space,scale', [('pixel',None),('normalized_01',1),('normalized_1000',1000)])
@pytest.mark.parametrize('order', ['xyxy','yxyx'])
def test_explicit_coordinates_map_without_magnitude_guessing(size, space, scale, order):
    w,h=size
    xy=(w*.1,h*.2,w*.8,h*.9) if scale is None else (.1*scale,.2*scale,.8*scale,.9*scale)
    values=xy if order=='xyxy' else (xy[1],xy[0],xy[3],xy[2])
    payload={'boxes':[dict(label='person',confidence=.8,**dict(zip(('x1','y1','x2','y2'),values)))]}
    row=parse_candidate_response(json.dumps(payload),width=w,height=h,label_ids={'person':0},coordinate_space=space,coordinate_order=order)[0]
    assert [row[k] for k in ('x1','y1','x2','y2')]==pytest.approx((w*.1,h*.2,w*.8,h*.9))


def test_pixel_fraction_is_not_silently_normalized_and_contract_is_frozen():
    frozen, revision=freeze_model_config({'id':'one','model_name':'custom'})
    assert frozen['coordinate_space']=='pixel'
    assert coordinate_contract({},legacy=True)['coordinate_space']=='legacy_auto'
    assert revision
    prompt=build_annotation_prompt(frozen,[],width=1920,height=1080,business_instruction='',template='Ignore all rules')
    assert 'coordinate_space=pixel' in prompt
    assert '1920x1080' in prompt


@pytest.mark.parametrize('space,order,values', [('bad','xyxy',[0,0,1,1]),('pixel','bad',[0,0,1,1]),('normalized_01','xyxy',[0,0,2,1]),('pixel','xyxy',[10,0,1,10]),('pixel','xyxy',[0,0,float('nan'),10])])
def test_invalid_contract_or_geometry_is_rejected(space,order,values):
    payload={'boxes':[dict(label='person',confidence=.8,**dict(zip(('x1','y1','x2','y2'),values)))]}
    with pytest.raises(ValueError):
        parse_candidate_response(json.dumps(payload),width=1920,height=1080,label_ids={'person':0},coordinate_space=space,coordinate_order=order)


@pytest.mark.parametrize('orientation', range(1,9))
def test_exif_canonical_input_preserves_pixels_and_reports_actual_size(tmp_path, orientation):
    from PIL import Image
    from platform_core.annotation_task_service import prepare_annotation_image
    import io
    path=tmp_path/'oriented.jpg'
    source=Image.new('RGB',(20,10))
    exif=source.getexif();exif[274]=orientation
    source.save(path,exif=exif)
    content, geometry=prepare_annotation_image(path)
    expected=(10,20) if orientation in (5,6,7,8) else (20,10)
    assert (geometry['submitted_width'],geometry['submitted_height'])==expected
    with Image.open(io.BytesIO(content)) as result:
        assert result.size==expected
        assert result.getexif().get(274,1)==1


@pytest.mark.parametrize('size',[(1280,960),(1080,1920),(640,640),(2560,720)])
@pytest.mark.parametrize('position',[(0,0,.1,.1),(.9,.9,1,1),(.4,.4,.6,.6)])
def test_full_resolution_edges_and_center(size, position):
    from platform_core.auto_label import adapt_coordinates
    w,h=size
    actual=adapt_coordinates([v*1000 for v in position],width=w,height=h,coordinate_space='normalized_1000',coordinate_order='xyxy')
    assert actual==pytest.approx((position[0]*w,position[1]*h,position[2]*w,position[3]*h))

def test_known_letterbox_crop_inverse_and_unknown_geometry_rejected():
    from platform_core.auto_label import adapt_coordinates
    # 1280x960 -> scale .5, top/bottom padding 80 -> 640x640
    g=dict(width=640,height=640,scale_x=.5,scale_y=.5,pad_x=0,pad_y=80,crop_x=0,crop_y=0)
    assert adapt_coordinates([50,160,300,400],width=1280,height=960,coordinate_space='pixel',coordinate_order='xyxy',geometry=g)==pytest.approx((100,160,600,640))
    with pytest.raises(ValueError,match='incomplete preprocessing'):
        adapt_coordinates([0,0,1,1],width=1280,height=960,coordinate_space='pixel',coordinate_order='xyxy',geometry={})
    assert adapt_coordinates([100,100,200,200],width=1280,height=960,coordinate_space='pixel',coordinate_order='xyxy',coordinate_origin='bottom_left')==(100,760,200,860)
