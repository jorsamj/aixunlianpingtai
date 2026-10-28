"""Explicit external Y'CbCr preprocessing contract and standalone NumPy reference.

No model mutation, platform imports, SDK calls, or claim of board installation.
Raw inputs are tightly packed 8-bit NV12, I420, or planar Y/U/V YUV444.
Chroma upsampling repeats samples (nearest neighbour, no siting correction).
Float64 conversion clips to [0,255], then rounds half upwards to uint8.
"""
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import uuid



PRESETS = ('bt601_limited', 'bt601_full', 'bt709_limited', 'bt709_full')
INPUT_FORMATS = ('NV12', 'I420', 'YUV444')
CONTRACT_TARGETS = ('sophon', 'rockchip', 'ascend', 'tensorrt', 'onnx')
SOURCES = (
    'https://www.itu.int/dms_pubrec/itu-r/rec/bt/r-rec-bt.709-6-201506-i!!pdf-e.pdf',
    'https://doc.sophgo.com/bm1688_sdk-docs/v1.8/docs_latest_release/docs/bmcv/bmcv_demo/bmcv_api/bmcv_image_vpp_basic.html',
)


def csc_capabilities(target):
    """Platform delivery capability, NOT an assertion about an installed SDK."""
    target = str(target or '').strip().lower()
    supported = target in CONTRACT_TARGETS
    return {'target': target, 'capability': 'contract_only' if supported else 'unsupported',
            'presets': list(PRESETS) if supported else [],
            'input_formats': list(INPUT_FORMATS) if supported else [],
            'modes': ['none', 'device_default'], 'embedded_supported': False,
            'execution_location': 'external_preprocessing' if supported else 'unknown',
            'device_observed': 'unknown', 'board_verification': 'NOT VERIFIED'}


def normalize_csc_request(csc):
    """Normalize requested intent; missing metadata stays legacy_unknown."""
    if csc is None:
        return {'preset': 'legacy_unknown'}
    if not isinstance(csc, Mapping):
        raise ValueError('csc must be an object')
    preset = str(csc.get('preset') or '').strip().lower()
    if preset not in (*PRESETS, 'none', 'device_default'):
        raise ValueError('unsupported CSC preset')
    result = {'preset': preset}
    for field in ('require_embedded', 'model_only', 'deployment_contract_acknowledged'):
        if field in csc:
            if not isinstance(csc[field], bool):
                raise ValueError(field + ' must be boolean')
            result[field] = csc[field]
    if csc.get('input_format') is not None:
        result['input_format'] = str(csc['input_format']).strip().upper()
    return result


def _coefficients(preset):
    if preset not in PRESETS:
        raise ValueError('reference decoding requires an explicit CSC preset')
    kr, kb = (0.299, 0.114) if preset.startswith('bt601_') else (0.2126, 0.0722)
    kg = 1.0 - kr - kb
    limited = preset.endswith('_limited')
    return {'kr': kr, 'kb': kb, 'y_offset': 16 if limited else 0,
            'y_divisor': 219 if limited else 255, 'chroma_offset': 128,
            'chroma_divisor': 224 if limited else 255,
            'normalized_y_cb_cr_to_rgb': [[1.0, 0.0, 2*(1-kr)],
                [1.0, -2*kb*(1-kb)/kg, -2*kr*(1-kr)/kg],
                [1.0, 2*(1-kb), 0.0]]}


