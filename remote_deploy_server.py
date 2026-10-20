import json
import hashlib
import hmac
import re
import threading
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from platform_core.rknn_runtime import probe_rknn_toolkit
from platform_core.sophon_runtime import probe_sophon_toolchain
from platform_core.remote_conversion_runtime import safe_extract_zip
from platform_core.task_runtime import launch_process, ProcessController, ProcessIdentity
from platform_core.task_runtime.process_control import ProcessIdentityMismatchError
from dataclasses import asdict

BASE_DIR = Path(__file__).resolve().parent
REMOTE_DIR = Path(os.environ.get('MC_REMOTE_DEPLOY_DATA_DIR') or BASE_DIR / 'remote_deploy_data').resolve()
JOBS_DIR = REMOTE_DIR / 'jobs'
CONFIG_FILE = REMOTE_DIR / 'server_config.json'
PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}
REMOTE_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
if not CONFIG_FILE.exists():
    CONFIG_FILE.write_text(json.dumps({
        'api_key':'', 'name':'算法部署转换服务器', 'python_path':sys.executable,
        'tool_root':'', 'paddledet_dir':'', 'trtexec_path':'', 'atc_path':'', 'env_script':'',
        'ultralytics_python':'', 'paddle2onnx_path':''
    }, ensure_ascii=False, indent=2), encoding='utf-8')

DEPLOY_SERVER_VERSION = (BASE_DIR / 'VERSION.txt').read_text(encoding='utf-8', errors='ignore').strip() if (BASE_DIR / 'VERSION.txt').exists() else '42.14.0'
app = FastAPI(title='畅联云远程部署转换服务', version=DEPLOY_SERVER_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def read_json(p:Path, default):
    try:return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
    except:return default
def write_json(p:Path,data):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def check_key(key=''):
    need=read_json(CONFIG_FILE,{}).get('api_key') or ''
    if not need or not isinstance(key, str) or not hmac.compare_digest(key, need):raise HTTPException(status_code=401,detail='API Key 不正确或服务尚未配置密钥')
def which(*items):
    for x in items:
        if not x:continue
        p=Path(str(x))
        if p.exists() and p.is_file():return str(p)
        q=shutil.which(str(x))
        if q:return q
    return ''
def command_version(cmd):
    if not cmd:return ''
    for args in ([cmd,'--version'],[cmd,'-v'],[cmd,'--help']):
        try:
            cp=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=8)
            txt=(cp.stdout or cp.stderr or '').strip().splitlines()
            if txt:return txt[0][:240]
        except:pass
    return ''
def detect_tools():
    cfg=read_json(CONFIG_FILE,{})
    root=Path(str(cfg.get('tool_root') or '')) if cfg.get('tool_root') else None
    transform=which(str(root/'python'/'tools'/'model_transform.py') if root else '', 'model_transform.py','model_transform')
    deploy=which(str(root/'python'/'tools'/'model_deploy.py') if root else '', 'model_deploy.py','model_deploy')
    cali=which(str(root/'python'/'tools'/'run_calibration.py') if root else '', 'run_calibration.py','run_calibration')
    atc=which(cfg.get('atc_path',''),'atc')
    trtexec=which(cfg.get('trtexec_path',''),'trtexec')
    paddle2onnx=which(cfg.get('paddle2onnx_path',''),'paddle2onnx')
    paddledet_raw=str(cfg.get('paddledet_dir') or '').strip()
    paddledet=Path(paddledet_raw) if paddledet_raw else None
    py=str(cfg.get('python_path') or sys.executable)
    ultra_py=str(cfg.get('ultralytics_python') or py)
    ultra=False;paddle=False;rknn=False;rknn_version=''
    rknn_probe={}
    try: ultra=subprocess.run([ultra_py,'-c','import ultralytics;print(ultralytics.__version__)'],capture_output=True,text=True,timeout=10).returncode==0
    except:pass
    try: paddle=subprocess.run([py,'-c','import paddle;print(paddle.__version__)'],capture_output=True,text=True,timeout=10).returncode==0
    except:pass
    rknn_probe=probe_rknn_toolkit(py, timeout=15)
    rknn=bool(rknn_probe.get('available'))
    rknn_version=str(rknn_probe.get('version') or '')
    npu=''
    soc_versions=[]
    nsmi=which('npu-smi')
    if nsmi:
        try:
            npu=subprocess.run([nsmi,'info'],capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=10).stdout[-5000:]
            import re as _re
            for m in _re.findall(r'Ascend\s*([0-9]{3,4}[A-Za-z0-9_-]*)', npu, _re.I):
                v='Ascend'+m.replace(' ','')
                if v not in soc_versions:soc_versions.append(v)
        except:pass
    targets=[]
    if ultra:targets.append('onnx')
    if paddle and paddledet and paddledet.exists() and (paddledet/'tools'/'export_model.py').exists():targets.append('paddle_inference')
    if trtexec:targets.append('tensorrt')
    sophon_probe=probe_sophon_toolchain(cfg)
    if sophon_probe.get('available'):targets.append('sophon')
    if atc:targets.append('ascend')
    if rknn:targets.append('rockchip')
    return {
        'ultralytics':ultra,'paddle':paddle,'paddledet':str(paddledet) if paddledet and paddledet.exists() else '',
        'model_transform':transform,'model_deploy':deploy,'run_calibration':cali,'trtexec':trtexec,'atc':atc,'paddle2onnx':paddle2onnx,
        'sophon':sophon_probe,'targets':targets,'rknn_toolkit2':rknn,'rknn_version':rknn_version,
        'rknn_onnx_version':str(rknn_probe.get('onnx_version') or ''),
        'rknn_error_code':str(rknn_probe.get('error_code') or ''),
        'rknn_error':str(rknn_probe.get('error') or ''),'npu_info':npu,'npu_smi':nsmi,'soc_versions':soc_versions,'atlas_om_ready':bool(atc),'versions':{'trtexec':command_version(trtexec),'atc':command_version(atc),'model_deploy':command_version(deploy),'rknn_toolkit2':rknn_version}
    }

