"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable
from fastapi import APIRouter
from .ai_configuration_service import AiConfigurationService
from .ai_configuration_contracts import PrelabelServiceReq, V35CoordinateConfirmationReq, V35CoordinateSampleReq, V35ModelAvailabilityReq, V35ModelConfigReq, V35PromptPreviewReq, V35PromptTemplateReq



def create_ai_configuration_router_1(service: Callable[[], AiConfigurationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/prelabel_services')
    def list_prelabel_services():
        return service().list_prelabel_services()

    @router.post('/api/prelabel_services')
    def save_prelabel_service(payload: PrelabelServiceReq):
        return service().save_prelabel_service(payload)

    @router.delete('/api/prelabel_services/{service_id}')
    def delete_prelabel_service(service_id: str):
        return service().delete_prelabel_service(service_id)

    @router.post('/api/prelabel_services/test')
    def test_prelabel_service(payload: PrelabelServiceReq):
        return service().test_prelabel_service(payload)

    return router


def create_ai_configuration_router_2(service: Callable[[], AiConfigurationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v35/model-configs')
    def v35_list_model_configs():
        return service().v35_list_model_configs()

    @router.post('/api/v35/model-configs')
    def v35_save_model_config(payload: V35ModelConfigReq):
        return service().v35_save_model_config(payload)

    @router.put('/api/v35/model-configs/{config_id}')
    def v35_update_model_config(config_id: str, payload: V35ModelConfigReq):
        return service().v35_update_model_config(config_id, payload)

    @router.post('/api/v35/model-configs/{config_id}/capacity-check')
    def v35_check_model_capacity(config_id: str):
        """Read server evidence only; connection/image checks remain separate."""
        return service().v35_check_model_capacity(config_id)

    @router.delete('/api/v35/model-configs/{config_id}')
    def v35_delete_model_config(config_id: str):
        return service().v35_delete_model_config(config_id)

    @router.patch('/api/v35/model-configs/{config_id}/availability')
    def v35_set_model_availability(config_id: str, payload: V35ModelAvailabilityReq):
        """Change availability without invalidating a saved coordinate proof."""
        return service().v35_set_model_availability(config_id, payload)

    @router.post('/api/v35/model-configs/test')
    def v35_test_model_config(payload: V35ModelConfigReq):
        return service().v35_test_model_config(payload)

    @router.post('/api/v35/model-configs/{config_id}/test-annotation')
    def v35_test_saved_model_annotation(config_id: str):
        return service().v35_test_saved_model_annotation(config_id)

    @router.post('/api/v35/model-configs/{config_id}/verify-coordinates')
    def v35_verify_model_coordinates(config_id: str, payload: V35CoordinateSampleReq):
        return service().v35_verify_model_coordinates(config_id, payload)

    @router.post('/api/v35/model-configs/{config_id}/confirm-coordinates')
    def v35_confirm_model_coordinates(config_id: str, payload: V35CoordinateConfirmationReq):
        return service().v35_confirm_model_coordinates(config_id, payload)

    @router.get('/api/v35/prompt-templates')
    def v35_list_prompt_templates():
        return service().v35_list_prompt_templates()

    @router.post('/api/v35/prompt-templates')
    def v35_save_prompt_template(payload: V35PromptTemplateReq):
        return service().v35_save_prompt_template(payload)

    @router.put('/api/v35/prompt-templates/{template_id}')
    def v35_update_prompt_template(template_id: str, payload: V35PromptTemplateReq):
        return service().v35_update_prompt_template(template_id, payload)

    @router.delete('/api/v35/prompt-templates/{template_id}')
    def v35_delete_prompt_template(template_id: str):
        return service().v35_delete_prompt_template(template_id)

    @router.post('/api/v35/prompt-templates/preview')
    def v35_preview_prompt_template(payload: V35PromptPreviewReq):
        return service().v35_preview_prompt_template(payload)

    return router
