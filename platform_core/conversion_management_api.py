"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, List
from fastapi import APIRouter, Query
from .conversion_management_service import ConversionManagementService
from .conversion_management_contracts import DeployJobReq, DeployResourceReq, ModelExportReq

from fastapi import File, Form, UploadFile
from fastapi.responses import PlainTextResponse


def create_conversion_management_router_1(service: Callable[[], ConversionManagementService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v30/projects/{project_id}/model-export')
    def v30_export_model_package(project_id: str, payload: ModelExportReq):
        return service().v30_export_model_package(project_id, payload)

    @router.post('/api/v32/projects/{project_id}/model-export')
    def v32_export_model_package(project_id: str, payload: ModelExportReq):
        return service().v32_export_model_package(project_id, payload)

    return router


def create_conversion_management_router_2(service: Callable[[], ConversionManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v39/deploy/resources')
    def v39_list_deploy_resources(detect_missing: bool=True):
        return service().v39_list_deploy_resources(detect_missing)

    @router.post('/api/v39/deploy/resources')
    def v39_create_deploy_resource(payload: DeployResourceReq):
        return service().v39_create_deploy_resource(payload)

    @router.put('/api/v39/deploy/resources/{resource_id}')
    def v39_update_deploy_resource(resource_id: str, payload: DeployResourceReq):
        return service().v39_update_deploy_resource(resource_id, payload)

    @router.delete('/api/v39/deploy/resources/{resource_id}')
    def v39_delete_deploy_resource(resource_id: str):
        return service().v39_delete_deploy_resource(resource_id)

    @router.post('/api/v39/deploy/resources/{resource_id}/detect')
    def v39_detect_deploy_resource(resource_id: str, force: bool=True):
        return service().v39_detect_deploy_resource(resource_id, force)

    @router.post('/api/v39/deploy/resources/{resource_id}/detect/start')
    def v39_start_deploy_resource_detection(resource_id: str):
        """Bounded start, shared by tabs/Web workers; status uses the existing GET.

        This is not a second SDK cache or task truth. The saved resource row owns
        its in-flight run ID, and the existing detector/file lock does the work.
        A crashed worker's lease expires in observe(); an explicit retry can claim
        the resource again without ever reporting a fabricated success.
        """
        return service().v39_start_deploy_resource_detection(resource_id)

    @router.get('/api/v39/deploy/resources/{resource_id}/detect/status')
    def v39_conversion_resource_detection_status(resource_id: str):
        return service().v39_conversion_resource_detection_status(resource_id)

    @router.post('/api/v39/deploy/local/auto-detect')
    def v39_detect_local_deploy_resources():
        """只检测当前机器真正存在的部署编译器；不存在的不会伪造为 ready。"""
        return service().v39_detect_local_deploy_resources()

    @router.get('/api/v39/projects/{project_id}/deploy/source-models')
    def v39_deploy_source_models(project_id: str):
        return service().v39_deploy_source_models(project_id)

    return router


def create_conversion_management_router_3(service: Callable[[], ConversionManagementService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v39/projects/{project_id}/deploy/resolve')
    def v39_resolve_conversion(project_id: str, payload: DeployJobReq):
        return service().v39_resolve_conversion(project_id, payload)

    @router.post('/api/v39/projects/{project_id}/deploy/jobs')
    def v39_create_deploy_job(project_id: str, payload: DeployJobReq):
        return service().v39_create_deploy_job(project_id, payload)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/by-request/{request_id}')
    def v39_conversion_job_by_request(project_id: str, request_id: str):
        return service().v39_conversion_job_by_request(project_id, request_id)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/preflight')
    def v39_rknn_hardware_test_preflight(project_id: str, job_id: str):
        return service().v39_rknn_hardware_test_preflight(project_id, job_id)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/report')
    def v39_rknn_hardware_acceptance_report(project_id: str, job_id: str, download: bool=Query(False)):
        return service().v39_rknn_hardware_acceptance_report(project_id, job_id, download)

    @router.post('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests')
    async def v39_create_rknn_hardware_test(project_id: str, job_id: str, file: UploadFile=File(...)):
        return await service().v39_create_rknn_hardware_test(project_id, job_id, file)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs')
    def v39_list_deploy_jobs(project_id: str):
        return service().v39_list_deploy_jobs(project_id)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}')
    def v39_get_deploy_job(project_id: str, job_id: str):
        return service().v39_get_deploy_job(project_id, job_id)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations')
    def v39_list_numeric_validations(project_id: str, job_id: str):
        return service().v39_list_numeric_validations(project_id, job_id)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations/{verification_id}')
    def v39_get_numeric_validation(project_id: str, job_id: str, verification_id: str):
        return service().v39_get_numeric_validation(project_id, job_id, verification_id)

    @router.post('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations')
    def v39_create_numeric_validation(project_id: str, job_id: str, files: List[UploadFile]=File(...), request_id: str=Form(''), confidence: float=Form(0.25), nms_iou: float=Form(0.7)):
        """Freeze real samples and enqueue PT-vs-ONNX only; never assert BMODEL pass."""
        return service().v39_create_numeric_validation(project_id, job_id, files, request_id, confidence, nms_iou)

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/log', response_class=PlainTextResponse)
    def v39_deploy_job_log(project_id: str, job_id: str):
        return service().v39_deploy_job_log(project_id, job_id)

    @router.post('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/stop')
    def v39_stop_deploy_job(project_id: str, job_id: str):
        return service().v39_stop_deploy_job(project_id, job_id)

    @router.delete('/api/v39/projects/{project_id}/deploy/jobs/{job_id}')
    def v39_delete_deploy_job(project_id: str, job_id: str):
        return service().v39_delete_deploy_job(project_id, job_id)

    return router


def create_conversion_management_router_4(service: Callable[[], ConversionManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v39/projects/{project_id}/deploy/jobs/{job_id}/package')
    def v39_download_deploy_package(project_id: str, job_id: str):
        return service().v39_download_deploy_package(project_id, job_id)

    return router


def create_conversion_management_router_5(service: Callable[[], ConversionManagementService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployments')
    def v423_version_deployments(project_id: str, algorithm_id: str, version_id: str, page: int=1, page_size: int=100, status: str='', target: str='', chip: str='', precision: str='', csc: str='', created_from: str='', created_to: str='', force: bool=False, asset_view: bool=False):
        return service().v423_version_deployments(project_id, algorithm_id, version_id, page, page_size, status, target, chip, precision, csc, created_from, created_to, force, asset_view)

    return router