def resolve_csc_params(params, target, *, input_color_order='RGB'):
    """Resolve params['csc'] to serializable immutable-in-intent evidence.

    Four presets require raw format and explicit external deployment acceptance.
    The RGB/BGR output order is supplied by the original color adapter owner.
    Legacy metadata and device defaults never imply a particular matrix/range.
    """
    if not isinstance(params, Mapping):
        raise ValueError('conversion params must be an object')
    request = normalize_csc_request(params.get('csc'))
    preset = request['preset']
    output_order = str(input_color_order).strip().upper()
    if output_order not in ('RGB', 'BGR'):
        raise ValueError('CSC output input_color_order must be RGB or BGR')
    capabilities = csc_capabilities(target)
    result = {'schema_version': 1, 'preset': preset, 'requested': dict(request),
              'target': capabilities['target'], 'applied': False,
              'execution_location': 'none' if preset == 'none' else 'unknown',
              'capability': 'no_adaptation' if preset == 'none' else 'unknown',
              'device_observed': 'unknown', 'board_verification': 'NOT VERIFIED',
              'weights_modified': False, 'output_color_order': output_order}
    if preset not in PRESETS:
        return result
    if capabilities['capability'] != 'contract_only':
        raise ValueError('CSC deployment contract is unsupported for this target adapter')
    if request.get('require_embedded') or request.get('model_only'):
        raise ValueError('embedded/model-only CSC is unsupported; external preprocessing is required')
    if request.get('input_format') not in INPUT_FORMATS:
        raise ValueError('explicit raw input_format NV12/I420/YUV444 is required')
    if request.get('deployment_contract_acknowledged') is not True:
        raise ValueError('explicit deployment_contract_acknowledged=true is required')
    result.update(capability='contract_only', execution_location='external_preprocessing',
                  input_format=request['input_format'], coefficients=_coefficients(preset),
                  sample_bits=8, input_layout='tightly_packed_planar_Y_U_V' if request['input_format'] != 'NV12' else 'tightly_packed_Y_interleaved_UV',
                  chroma_upsampling='nearest_repeat_no_siting_correction',
                  rounding='float64; clip [0,255]; floor(value+0.5)',
                  reference_only=True, sources=list(SOURCES))
    return result


