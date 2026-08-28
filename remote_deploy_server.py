import json
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

BASE_DIR = Path(__file__).resolve().parent
REMOTE_DIR = BASE_DIR / 'remote_deploy_data'
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
def safe_extract_zip(zf: zipfile.ZipFile, dst: Path):
    dst = dst.resolve()
    for member in zf.infolist():
        target = (dst / member.filename).resolve()
        try:
            target.relative_to(dst)
        except ValueError:
            raise RuntimeError(f'ZIP 包含非法路径：{member.filename}')
    zf.extractall(dst)

def check_key(key=''):
    need=read_json(CONFIG_FILE,{}).get('api_key') or ''
    if need and key!=need:raise HTTPException(status_code=401,detail='API Key 不正确')
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
    try: ultra=subprocess.run([ultra_py,'-c','import ultralytics;print(ultralytics.__version__)'],capture_output=True,text=True,timeout=10).returncode==0
    except:pass
    try: paddle=subprocess.run([py,'-c','import paddle;print(paddle.__version__)'],capture_output=True,text=True,timeout=10).returncode==0
    except:pass
    try:
        cp=subprocess.run([py,'-c',"from rknn.api import RKNN; import importlib.metadata as m; print(m.version('rknn-toolkit2'))"],capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=15)
        rknn=cp.returncode==0
        if rknn:rknn_version=(cp.stdout or '').strip().splitlines()[-1]
    except:pass
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
    if transform and deploy:targets.append('sophon')
    if atc:targets.append('ascend')
    if rknn:targets.append('rockchip')
    return {
        'ultralytics':ultra,'paddle':paddle,'paddledet':str(paddledet) if paddledet and paddledet.exists() else '',
        'model_transform':transform,'model_deploy':deploy,'run_calibration':cali,'trtexec':trtexec,'atc':atc,'paddle2onnx':paddle2onnx,
        'targets':targets,'rknn_toolkit2':rknn,'rknn_version':rknn_version,'npu_info':npu,'npu_smi':nsmi,'soc_versions':soc_versions,'atlas_om_ready':bool(atc),'versions':{'trtexec':command_version(trtexec),'atc':command_version(atc),'model_deploy':command_version(deploy),'rknn_toolkit2':rknn_version}
    }

@app.get('/api/deploy/health')
def health(x_api_key:str=Header(default='')):
    check_key(x_api_key);cfg=read_json(CONFIG_FILE,{})
    tools=detect_tools()
    return {'ok':True,'server':'mc-deploy-server','version':DEPLOY_SERVER_VERSION,'name':cfg.get('name') or '算法部署转换服务器','time':now(),'base_dir':str(BASE_DIR),'tools':tools,'targets':tools['targets']}

class ConfigReq(BaseModel):
    api_key:str='';name:str='算法部署转换服务器';python_path:str='';tool_root:str='';paddledet_dir:str='';trtexec_path:str='';atc_path:str='';env_script:str='';ultralytics_python:str='';paddle2onnx_path:str=''
@app.post('/api/deploy/config')
def save_config(payload:ConfigReq):
    write_json(CONFIG_FILE,payload.model_dump());return {'ok':True,'tools':detect_tools()}

@app.post('/api/deploy/convert')
async def convert(source_model:UploadFile=File(...), target:str=Form(...), params_json:str=Form('{}'), config_file:Optional[UploadFile]=File(default=None), calibration_zip:Optional[UploadFile]=File(default=None), x_api_key:str=Header(default='')):
    check_key(x_api_key)
    try:params=json.loads(params_json or '{}')
    except Exception as e:raise HTTPException(status_code=400,detail=f'params_json 无效：{e}')
    jid=uuid.uuid4().hex[:12];jd=JOBS_DIR/jid;srcd=jd/'source';srcd.mkdir(parents=True,exist_ok=True)
    src=srcd/Path(source_model.filename or 'model.bin').name;src.write_bytes(await source_model.read())
    if config_file is not None:
        cfgp=srcd/Path(config_file.filename or 'model.yml').name;cfgp.write_bytes(await config_file.read());params['config_path']=str(cfgp)
    cal_dir=None
    if calibration_zip is not None:
        zp=jd/'calibration.zip';zp.write_bytes(await calibration_zip.read());cal_dir=jd/'calibration';cal_dir.mkdir(parents=True,exist_ok=True)
        try:
            with zipfile.ZipFile(zp,'r') as zf:safe_extract_zip(zf,cal_dir)
        except Exception as e:raise HTTPException(status_code=400,detail=f'校准数据解压失败：{e}')
    cfg=read_json(CONFIG_FILE,{})
    resource={**cfg,'id':'remote','name':cfg.get('name') or '远程部署服务器','mode':'local'}
    job={'id':jid,'status':'queued','progress':0,'stage':'等待启动','message':'等待启动','target':target,'params':params,'resource':resource,'source_path':str(src),'calibration_dir':str(cal_dir) if cal_dir else '','created_at':now(),'updated_at':now()}
    write_json(jd/'job.json',job)
    log=(jd/'convert.log').open('ab')
    proc=subprocess.Popen([sys.executable,str(BASE_DIR/'deployment_worker.py'),'--job-dir',str(jd)],cwd=str(BASE_DIR),stdout=log,stderr=subprocess.STDOUT,env={**os.environ.copy(),'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
    PROCESS_REGISTRY[jid]=proc
    return {'ok':True,'job_id':jid,'status':'running'}

def sync_job(jid):
    jf=JOBS_DIR/jid/'job.json'
    if not jf.exists():raise HTTPException(status_code=404,detail='任务不存在')
    j=read_json(jf,{})
    p=PROCESS_REGISTRY.get(jid)
    if p and p.poll() is not None:PROCESS_REGISTRY.pop(jid,None)
    return j
@app.get('/api/deploy/jobs/{job_id}')
def get_job(job_id:str,x_api_key:str=Header(default='')):check_key(x_api_key);return sync_job(job_id)
@app.get('/api/deploy/jobs/{job_id}/log',response_class=PlainTextResponse)
def get_log(job_id:str,x_api_key:str=Header(default='')):
    check_key(x_api_key);p=JOBS_DIR/job_id/'convert.log'
    return p.read_text(encoding='utf-8',errors='ignore')[-120000:] if p.exists() else '暂无日志'
@app.post('/api/deploy/jobs/{job_id}/stop')
def stop_job(job_id:str,x_api_key:str=Header(default='')):
    check_key(x_api_key);p=PROCESS_REGISTRY.get(job_id)
    if p:
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
