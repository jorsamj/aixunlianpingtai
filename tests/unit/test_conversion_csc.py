import importlib.util
import hashlib
import json

import numpy as np
import pytest

from platform_core.conversion_csc import (
    csc_capabilities, decode_yuv8, resolve_csc_params, write_csc_deployment_bundle,
)


@pytest.mark.parametrize('preset,expected', [
    ('bt601_limited', [255, 22, 21]),
    ('bt601_full', [255, 33, 33]),
    ('bt709_limited', [255, 46, 18]),
    ('bt709_full', [255, 55, 29]),
])
def test_four_fixed_raw_golden_vectors(preset, expected):
    source = np.array([100, 90, 240], dtype=np.uint8)
    original = source.copy()
    result = decode_yuv8(source, 1, 1, preset=preset, input_format='YUV444')
    assert result.tolist() == [[expected]]
    np.testing.assert_array_equal(source, original)
    low, high = (16, 235) if preset.endswith('limited') else (0, 255)
    assert decode_yuv8(bytes([low,128,128]),1,1,preset=preset,input_format='YUV444').tolist()==[[[0,0,0]]]
    assert decode_yuv8(bytes([high,128,128]),1,1,preset=preset,input_format='YUV444').tolist()==[[[255,255,255]]]


@pytest.mark.parametrize('fmt,data', [('NV12', [100]*4+[90,240]), ('I420', [100]*4+[90,240]), ('YUV444', [100]*4+[90]*4+[240]*4)])
def test_raw_planes_and_bgr_output(fmt, data):
    decoded = decode_yuv8(bytes(data), 2, 2, preset='bt709_full', input_format=fmt, output_color_order='BGR')
    assert decoded.tolist() == [[[29,55,255]]*2]*2


def request(**extra):
    return {'csc': {'preset':'bt709_limited','input_format':'NV12', 'deployment_contract_acknowledged':True, **extra}}


def test_contract_truth_and_legacy_defaults():
    assert resolve_csc_params({}, 'sophon')['preset'] == 'legacy_unknown'
    for preset in ('none', 'device_default'):
        contract=resolve_csc_params({'csc': {'preset':preset}}, 'unrecognized')
        assert contract['applied'] is False
        assert contract['device_observed'] == 'unknown'
    for target in ('sophon','rockchip','ascend','tensorrt','onnx'):
        contract=resolve_csc_params(request(), target, input_color_order='BGR')
        assert contract['capability']=='contract_only'
        assert contract['execution_location']=='external_preprocessing'
        assert contract['output_color_order']=='BGR'
        assert contract['applied'] is False
        assert contract['board_verification']=='NOT VERIFIED'
        assert csc_capabilities(target)['embedded_supported'] is False


@pytest.mark.parametrize('target,body', [('unknown',request()), ('onnx',request(input_format='RGB')), ('onnx',request(deployment_contract_acknowledged=False)), ('onnx',request(require_embedded=True)), ('onnx',request(model_only=True)), ('onnx',{'csc':{'preset':'mistyped'}})])
def test_reject_unsupported_or_unacknowledged_requests(target, body):
    with pytest.raises(ValueError):
        resolve_csc_params(body, target)


def test_reference_validates_raw_layout_and_does_not_guess_defaults():
    for kwargs, data in [({'preset':'device_default','input_format':'NV12'}, bytes(6)), ({'preset':'bt601_full','input_format':'NV12'}, bytes(5)), ({'preset':'bt601_full','input_format':'RGB'}, bytes(12))]:
        with pytest.raises(ValueError):
            decode_yuv8(data,2,2,**kwargs)
    with pytest.raises(ValueError):
        decode_yuv8(np.zeros(12,dtype=np.float32),2,2,preset='bt601_full',input_format='YUV444')


def test_bundle_ships_executable_standalone_reference_and_exact_manifest(tmp_path):
    contract=resolve_csc_params(request(), 'sophon')
    weights=tmp_path/'weights.bin'; weights.write_bytes(b'original weights')
    manifest=write_csc_deployment_bundle(tmp_path,contract)
    assert weights.read_bytes()==b'original weights'
    saved=json.loads((tmp_path/'csc_deployment_contract.json').read_text(encoding='utf-8'))
    assert saved['contract']==contract
    assert saved['files']==manifest['files']
    for entry in manifest['files']:
        content=(tmp_path/entry['path']).read_bytes()
        assert len(content)==entry['size_bytes']
        assert hashlib.sha256(content).hexdigest()==entry['sha256']
    spec=importlib.util.spec_from_file_location('shipped_csc',tmp_path/'csc_reference.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.decode_yuv8(bytes([100,90,240]),1,1,preset='bt601_full',input_format='YUV444').tolist()==[[[255,33,33]]]


def test_reference_package_uses_existing_safe_zip_contract(tmp_path):
    import zipfile
    contract=resolve_csc_params({'csc':{'preset':'bt709_full','input_format':'NV12','deployment_contract_acknowledged':True}},'onnx')
    write_csc_deployment_bundle(tmp_path,contract)
    original=(tmp_path/'csc_deployment_reference.zip').read_bytes()
    write_csc_deployment_bundle(tmp_path,contract)
    assert (tmp_path/'csc_deployment_reference.zip').read_bytes()==original
    with zipfile.ZipFile(tmp_path/'csc_deployment_reference.zip') as archive:
        assert set(archive.namelist())=={'csc_reference.py','CSC_DEPLOYMENT_README.md','csc_deployment_contract.json'}
        assert json.loads(archive.read('csc_deployment_contract.json'))['contract']==contract


def test_sophon_csc_output_follows_existing_canonical_bgr_preprocessing():
    from platform_core.conversion import validate_target
    params={'chip':'bm1688','precision':'fp16','input_height':32,'input_width':32,
        'preprocessing':{'pixel_format':'bgr'},
        'csc':{'preset':'bt601_full','input_format':'NV12','deployment_contract_acknowledged':True}}
    resolved=validate_target('sophon',params)
    assert resolved['preprocessing']['pixel_format']=='bgr'
    assert resolved['csc_contract']['output_color_order']=='BGR'
