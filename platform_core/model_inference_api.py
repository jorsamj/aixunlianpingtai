"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .model_inference_service import ModelInferenceService

from fastapi import File, Form, UploadFile


def create_model_inference_router_1(service: Callable[[], ModelInferenceService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/projects/{project_id}/models')
    def list_models(project_id: str):
        return service().list_models(project_id)

    @router.get('/api/projects/{project_id}/models/{model_name}/download')
    def download_model(project_id: str, model_name: str):
        return service().download_model(project_id, model_name)

    @router.post('/api/projects/{project_id}/predict')
    async def predict_image(project_id: str, model_name: str=Form(...), conf: float=Form(0.25), file: UploadFile=File(...)):
        return await service().predict_image(project_id, model_name, conf, file)

    @router.post('/api/projects/{project_id}/export/onnx')
    def export_onnx(project_id: str, model_name: str=Form(...)):
        return service().export_onnx(project_id, model_name)

    return router


def create_model_inference_router_2(service: Callable[[], ModelInferenceService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v12/projects/{project_id}/predict')
    async def v12_predict_image(project_id: str, model_name: str=Form(''), model_source: str=Form('project'), local_path: str=Form(''), algorithm_id: str=Form(''), version_id: str=Form(''), conf: float=Form(0.25), inference_framework: str=Form('ultralytics'), inference_env_id: str=Form(''), file: UploadFile=File(...)):
        return await service().v12_predict_image(project_id, model_name, model_source, local_path, algorithm_id, version_id, conf, inference_framework, inference_env_id, file)

    return router


def create_model_inference_router_3(service: Callable[[], ModelInferenceService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/test_models')
    def v12_test_models(project_id: str, probe_optional: bool=True, model_scope: str=''):
        return service().v12_test_models(project_id, probe_optional, model_scope)

    return router
