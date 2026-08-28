from typing import Dict, List, Any

_PLUGINS: List[Dict[str, Any]] = [
    {
        'id':'onnx','name':'通用 ONNX','vendor':'Open','output':'.onnx',
        'source_formats':['.pt','.pth','.onnx','.pdparams','.pdmodel','.pdiparams'],
        'targets':['onnx'],'sdk':'Ultralytics / Paddle2ONNX','environment':'local_or_remote',
        'chips':[],'description':'统一中间模型层，供后续芯片插件继续编译。'
    },
    {
        'id':'rockchip','name':'瑞芯微 RKNN','vendor':'Rockchip','output':'.rknn',
        'source_formats':['.pt','.pth','.onnx','.pdparams','.pdmodel','.pdiparams'],
        'targets':['rockchip'],'sdk':'RKNN-Toolkit2','environment':'linux_x86_64_or_arm64',
        'chips':['rk3588','rk3576','rk3566','rk3568','rk3562','rv1103','rv1106','rv1103b','rv1106b','rv1126b','rk2118'],
        'description':'PC/转换节点使用 RKNN-Toolkit2 生成 .rknn；开发板 Runtime 仅负责运行，不是第二次转换。'
    },
    {
        'id':'ascend','name':'华为 Atlas / Ascend','vendor':'Huawei','output':'.om',
        'source_formats':['.pt','.pth','.onnx','.pdparams','.pdmodel','.pdiparams'],
        'targets':['ascend'],'sdk':'CANN Toolkit / ATC','environment':'linux',
        'chips':['Ascend310P3','Ascend310P1','Ascend310B','Ascend310B4','Ascend910B'],
        'description':'CANN ATC 将 ONNX 编译为目标 Ascend SoC 对应的 OM。'
    },
    {
        'id':'sophon','name':'算能 Sophon','vendor':'SOPHGO','output':'.bmodel',
        'source_formats':['.pt','.pth','.onnx','.pdparams','.pdmodel','.pdiparams'],
        'targets':['sophon'],'sdk':'TPU-MLIR','environment':'linux_or_docker',
        'chips':['bm1684x','bm1688','bm1690','cv186x'],
        'description':'TPU-MLIR 完成 MLIR lowering、量化和 BMODEL 编译。'
    },
    {
        'id':'tensorrt','name':'NVIDIA TensorRT','vendor':'NVIDIA','output':'.engine',
        'source_formats':['.pt','.pth','.onnx','.pdparams','.pdmodel','.pdiparams'],
        'targets':['tensorrt'],'sdk':'TensorRT / trtexec','environment':'nvidia_host',
        'chips':[],'description':'将 ONNX 编译为当前 TensorRT/CUDA 环境可加载的 Engine。'
    },
]

def plugin_catalog() -> List[Dict[str, Any]]:
    return [dict(x) for x in _PLUGINS]

def plugin_by_id(plugin_id: str) -> Dict[str, Any]:
    return next((dict(x) for x in _PLUGINS if x['id']==plugin_id), {})
