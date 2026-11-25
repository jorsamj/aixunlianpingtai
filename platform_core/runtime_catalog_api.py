"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Any, Callable, Dict, Optional
from fastapi import APIRouter
from .runtime_catalog_service import RuntimeCatalogService
from .runtime_catalog_contracts import LocalModelScanReq, PaddleDetectReq, PaddleEnvReq, TrainServerReq, TrainingRobustnessPolicyReq, UltralyticsEnvDetectReq

from fastapi import File, UploadFile


def create_runtime_catalog_router_1(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/system/version')
    def system_version():
        return service().system_version()

    @router.get('/api/v62/workers')
    def list_worker_runtime():
        return service().list_worker_runtime()

    @router.get('/api/v62/gpu-runtime')
    def gpu_runtime_truth():
        return service().gpu_runtime_truth()

    return router


def create_runtime_catalog_router_2(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v62/training/robustness-policy')
    def training_robustness_policy():
        return service().training_robustness_policy()

    @router.put('/api/v62/training/robustness-policy')
    def save_training_robustness_policy(payload: TrainingRobustnessPolicyReq):
        return service().save_training_robustness_policy(payload)

    @router.get('/api/system/recommendation')
    def system_recommendation(probe_local_cuda: bool=False):
        return service().system_recommendation(probe_local_cuda)

    return router


def create_runtime_catalog_router_3(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/local_models')
    def list_local_models(limit: int=200, cursor: Optional[str]=None):
        return service().list_local_models(limit, cursor)

    @router.post('/api/local_models/scan', status_code=202)
    def scan_local_models(payload: LocalModelScanReq):
        return service().scan_local_models(payload)

    @router.get('/api/ultralytics_env')
    def get_ultralytics_env():
        return service().get_ultralytics_env()

    @router.post('/api/ultralytics_env/detect', status_code=202)
    def detect_ultralytics_env(payload: UltralyticsEnvDetectReq):
        return service().detect_ultralytics_env(payload)

    return router


def create_runtime_catalog_router_4(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/resource-discovery/tasks/{task_id}')
    def get_resource_discovery_task(task_id: str):
        return service().get_resource_discovery_task(task_id)

    @router.post('/api/resource-discovery/tasks/{task_id}/cancel')
    def cancel_resource_discovery_task(task_id: str):
        return service().cancel_resource_discovery_task(task_id)

    @router.get('/api/training_catalog')
    def training_catalog():
        return service().training_catalog()

    @router.post('/api/v63/base-models/upload')
    async def upload_preinstalled_base_model(file: UploadFile=File(...)):
        """Explicit opt-in preload to durable storage. Does not invoke Ultralytics."""
        return await service().upload_preinstalled_base_model(file)

    @router.get('/api/v63/base-models/assets')
    def list_mother_model_assets():
        """Cached evidence only. GET must never import torch or scan Agent disks."""
        return service().list_mother_model_assets()

    @router.get('/api/v63/base-models/node-inventory')
    def list_mother_model_node_inventory():
        """Show bounded Agent-discovered paths; never infer verified/installed PT."""
        return service().list_mother_model_node_inventory()

    @router.post('/api/v63/base-models/assets/{asset_id}/install', status_code=202)
    def install_mother_model_to_node(asset_id: str, payload: Dict[str, Any]):
        """Queue an Agent-owned installation; never write to a remote path in Web."""
        return service().install_mother_model_to_node(asset_id, payload)

    @router.get('/api/v63/base-models/installations')
    def list_mother_model_installations(cursor: Optional[str]=None):
        """Project only authoritative task status and same-generation Agent receipt."""
        return service().list_mother_model_installations(cursor)

    @router.post('/api/v63/base-models/installations/{task_id}/cancel')
    def cancel_mother_model_installation(task_id: str):
        return service().cancel_mother_model_installation(task_id)

    @router.post('/api/v63/base-models/discovered/register')
    def register_discovered_mother_model(payload: Dict[str, Any]):
        """Import an *exact cached controller discovery result* into managed assets.

        This is an explicit user action. It cannot copy an arbitrary local path or
        treat an unverified remote heartbeat path as a training-ready checkpoint.
        """
        return service().register_discovered_mother_model(payload)

    @router.post('/api/v63/base-models/assets/{asset_id}/verify', status_code=202)
    def verify_mother_model_asset(asset_id: str):
        """Trigger a fenced, local sandbox probe; never deserialize in Web."""
        return service().verify_mother_model_asset(asset_id)

    @router.get('/api/base_models')
    def list_base_models(project_id: Optional[str]=None):
        """训练页基础模型下拉框。区分 Ultralytics 可训练权重和飞桨模型源。"""
        return service().list_base_models(project_id)

    return router


def create_runtime_catalog_router_5(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/paddle_env')
    def get_paddle_env():
        return service().get_paddle_env()

    @router.post('/api/paddle_env/select')
    def select_paddle_env(payload: PaddleEnvReq):
        return service().select_paddle_env(payload)

    @router.post('/api/paddle_env/test')
    def test_paddle_env(payload: PaddleEnvReq):
        return service().test_paddle_env(payload)

    @router.get('/api/paddle_env/algorithms')
    def list_paddle_env_algorithms():
        return service().list_paddle_env_algorithms()

    @router.post('/api/paddle_env/algorithms/scan')
    def scan_paddle_env_algorithms(payload: PaddleEnvReq):
        return service().scan_paddle_env_algorithms(payload)

    @router.post('/api/paddle_env/detect')
    def detect_paddle_env(payload: PaddleDetectReq):
        return service().detect_paddle_env(payload)

    @router.get('/api/train_servers')
    def list_train_servers():
        return service().list_train_servers()

    @router.post('/api/train_servers')
    def save_train_server(payload: TrainServerReq):
        return service().save_train_server(payload)

    @router.delete('/api/train_servers/{server_id}')
    def delete_train_server(server_id: str):
        return service().delete_train_server(server_id)

    @router.post('/api/train_servers/test')
    def test_train_server(payload: TrainServerReq):
        return service().test_train_server(payload)

    @router.post('/api/train_servers/{server_id}/test')
    def test_saved_train_server(server_id: str):
        """Explicitly probe a configured legacy target; no probe on list/read."""
        return service().test_saved_train_server(server_id)

    @router.get('/api/v62/training-devices')
    def training_devices():
        return service().training_devices()

    @router.get('/api/v62/gpu-resources')
    def gpu_resources():
        return service().gpu_resources()

    return router


def create_runtime_catalog_router_6(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/app_info')
    def v12_app_info():
        return service().v12_app_info()

    return router


def create_runtime_catalog_router_7(service: Callable[[], RuntimeCatalogService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v16/inference_envs')
    def v16_inference_envs():
        return service().v16_inference_envs()

    return router
