"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .deployment_validation_service import DeploymentValidationService

from fastapi import File, Form, UploadFile


def create_deployment_validation_router_1(service: Callable[[], DeploymentValidationService]) -> APIRouter:
    router = APIRouter()

    @router.post('/api/v61/projects/{project_id}/deployment-tests')
    async def create_deployment_test(project_id: str, model_name: str=Form(''), model_source: str=Form('project'), local_path: str=Form(''), algorithm_id: str=Form(''), version_id: str=Form(''), conf: float=Form(0.25), inference_framework: str=Form('ultralytics'), inference_env_id: str=Form(''), detection_batch_id: str=Form(''), detection_item_index: int=Form(-1), detection_item_total: int=Form(0), detection_side: str=Form(''), model_label: str=Form(''), original_filename: str=Form(''), model_scope: str=Form(''), creation_id: str=Form(''), detection_sides: str=Form(''), file: UploadFile=File(...)):
        return await service().create_deployment_test(project_id, model_name, model_source, local_path, algorithm_id, version_id, conf, inference_framework, inference_env_id, detection_batch_id, detection_item_index, detection_item_total, detection_side, model_label, original_filename, model_scope, creation_id, detection_sides, file)

    @router.get('/api/v61/projects/{project_id}/deployment-test-creations/{creation_id}')
    def get_deployment_creation(project_id: str, creation_id: str):
        return service().get_deployment_creation(project_id, creation_id)

    @router.post('/api/v61/projects/{project_id}/deployment-test-creations/{creation_id}/recover')
    async def recover_deployment_creation(project_id: str, creation_id: str):
        return await service().recover_deployment_creation(project_id, creation_id)

    @router.get('/api/v61/projects/{project_id}/deployment-tests/{task_id}')
    def get_deployment_test(project_id: str, task_id: str):
        return service().get_deployment_test(project_id, task_id)

    @router.post('/api/v61/projects/{project_id}/deployment-tests/{task_id}/retry')
    def retry_deployment_test(project_id: str, task_id: str):
        return service().retry_deployment_test(project_id, task_id)

    @router.post('/api/v61/projects/{project_id}/deployment-tests/{task_id}/cancel')
    def cancel_deployment_test(project_id: str, task_id: str):
        return service().cancel_deployment_test(project_id, task_id)

    @router.post('/api/v64/projects/{project_id}/deployment-tests/{task_id}/feedback-evidence')
    def promote_deployment_test_to_feedback_evidence(project_id: str, task_id: str):
        """Create review evidence from one completed formal algorithm-version detection.

        This is intentionally explicit: running a model test never promotes data or
        writes annotation truth. The returned prediction_id can only enter the
        existing v63 human-review flow.
        """
        return service().promote_deployment_test_to_feedback_evidence(project_id, task_id)

    return router
