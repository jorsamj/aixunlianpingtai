"""HTTP adapters registered at their original positions to retain matching order."""
from typing import Callable, Optional
from fastapi import APIRouter
from .training_evaluation_service import TrainingEvaluationService
from .training_evaluation_contracts import EvaluationReviewReq, FreezeReviewedMiningReq, FreezeSupplementFeedbackCandidatesReq, HardSampleMiningCreateReq



def create_training_evaluation_router_1(service: Callable[[], TrainingEvaluationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/images/{image_name}')
    def evaluation_diagnostic_image_v1(project_id: str, algorithm_id: str, version_id: str, image_name: str, expected_evaluation_id: str='', expected_image_id: str='', expected_sha256: str=''):
        """Read-only frozen Test Split preview, never a source of training candidates.

        Authorize the version/evaluation and the exact snapshot/material digest
        before returning bytes. Historical or unbound test snapshots fail closed.
        """
        return service().evaluation_diagnostic_image_v1(project_id, algorithm_id, version_id, image_name, expected_evaluation_id, expected_image_id, expected_sha256)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/trust')
    def evaluation_trust_analysis(project_id: str, algorithm_id: str, version_id: str, offset: int=0, limit: int=20):
        return service().evaluation_trust_analysis(project_id, algorithm_id, version_id, offset, limit)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/samples')
    def evaluation_sample_page(project_id: str, algorithm_id: str, version_id: str, offset: int=0, limit: int=24, issue: str='', class_id: Optional[int]=None, sort: str='severity', reader_view: bool=False):
        return service().evaluation_sample_page(project_id, algorithm_id, version_id, offset, limit, issue, class_id, sort, reader_view)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/report')
    def advanced_evaluation_report(project_id: str, algorithm_id: str, version_id: str, reader_view: bool=False, section: str='summary', offset: int=0, limit: int=20, class_id: Optional[int]=None):
        return service().advanced_evaluation_report(project_id, algorithm_id, version_id, reader_view, section, offset, limit, class_id)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/compare/{other_version_id}')
    def compare_version_evaluation(project_id: str, algorithm_id: str, version_id: str, other_version_id: str, reader_view: bool=False, offset: int=0, limit: int=20):
        return service().compare_version_evaluation(project_id, algorithm_id, version_id, other_version_id, reader_view, offset, limit)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/deep-compare/{other_version_id}')
    def deep_compare_evaluation(project_id: str, algorithm_id: str, version_id: str, other_version_id: str, offset: int=0, limit: int=24, category: str=''):
        return service().deep_compare_evaluation(project_id, algorithm_id, version_id, other_version_id, offset, limit, category)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining/{task_id}/reviewed')
    def preview_reviewed_mining(project_id: str, algorithm_id: str, version_id: str, task_id: str, offset: int=0, limit: int=24):
        return service().preview_reviewed_mining(project_id, algorithm_id, version_id, task_id, offset, limit)

    @router.post('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining/{task_id}/adopt')
    def adopt_reviewed_mining(project_id: str, algorithm_id: str, version_id: str, task_id: str, payload: FreezeReviewedMiningReq):
        return service().adopt_reviewed_mining(project_id, algorithm_id, version_id, task_id, payload)

    @router.post('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/review')
    def review_evaluation_sample(project_id: str, algorithm_id: str, version_id: str, payload: EvaluationReviewReq):
        return service().review_evaluation_sample(project_id, algorithm_id, version_id, payload)

    @router.get('/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/evaluation/review')
    def read_evaluation_sample_review(project_id: str, algorithm_id: str, version_id: str, expected_evaluation_id: str, image_id: str):
        return service().read_evaluation_sample_review(project_id, algorithm_id, version_id, expected_evaluation_id, image_id)

    return router


def create_training_evaluation_router_2(service: Callable[[], TrainingEvaluationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v63/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/supplement-data-candidates')
    def list_supplement_feedback_candidates(project_id: str, algorithm_id: str, version_id: str):
        return service().list_supplement_feedback_candidates(project_id, algorithm_id, version_id)

    @router.post('/api/v63/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/supplement-data-candidates/freeze')
    def freeze_supplement_feedback_candidates(project_id: str, algorithm_id: str, version_id: str, payload: FreezeSupplementFeedbackCandidatesReq):
        return service().freeze_supplement_feedback_candidates(project_id, algorithm_id, version_id, payload)

    return router


def create_training_evaluation_router_3(service: Callable[[], TrainingEvaluationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v64/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining/eligible')
    def eligible_hard_sample_materials(project_id: str, algorithm_id: str, version_id: str, limit: int=100):
        """A bounded read-only filter over canonical Materials and frozen Test truth.

        This is not a separate candidate database. Final POST revalidates everything.
        """
        return service().eligible_hard_sample_materials(project_id, algorithm_id, version_id, limit)

    @router.post('/api/v64/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining', status_code=202)
    def create_hard_sample_mining(project_id: str, algorithm_id: str, version_id: str, payload: HardSampleMiningCreateReq):
        return service().create_hard_sample_mining(project_id, algorithm_id, version_id, payload)

    return router


def create_training_evaluation_router_4(service: Callable[[], TrainingEvaluationService]) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v49/projects/{project_id}/algorithms/{algorithm_id}/report')
    def v49_algorithm_report(project_id: str, algorithm_id: str, lightweight: bool=False):
        return service().v49_algorithm_report(project_id, algorithm_id, lightweight)

    return router
