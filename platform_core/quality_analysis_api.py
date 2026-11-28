"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .quality_analysis_service import QualityAnalysisService
from .quality_analysis_contracts import V44QualityReq, V45ErrorCauseReq



def create_quality_analysis_router_1(service: Callable[[], QualityAnalysisService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v44/projects/{project_id}/quality-center')
    def v44_quality_center(project_id: str):
        return service().v44_quality_center(project_id)

    @router.post('/api/v44/projects/{project_id}/data-quality')
    def v44_data_quality(project_id: str, payload: V44QualityReq):
        return service().v44_data_quality(project_id, payload)

    @router.post('/api/v44/model-configs/{config_id}/test')
    def v44_test_saved_model_config(config_id: str):
        return service().v44_test_saved_model_config(config_id)

    return router


def create_quality_analysis_router_2(service: Callable[[], QualityAnalysisService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v45/projects/{project_id}/jobs/{job_id}/error-cause-analysis')
    def v45_error_cause_analysis(project_id: str, job_id: str, payload: V45ErrorCauseReq):
        """VLM只做错误原因辅助归因。检测是否正确仍由预测框与人工Ground Truth通过IoU/类别客观计算。"""
        return service().v45_error_cause_analysis(project_id, job_id, payload)

    @router.post('/api/v44/projects/{project_id}/jobs/{job_id}/supplement')
    def v44_supplement_training_data(project_id: str, job_id: str):
        return service().v44_supplement_training_data(project_id, job_id)

    return router
