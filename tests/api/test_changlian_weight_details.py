"""Scoped HTTP contract for the existing read-only provider routes."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from platform_core.external_algorithm_platform import ExternalAlgorithmPlatformService, external_algorithm_platform_router
from platform_core.errors import PlatformError,error_body
from platform_core.secrets import MemorySecretStore


def test_existing_weight_routes_preserve_ids_queries_redaction_and_invalid_inputs(tmp_path,monkeypatch):
    calls=[]
    class Client:
        def weight_info(self,weight_id,**kwargs):
            calls.append((weight_id,kwargs))
            if not weight_id.isdecimal():raise ValueError('weightId invalid')
            return {"code":200,"data":{"weightId":2112456166616469504,"tags":["Car"],"accessToken":"private"}}
        def weight_page(self,**kwargs):
            calls.append(kwargs);return {"code":200,"total":1,"data":[{"weightId":2112456166616469504,"tags":["Car"]}]}
    monkeypatch.setattr(ExternalAlgorithmPlatformService,'_client',lambda self:Client())
    app=FastAPI()
    @app.exception_handler(PlatformError)
    async def platform_error(request,error):return JSONResponse(error_body(error),status_code=error.status_code)
    app.include_router(external_algorithm_platform_router(data_dir=tmp_path,get_project=lambda p:None,algorithms_file=lambda p:tmp_path/'a.json',secret_store_factory=MemorySecretStore))
    client=TestClient(app);base='/api/v63/external-algorithm-platform/provider/weights'
    result=client.get(base+'/2112456166616469504?withTags=true')
    assert result.status_code==200
    assert result.json()['response']['data']=={'weightId':'2112456166616469504','tags':['Car'],'accessToken':'***'}
    assert calls[-1]==('2112456166616469504',{'with_tags':True})
    client.get(base+'/2112456166616469504');assert calls[-1]==('2112456166616469504',{})
    page=client.get(base+'/page?pageNum=2&pageSize=50&algoVersionId=2109729657292197888&withTags=true')
    assert page.json()['response']['data'][0]['weightId']=='2112456166616469504'
    assert calls[-1]=={'page_num':2,'page_size':50,'algoVersionId':'2109729657292197888','withTags':'true'}
    before=len(calls)
    assert client.get(base+'/page?pageNum=0&pageSize=50').status_code==422
    assert client.get(base+'/page?pageNum=1&pageSize=501').status_code==422
    assert client.get(base+'/2112456166616469504?withTags=invalid').status_code==422
    assert len(calls)==before
    bad=client.get(base+'/invalid');assert bad.status_code==400 and bad.json()['code']=='EXTERNAL_WEIGHT_ID_INVALID'
