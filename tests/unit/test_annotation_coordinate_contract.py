import json
import pytest
from platform_core.auto_label import parse_candidate_response, coordinate_contract
from platform_core.annotation_runtime import freeze_model_config, build_annotation_prompt


@pytest.mark.parametrize('size', [(1920,1080),(1080,1920),(640,480)])
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


def test_exif_and_stored_geometry_fail_before_provider(tmp_path):
    from PIL import Image
    from platform_core.annotation_task_service import annotate_one
    class Provider:
        def annotate(self, **kwargs):
            raise AssertionError('geometry must be checked before inference')
    path=tmp_path/'oriented.jpg'
    source=Image.new('RGB',(20,10))
    exif=source.getexif()
    exif[274]=6
    source.save(path,exif=exif)
    request={'_provider':Provider(),'_provider_config':{}}
    with pytest.raises(ValueError,match='EXIF'):
        annotate_one(request,{'path':str(path),'width':20,'height':10})
    source.save(path)
    with pytest.raises(ValueError,match='dimensions'):
        annotate_one(request,{'path':str(path),'width':10,'height':20})
