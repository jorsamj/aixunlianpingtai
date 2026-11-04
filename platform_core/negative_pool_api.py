"""Routes use the host application's existing project/session authorization."""
import sqlite3
from fastapi import APIRouter, Body, HTTPException, Query
from .negative_pool import NegativePool


def create_negative_pool_router(material_store, get_project, public_material, usage_for_page=None):
    router = APIRouter(prefix='/api/v61/projects/{project_id}/negative-pool')

    def pool(project_id):
        get_project(project_id)
        return NegativePool(material_store(project_id))

    def algorithm_scope(project_id, algorithm_id):
        if not algorithm_id:
            return ''  # Legacy project-wide associations remain unconfirmed.
        store = material_store(project_id)
        from .algorithms import list_algorithms
        path = store.project_path / 'algorithms.json'
        if not (path.exists() or (path.parent / 'algorithms.sqlite3').exists()):
            raise ValueError('algorithm not found')
        identity = str(algorithm_id).strip()
        if not any(str(row.get('id')) == identity for row in list_algorithms(path)):
            raise ValueError('algorithm not found')
        return identity

    def invoke(call):
        try:
            return call()
        except (ValueError, sqlite3.IntegrityError) as error:
            raise HTTPException(400, str(error)) from error

    def filters(algorithm_id: str = '', query='', category_id: list[str] = Query(default=[]), label: list[str] = Query(default=[]), joined_days: int | None = None, joined_from: str | None = None, joined_to: str | None = None, review_status: str | None = None):
        return dict(algorithm_id=algorithm_id,query=query,category_ids=category_id,labels=label,joined_days=joined_days,joined_from=joined_from,joined_to=joined_to,review_status=review_status)

    from fastapi import Depends

    @router.get('')
    def listing(project_id: str, page: int = 1, page_size: int = 50, target_label: list[str] = Query(default=[]), selected: dict = Depends(filters)):
        get_project(project_id)
        invoke(lambda: algorithm_scope(project_id, selected.get('algorithm_id')))
        store = material_store(project_id)
        from .annotation_repository import AnnotationRepository
        annotations = AnnotationRepository(store.project_path)
        revisions = (store.current_revision(), annotations.current_revision(), pool(project_id).revision())
        result = invoke(lambda: pool(project_id).query(page=page,page_size=page_size,**selected))
        scope_kind = 'requested_labels'
        if selected.get('algorithm_id'):
            from .algorithms import list_algorithms
            store = material_store(project_id)
            algorithm = next(row for row in list_algorithms(store.project_path/'algorithms.json') if str(row.get('id')) == selected['algorithm_id'])
            if algorithm.get('current_version_id') or algorithm.get('versions'):
                from .training_label_tasks import resolve_training_label_contract
                contract = invoke(lambda: resolve_training_label_contract(store.project_path.parent.parent, store.project_path,
                    {'train_labels':target_label, 'framework':'ultralytics'}, algorithm,
                    require_positive_evidence=False, include_base_weight_digest=False))
                effective = contract['effective_label_codes']
                if target_label and set(target_label) != set(effective):
                    raise HTTPException(422, 'target scope must include the complete inherited algorithm schema')
                target_label = list(effective)
                scope_kind = 'algorithm_contract'
        result['effective_label_codes'] = list(target_label)
        result['scope_kind'] = scope_kind
        if target_label and selected.get('algorithm_id') and result['items']:
            from .negative_pool import negative_pool_qualification
            project = get_project(project_id) or {}
            allowed = {str(label.get('code') if isinstance(label, dict) else label) for label in project.get('labels') or []}
            if any(code not in allowed for code in target_label):
                raise HTTPException(422, 'unknown project target label')
            evidence = negative_pool_qualification(material_store(project_id), result['items'], target_label)
            for row in result['items']:
                row['negative_pool'].update(evidence[row['id']])
                row['negative_pool']['scope_kind'] = scope_kind
                if scope_kind == 'algorithm_contract':
                    row['negative_pool']['algorithm_qualification'] = row['negative_pool']['qualification']
        if usage_for_page and result['items']:
            usage = usage_for_page(project_id, result['items'])
            for row in result['items']:
                row['negative_pool']['training_usage'] = usage.get(row['id'], 'unknown')
        result['items']=[{**public_material(project_id,row),'negative_pool':row['negative_pool']} for row in result['items']]
        if revisions != (store.current_revision(), annotations.current_revision(), pool(project_id).revision()):
            raise HTTPException(409, 'material, annotation or pool changed; refresh before retry')
        result.update(material_revision=revisions[0], annotation_revision=revisions[1], negative_pool_revision=revisions[2])
        return result

    @router.get('/ids')
    def identities(project_id: str, selected: dict = Depends(filters)):
        get_project(project_id)
        invoke(lambda: algorithm_scope(project_id, selected.get('algorithm_id')))
        return invoke(lambda: pool(project_id).query(ids_only=True,**selected))

    @router.get('/categories')
    def categories(project_id: str, query: str = ''):
        return {'items':invoke(lambda: pool(project_id).categories(query))}

    @router.post('/categories')
    def create(project_id: str, body: dict = Body(...)):
        return invoke(lambda: pool(project_id).category(name=body.get('name')))

    @router.patch('/categories/{category_id}')
    def edit(project_id: str, category_id: str, body: dict = Body(...)):
        return invoke(lambda: pool(project_id).category(category_id,name=body.get('name'),enabled=body.get('enabled')))

    @router.delete('/categories/{category_id}')
    def delete(project_id: str, category_id: str):
        return invoke(lambda: pool(project_id).category(category_id,delete=True))

    @router.post('/members')
    def members(project_id: str, body: dict = Body(...)):
        return invoke(lambda: pool(project_id).members(body.get('image_ids',[]),action=body.get('action','add'),category_ids=body.get('category_ids',[]),algorithm_id=algorithm_scope(project_id,body.get('algorithm_id'))))

    @router.post('/upload-intent')
    def upload_intent(project_id: str, body: dict = Body(...)):
        """Post-upload positive intent or negative category association, not GT."""
        project = get_project(project_id)
        kind = str(body.get('sample_type') or '').strip()
        ids = body.get('image_ids', [])
        codes = body.get('label_codes', [])
        categories = body.get('category_ids', [])
        if kind == 'positive':
            if categories:
                raise HTTPException(422, 'positive samples use target labels, not negative categories')
            labels = project.get('labels') or []
            metadata = project.get('label_meta') or []
            allowed = {str(label.get('code') if isinstance(label, dict) else label)
                for index, label in enumerate(labels)
                if (index >= len(metadata) or not isinstance(metadata[index], dict)
                    or (str(metadata[index].get('status') or 'active').lower() == 'active'
                        and metadata[index].get('active') is not False))}
            if not isinstance(codes, list) or not codes or any(str(code) not in allowed for code in codes):
                raise HTTPException(422, 'unknown or inactive project label')
            return invoke(lambda: pool(project_id).set_positive_upload_intent(ids, codes))
        if kind == 'negative':
            if codes:
                raise HTTPException(422, 'negative samples use pool categories, not target labels')
            if not categories:
                raise HTTPException(422, 'negative samples require a category')
            return invoke(lambda: pool(project_id).members(ids, action='add', category_ids=categories,algorithm_id=algorithm_scope(project_id,body.get('algorithm_id'))))
        raise HTTPException(422, 'select positive or negative sample type')

    @router.post('/categories/assign')
    def assign(project_id: str, body: dict = Body(...)):
        return invoke(lambda: pool(project_id).members(body.get('image_ids',[]),action=body.get('action','add'),category_ids=body.get('category_ids',[]),categories_only=True))

    return router
