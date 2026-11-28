"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .storage_configuration_service import StorageConfigurationService
from .storage_configuration_contracts import StorageSourceCreateReq, StorageSourceUpdateReq



def create_storage_configuration_router_1(service: Callable[[], StorageConfigurationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v61/storage-sources')
    def list_storage_sources():
        return service().list_storage_sources()

    @router.post('/api/v61/storage-sources', status_code=201)
    def create_storage_source(payload: StorageSourceCreateReq):
        return service().create_storage_source(payload)

    @router.patch('/api/v61/storage-sources/{source_id}')
    def update_storage_source(source_id: str, payload: StorageSourceUpdateReq):
        return service().update_storage_source(source_id, payload)

    @router.post('/api/v61/storage-sources/{source_id}/default')
    def set_default_storage_source(source_id: str):
        return service().set_default_storage_source(source_id)

    @router.post('/api/v61/storage-sources/{source_id}/test')
    def test_storage_source(source_id: str):
        return service().test_storage_source(source_id)

    @router.delete('/api/v61/storage-sources/{source_id}')
    def delete_storage_source(source_id: str):
        return service().delete_storage_source(source_id)

    return router