def decode_yuv8(data, width, height, *, preset, input_format, output_color_order='RGB'):
    """Decode raw 8-bit Y'CbCr to a NEW HWC uint8 RGB/BGR array.

    No RGB-to-YUV inverse step, HSV manipulation, gamma/transfer conversion,
    resize or model normalization is performed. NV12/I420 require even sizes.
    YUV444 denotes planar Y then U then V, not interleaved YUV bytes.
    """
    import numpy as np  # Numerical engine is needed only when executing pixel decoding.
    coefficients = _coefficients(preset)
    fmt = str(input_format).strip().upper()
    order = str(output_color_order).strip().upper()
    if (isinstance(width, bool) or isinstance(height, bool) or
            not isinstance(width, (int, np.integer)) or not isinstance(height, (int, np.integer)) or width <= 0 or height <= 0):
        raise ValueError('raw width/height must be positive integers')
    if fmt not in INPUT_FORMATS or order not in ('RGB', 'BGR'):
        raise ValueError('unsupported raw layout or output color order')
    if fmt != 'YUV444' and (width % 2 or height % 2):
        raise ValueError('NV12/I420 require even width and height')
    if isinstance(data, (bytes, bytearray, memoryview)):
        raw = np.frombuffer(data, dtype=np.uint8)
    else:
        raw = np.asarray(data)
        if raw.dtype != np.uint8:
            raise ValueError('raw input must have uint8 dtype')
        raw = raw.reshape(-1)
    pixels = width * height
    expected = pixels * 3 if fmt == 'YUV444' else pixels * 3 // 2
    if raw.size != expected:
        raise ValueError('raw byte length does not match tightly packed input dimensions')
    y = raw[:pixels].reshape(height, width).astype(np.float64)
    if fmt == 'YUV444':
        u = raw[pixels:2*pixels].reshape(height, width)
        v = raw[2*pixels:].reshape(height, width)
    elif fmt == 'I420':
        u = raw[pixels:pixels+pixels//4].reshape(height//2, width//2)
        v = raw[pixels+pixels//4:].reshape(height//2, width//2)
    else:
        uv = raw[pixels:].reshape(height//2, width//2, 2)
        u, v = uv[..., 0], uv[..., 1]
    if fmt != 'YUV444':
        u = u.repeat(2, axis=0).repeat(2, axis=1)
        v = v.repeat(2, axis=0).repeat(2, axis=1)
    normalized = np.stack(((y-coefficients['y_offset'])/coefficients['y_divisor'],
        (u.astype(np.float64)-128)/coefficients['chroma_divisor'],
        (v.astype(np.float64)-128)/coefficients['chroma_divisor']), axis=-1)
    rgb = normalized @ np.asarray(coefficients['normalized_y_cb_cr_to_rgb'], dtype=np.float64).T
    output = np.floor(np.clip(rgb*255, 0, 255)+0.5).astype(np.uint8)
    return output if order == 'RGB' else output[..., ::-1].copy()


def write_csc_deployment_bundle(output_dir, contract, *, include_reference_sources=True):
    """Write auditable reference aid beside an artifact; never change the artifact.

    Manifest hashes cover the exact shipped source/readme bytes. The contract
    JSON does not hash itself. This does NOT install or invoke preprocessing.
    """
    if not isinstance(contract, Mapping):
        raise ValueError('resolved CSC contract is required')
    request = contract.get('requested')
    checked = resolve_csc_params({'csc': request} if contract.get('preset') != 'legacy_unknown' else {},
        contract.get('target'), input_color_order=contract.get('output_color_order', 'RGB'))
    if dict(contract) != checked:
        raise ValueError('deployment contract differs from canonical resolved CSC metadata')
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    readme = (
        '# CSC external preprocessing reference\n\n'
        'This aid is not installed in your device business application. No board behavior is verified.\n'
        'Four explicit presets require external raw YUV decoding before the existing model preprocessing.\n'
        'Do not apply CSC again to already decoded RGB/BGR. none performs no adaptation; device_default\n'
        'and legacy_unknown do not specify a matrix. Model files/weights are unchanged.\n\n'
        'Input: tightly packed 8-bit NV12 (Y then UV), I420 (Y,U,V), or planar YUV444 (Y,U,V).\n'
        'NV12/I420 use nearest-repeat chroma without siting correction. Padding/strides must be removed.\n'
        'Limited: Y=(byte-16)/219, C=(byte-128)/224. Full: Y=byte/255, C=(byte-128)/255.\n'
        'BT.601 Kr=.299 Kb=.114; BT.709 Kr=.2126 Kb=.0722. No transfer/gamma conversion.\n'
        'Float64 output is multiplied by 255, clipped to [0,255], rounded floor(x+.5).\n'
        'Reference may differ from SDK fixed-point rounding, chroma siting and resizing.\n\n'
        'Requires NumPy. Example (output .npy is HWC uint8, not a model tensor):\n'
        'python csc_reference.py input.yuv output.npy --width 640 --height 480 '
        '--preset bt709_limited --input-format NV12 --output-color-order RGB\n'
        'Use deployment contract output_color_order to match the original model input color adapter.\n'
    ).encode('utf-8')
    files = {'csc_reference.py': Path(__file__).read_text(encoding='utf-8').replace('\r\n','\n').encode('utf-8'), 'CSC_DEPLOYMENT_README.md': readme}
    manifest = {'schema_version': 1, 'reference_archive':'csc_deployment_reference.zip', 'contract': dict(contract),
        'files': [{'path': name, 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                  for name, content in files.items()]}
    files['csc_deployment_contract.json'] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')
    for name, content in files.items():
        if not include_reference_sources and name in {'csc_reference.py','CSC_DEPLOYMENT_README.md'}:
            continue
        destination = root/name
        temporary = root/('.'+name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    # Deliver executable reference source through the existing registered ZIP
    # download contract; do not broaden public business-file suffix permissions.
    import zipfile
    archive = root/'csc_deployment_reference.zip'
    temporary = root/('.csc-reference-'+uuid.uuid4().hex+'.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as bundle:
            for name, content in files.items():
                info=zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
                info.external_attr=0o644 << 16
                bundle.writestr(info, content)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


if __name__ == '__main__':
    import numpy as np
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--preset', choices=PRESETS, required=True)
    parser.add_argument('--input-format', choices=INPUT_FORMATS, required=True)
    parser.add_argument('--output-color-order', choices=('RGB', 'BGR'), default='RGB')
    args = parser.parse_args()
    np.save(args.output, decode_yuv8(Path(args.input).read_bytes(), args.width, args.height,
        preset=args.preset, input_format=args.input_format, output_color_order=args.output_color_order))
