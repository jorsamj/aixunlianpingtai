"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, Optional
from fastapi import APIRouter
from .legacy_automation_service import LegacyAutomationService
from .legacy_automation_contracts import V42AlgorithmBlueprintReq, V42CollectReq, V42SourceReq



def create_legacy_automation_router_1(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/industry-templates')
    def v42_industry_templates():
        return service().v42_industry_templates()

    @router.get('/api/v42/projects/{project_id}/algorithm-blueprints')
    def v42_list_algorithm_blueprints(project_id: str):
        return service().v42_list_algorithm_blueprints(project_id)

    @router.post('/api/v42/projects/{project_id}/algorithm-blueprints')
    def v42_create_algorithm_blueprint(project_id: str, payload: V42AlgorithmBlueprintReq):
        return service().v42_create_algorithm_blueprint(project_id, payload)

    return router


def create_legacy_automation_router_2(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/projects/{project_id}/sources')
    def v42_list_sources(project_id: str):
        return service().v42_list_sources(project_id)

    @router.post('/api/v42/projects/{project_id}/sources')
    def v42_create_source(project_id: str, payload: V42SourceReq):
        return service().v42_create_source(project_id, payload)

    @router.put('/api/v42/projects/{project_id}/sources/{source_id}')
    def v42_update_source(project_id: str, source_id: str, payload: V42SourceReq):
        return service().v42_update_source(project_id, source_id, payload)

    @router.delete('/api/v42/projects/{project_id}/sources/{source_id}')
    def v42_delete_source(project_id: str, source_id: str):
        return service().v42_delete_source(project_id, source_id)

    @router.post('/api/v42/projects/{project_id}/sources/{source_id}/test')
    def v42_test_source(project_id: str, source_id: str):
        return service().v42_test_source(project_id, source_id)

    @router.get('/api/v42/projects/{project_id}/collection-runs')
    def v42_collection_runs(project_id: str):
        return service().v42_collection_runs(project_id)

    @router.post('/api/v42/projects/{project_id}/sources/{source_id}/collect')
    def v42_collect(project_id: str, source_id: str, payload: V42CollectReq):
        return service().v42_collect(project_id, source_id, payload)

    @router.post('/api/v42/model-configs/{config_id}/test')
    def v42_test_saved_model_config(config_id: str):
        return service().v42_test_saved_model_config(config_id)

    return router


def create_legacy_automation_router_3(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/projects/{project_id}/iteration-policies')
    def v42_policies(project_id: str):
        return service().v42_policies(project_id)

    return router


def create_legacy_automation_router_4(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.delete('/api/v42/projects/{project_id}/iteration-policies/{policy_id}')
    def v42_delete_policy(project_id: str, policy_id: str):
        return service().v42_delete_policy(project_id, policy_id)

    @router.get('/api/v42/projects/{project_id}/online-feedback')
    def v42_online_feedback(project_id: str, algorithm_id: Optional[str]=None):
        return service().v42_online_feedback(project_id, algorithm_id)

    return router


def create_legacy_automation_router_5(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/projects/{project_id}/datasets/{dataset_id}/hygiene')
    def v42_dataset_hygiene(project_id: str, dataset_id: str, max_scan: int=1000):
        return service().v42_dataset_hygiene(project_id, dataset_id, max_scan)

    @router.get('/api/v42/projects/{project_id}/iteration-runs')
    def v42_iteration_runs(project_id: str):
        return service().v42_iteration_runs(project_id)

    return router


def create_legacy_automation_router_6(service: Callable[[], LegacyAutomationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v42/projects/{project_id}/quality-overview')
    def v42_quality_overview(project_id: str):
        return service().v42_quality_overview(project_id)

    return router
