"""Routes use the host application's existing project/session authorization."""
import sqlite3
from fastapi import APIRouter, Body, HTTPException, Query
from .negative_pool import NegativePool


def create_negative_pool_router(material_store, get_project, public_material, usage_for_page=None):
    router = APIRouter(prefix='/api/v61/projects/{project_id}/negative-pool')

    def pool(project_id):
        get_project(project_id)
        return NegativePool(material_store(project_id))

    def invoke(call):
        try:
            return call()
        except (ValueError, sqlite3.IntegrityError) as error:
            raise HTTPException(400, str(error)) from error

    def filters(query='', category_id: list[str] = Query(default=[]), label: list[str] = Query(default=[]), joined_days: int | None = None, joined_from: str | None = None, joined_to: str | None = None, review_status: str | None = None):
        return dict(query=query,category_ids=category_id,labels=label,joined_days=joined_days,joined_from=joined_from,joined_to=joined_to,review_status=review_status)

    from fastapi import Depends

    @router.get('')
    def listing(project_id: str, page: int = 1, page_size: int = 50, selected: dict = Depends(filters)):
        result = invoke(lambda: pool(project_id).query(page=page,page_size=page_size,**selected))
        if usage_for_page and result['items']:
            usage = usage_for_page(project_id, result['items'])
            for row in result['items']:
                row['negative_pool']['training_usage'] = usage.get(row['id'], 'unknown')
        result['items']=[{**public_material(project_id,row),'negative_pool':row['negative_pool']} for row in result['items']]
        return result

    @router.get('/ids')
    def identities(project_id: str, selected: dict = Depends(filters)):
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
        return invoke(lambda: pool(project_id).members(body.get('image_ids',[]),action=body.get('action','add'),category_ids=body.get('category_ids',[])))

    @router.post('/categories/assign')
    def assign(project_id: str, body: dict = Body(...)):
        return invoke(lambda: pool(project_id).members(body.get('image_ids',[]),action=body.get('action','add'),category_ids=body.get('category_ids',[]),categories_only=True))

    return router