@app.get('/api/deploy/health')
def health(x_api_key:str=Header(default='')):
    check_key(x_api_key);cfg=read_json(CONFIG_FILE,{})
    tools=detect_tools()
    return {'ok':True,'server':'mc-deploy-server','version':DEPLOY_SERVER_VERSION,'name':cfg.get('name') or '算法部署转换服务器','time':now(),'base_dir':str(BASE_DIR),'tools':tools,'targets':tools['targets']}

class ConfigReq(BaseModel):
    api_key:str='';name:str='算法部署转换服务器';python_path:str='';tool_root:str='';paddledet_dir:str='';trtexec_path:str='';atc_path:str='';env_script:str='';ultralytics_python:str='';paddle2onnx_path:str=''
@app.post('/api/deploy/config')
def save_config(payload:ConfigReq,x_api_key:str=Header(default='')):
    check_key(x_api_key)
    if not payload.api_key.strip():raise HTTPException(status_code=400,detail='API Key 不能为空')
    write_json(CONFIG_FILE,payload.model_dump());return {'ok':True,'tools':detect_tools()}

JOB_CREATE_LOCK = threading.Lock()

def valid_job_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(value or '')):
        raise HTTPException(status_code=400,detail='任务 ID 非法')
    return value

@app.post('/api/deploy/convert')
async def convert(source_model:UploadFile=File(...), target:str=Form(...), params_json:str=Form('{}'), config_file:Optional[UploadFile]=File(default=None), calibration_zip:Optional[UploadFile]=File(default=None), x_api_key:str=Header(default=''), client_job_id:str=Form(default=''), source_trace_json:str=Form(default='{}')):
    check_key(x_api_key)
    try:
        params=json.loads(params_json or '{}')
        trace=json.loads(source_trace_json or '{}')
        if not isinstance(params,dict) or not isinstance(trace,dict):raise ValueError('需要 JSON 对象')
    except Exception as e:raise HTTPException(status_code=400,detail=f'请求 JSON 无效：{e}')
    body=await source_model.read()
    cfg_body=await config_file.read() if config_file is not None else None
    calibration_body=await calibration_zip.read() if calibration_zip is not None else None
    if target == 'sophon':
        from platform_core.conversion import validate_target
        try:params=validate_target(target,params)
        except ValueError as error:raise HTTPException(status_code=400,detail=str(error))
    jid=valid_job_id(client_job_id) if client_job_id else uuid.uuid4().hex[:12]
    identity=hashlib.sha256(json.dumps({'target':target,'params':params,'trace':trace,'source_sha256':hashlib.sha256(body).hexdigest(), 'config_sha256':hashlib.sha256(cfg_body or b'').hexdigest(), 'calibration_sha256':hashlib.sha256(calibration_body or b'').hexdigest()},sort_keys=True).encode()).hexdigest()
    jd=JOBS_DIR/jid
    with JOB_CREATE_LOCK:
        if jd.exists():
            existing=read_json(jd/'job.json',{})
            if existing.get('request_identity') != identity:
                raise HTTPException(status_code=409,detail='任务 ID 已存在且请求不一致')
            return {'ok':True,'job_id':jid,'status':existing.get('status'),'reused':True}
        cfg=read_json(CONFIG_FILE,{})
        if target == 'sophon':
            probe=probe_sophon_toolchain(cfg)
            if not probe.get('available') or params.get('chip') not in probe.get('supported_chips',[]):
                raise HTTPException(status_code=400,detail={'code':probe.get('error_code') or 'TPU_MLIR_UNAVAILABLE','error':probe.get('error') or '当前 TPU-MLIR 不支持指定芯片','solution':probe.get('solution') or '检查 TPU-MLIR 环境'})
        srcd=jd/'source';srcd.mkdir(parents=True,exist_ok=False)
        src=srcd/Path(source_model.filename or 'model.bin').name;src.write_bytes(body)
        if cfg_body is not None:
            cfgp=srcd/Path(config_file.filename or 'model.yml').name;cfgp.write_bytes(cfg_body);params['config_path']=str(cfgp)
        cal_dir=None
        if calibration_body is not None:
            import io
            cal_dir=jd/'calibration';cal_dir.mkdir()
            try:
                with zipfile.ZipFile(io.BytesIO(calibration_body),'r') as zf:safe_extract_zip(zf,cal_dir)
            except Exception as e:raise HTTPException(status_code=400,detail=f'校准数据解压失败：{e}')
        resource={**{k:v for k,v in cfg.items() if k!='api_key'},'id':'remote','name':cfg.get('name') or '远程部署服务器','mode':'local'}
        job={'id':jid,'request_identity':identity,'source_trace':trace,'status':'queued','progress':0,'stage':'等待启动','message':'等待启动','target':target,'params':params,'resource':resource,'source_path':str(src),'calibration_dir':str(cal_dir) if cal_dir else '','created_at':now(),'updated_at':now()}
        write_json(jd/'job.json',job)
        try:
            with (jd/'convert.log').open('ab') as log:
                command=[sys.executable,str(BASE_DIR/'deployment_worker.py'),'--job-dir',str(jd)]
                options=dict(cwd=str(BASE_DIR),stdout=log,stderr=subprocess.STDOUT,env={**os.environ.copy(),'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
                if target == 'sophon':
                    launched=launch_process(command,**options)
                    proc=launched.process
                    write_json(jd/'process.json',asdict(launched.identity))
                else:
                    proc=subprocess.Popen(command,**options)
            PROCESS_REGISTRY[jid]=proc
        except Exception as error:
            job.update(status='failed',error=str(error),error_code='REMOTE_WORKER_START_FAILED');write_json(jd/'job.json',job)
            raise HTTPException(status_code=500,detail='转换 Worker 启动失败')
    return {'ok':True,'job_id':jid,'status':'running'}

def sync_job(jid):
    jf=JOBS_DIR/valid_job_id(jid)/'job.json'
    if not jf.exists():raise HTTPException(status_code=404,detail='任务不存在')
    j=read_json(jf,{})
    p=PROCESS_REGISTRY.get(jid)
    if p and p.poll() is not None:PROCESS_REGISTRY.pop(jid,None)
    return j
@app.get('/api/deploy/jobs/{job_id}')
def get_job(job_id:str,x_api_key:str=Header(default='')):check_key(x_api_key);return sync_job(job_id)
@app.get('/api/deploy/jobs/{job_id}/log',response_class=PlainTextResponse)
def get_log(job_id:str,x_api_key:str=Header(default='')):
    check_key(x_api_key);p=JOBS_DIR/valid_job_id(job_id)/'convert.log'
    return p.read_text(encoding='utf-8',errors='ignore')[-120000:] if p.exists() else '暂无日志'
@app.post('/api/deploy/jobs/{job_id}/stop')
def stop_job(job_id:str,x_api_key:str=Header(default='')):
    check_key(x_api_key);valid_job_id(job_id);p=PROCESS_REGISTRY.get(job_id)
    identity=read_json(JOBS_DIR/job_id/'process.json',{})
    if identity:
        try:ProcessController().terminate_tree(ProcessIdentity(**identity))
        except (ProcessLookupError,ProcessIdentityMismatchError):pass
        except Exception as error:raise HTTPException(status_code=409,detail=f'无法确认远程进程树终止：{error}')
        PROCESS_REGISTRY.pop(job_id,None)
    elif p:
        try:p.terminate();time.sleep(.5)
        except:pass
        if p.poll() is None:
            try:p.kill()
            except:pass
        PROCESS_REGISTRY.pop(job_id,None)
    jf=JOBS_DIR/job_id/'job.json';j=read_json(jf,{})
    if j:j.update({'status':'stopped','message':'用户停止','stage':'已停止','updated_at':now()});write_json(jf,j)
    return {'ok':True}
@app.get('/api/deploy/jobs/{job_id}/artifacts.zip')
def artifact_zip(job_id:str,x_api_key:str=Header(default='')):
    check_key(x_api_key);j=sync_job(job_id)
    ad=JOBS_DIR/job_id/'artifacts'
    if not ad.exists():raise HTTPException(status_code=404,detail='暂无部署产物')
    zp=JOBS_DIR/job_id/f'{job_id}_artifacts.zip'
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as zf:
        for p in ad.rglob('*'):
            if p.is_file():zf.write(p,p.relative_to(ad))
    return FileResponse(zp,filename=zp.name)
