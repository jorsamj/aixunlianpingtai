"""HTTP surface of the algorithm catalog; business rules have one service owner."""
from __future__ import annotations

from typing import Callable
from fastapi import APIRouter
from .algorithm_catalog_contracts import AlgorithmReq, AlgorithmVersionReq, VersionPatchReq, AlgorithmVersionRollbackReq
from .algorithm_catalog_service import AlgorithmCatalogService


def create_algorithm_catalog_router(service: Callable[[], AlgorithmCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/algorithms')
    def v12_list_algorithms(project_id: str, summary_only: bool=False, asset_view: bool=False, page: int=1, page_size: int=20, query: str='', algorithm_type: str='', industry: str='', source_type: str='', status: str='', sort: str='updated', library_view: bool=False, training_state: str='', category_ids: str=''):
        return service().v12_list_algorithms(project_id, summary_only, asset_view, page, page_size, query, algorithm_type, industry, source_type, status, sort, library_view, training_state, category_ids)

    @router.post('/api/v12/projects/{project_id}/algorithms')
    def v12_create_algorithm(project_id: str, payload: AlgorithmReq, asset_view: bool=False):
        return service().v12_create_algorithm(project_id, payload, asset_view)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}')
    def v12_get_algorithm(project_id: str, algorithm_id: str, asset_view: bool=False, version_id: str='', page: int=1, page_size: int=20, basic_only: bool=False, quality_view: bool=False):
        return service().v12_get_algorithm(project_id, algorithm_id, asset_view, version_id, page, page_size, basic_only, quality_view)

    @router.put('/api/v12/projects/{project_id}/algorithms/{algorithm_id}')
    def v12_update_algorithm(project_id: str, algorithm_id: str, payload: AlgorithmReq, asset_view: bool=False):
        return service().v12_update_algorithm(project_id, algorithm_id, payload, asset_view)

    @router.delete('/api/v12/projects/{project_id}/algorithms/{algorithm_id}')
    def v12_delete_algorithm(project_id: str, algorithm_id: str):
        return service().v12_delete_algorithm(project_id, algorithm_id)

    @router.get('/api/v12/projects/{project_id}/publish/pending')
    def v12_pending_models(project_id: str):
        return service().v12_pending_models(project_id)

    @router.post('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions')
    def v12_assign_version(project_id: str, algorithm_id: str, payload: AlgorithmVersionReq):
        return service().v12_assign_version(project_id, algorithm_id, payload)

    @router.put('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}')
    def v12_update_version(project_id: str, algorithm_id: str, version_id: str, payload: VersionPatchReq, asset_view: bool=False):
        return service().v12_update_version(project_id, algorithm_id, version_id, payload, asset_view)

    @router.delete('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}')
    def v12_delete_version(project_id: str, algorithm_id: str, version_id: str):
        return service().v12_delete_version(project_id, algorithm_id, version_id)

    @router.post('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/rollback')
    def v12_rollback_version(project_id: str, algorithm_id: str, version_id: str, payload: AlgorithmVersionRollbackReq):
        return service().v12_rollback_version(project_id, algorithm_id, version_id, payload)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployment-activation-dry-run')
    def v12_deployment_activation_dry_run(project_id: str, algorithm_id: str, version_id: str, operation_id: str='', expected_current_version_id: str=''):
        'Read-only deployment activation Dry-Run; reuses `_dry_run_operation_guard`.'
        return service().v12_deployment_activation_dry_run(project_id, algorithm_id, version_id, operation_id, expected_current_version_id)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/rollback-dry-run')
    def v12_rollback_dry_run(project_id: str, algorithm_id: str, version_id: str, operation_id: str='', expected_current_version_id: str=''):
        'Read-only rollback Dry-Run; reuses `_dry_run_operation_guard`.'
        return service().v12_rollback_dry_run(project_id, algorithm_id, version_id, operation_id, expected_current_version_id)

    @router.post('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/version-operations/{operation_id}/retry-cleanup')
    def v12_retry_version_cleanup(project_id: str, algorithm_id: str, operation_id: str):
        return service().v12_retry_version_cleanup(project_id, algorithm_id, operation_id)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/download')
    def v12_download_version(project_id: str, algorithm_id: str, version_id: str):
        return service().v12_download_version(project_id, algorithm_id, version_id)

    return router
