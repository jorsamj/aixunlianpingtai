from types import SimpleNamespace
import json
import app as api

def test_material_reader_projection_is_paged_safe_and_full_detail_is_explicit(monkeypatch):
    row={'id':'image','filename':'photo.jpg','width':640,'height':480,'stored_path':'/private/photo.jpg','object_key':'PRIVATE_KEY','content_sha256':'a'*64,'annotation_preview':[{'x1':1,'y1':2,'x2':50,'y2':60,'label':'smoke'}],'box_count':40}
    store=SimpleNamespace(list_page=lambda **kw:SimpleNamespace(items=[row],total=1,next_cursor=None),get_many=lambda ids:[row],current_revision=lambda:7)
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p});monkeypatch.setattr(api,'material_store',lambda p:store)
    monkeypatch.setattr(api,'read_annotation',lambda p,i:{'boxes':[{'x1':1,'y1':2,'x2':50,'y2':60,'label':'smoke'}]*40,'annotation_state':'annotated','version':9})
    listing=api.list_materials_v61('p',page=1,page_size=24,storage_source_id=None,label=None,reader_view=True)
    assert listing['project_id']=='p' and len(listing['items'])==1 and listing['items'][0]['boxes_preview_only'] is True
    assert 'PRIVATE_KEY' not in json.dumps(listing) and '/private' not in json.dumps(listing)
    detail=api.get_annotation('p','image',reader_view=True)
    assert detail['boxes_total']==40 and len(detail['annotation']['boxes'])==40 and detail['annotation']['boxes'][0]['x2']==50
    assert detail['boxes_truncated'] is False and detail['annotation']['annotation_version']==9
    assert '/private' not in json.dumps(detail)


def test_material_catalog_migration_preserves_original_openapi_surface():
    import re
    import app as application
    expected = [('get', '/api/v61/projects/{project_id}/materials', 'list_materials_v61'), ('get', '/api/v61/projects/{project_id}/materials/ids', 'list_material_ids_v61'), ('get', '/api/v61/projects/{project_id}/materials/status-counts', 'material_status_counts_v61'), ('get', '/api/v61/projects/{project_id}/materials/{image_id}/content', 'material_content_v61'), ('get', '/api/v61/projects/{project_id}/materials/{image_id}/content/thumbnail', 'material_thumbnail_v61'), ('get', '/api/projects/{project_id}/datasets', 'list_datasets'), ('post', '/api/projects/{project_id}/datasets', 'create_dataset'), ('put', '/api/projects/{project_id}/datasets/{dataset_id}', 'update_dataset'), ('get', '/api/projects/{project_id}/images', 'list_images'), ('get', '/api/v12/projects/{project_id}/labels', 'v12_list_labels'), ('get', '/api/v17/projects/{project_id}/datasets/{dataset_id}/quality', 'v17_dataset_quality'), ('get', '/api/v12/projects/{project_id}/datasets/{dataset_id}/summary', 'v12_dataset_summary')]
    schema = application.app.openapi()
    for method, path, name in expected:
        operation = schema["paths"][path][method]
        assert operation["operationId"] == re.sub(r"\W", "_", name + path) + "_" + method
    for method, path in (("post", "/api/projects/{project_id}/datasets"), ("put", "/api/projects/{project_id}/datasets/{dataset_id}")):
        assert schema["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/DatasetReq"
