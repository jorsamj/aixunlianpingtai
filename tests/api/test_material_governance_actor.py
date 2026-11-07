import pytest
from fastapi import HTTPException
from starlette.requests import Request


def request(cookie='', **headers):
    from platform_core.changlian_login_auth import SESSION_COOKIE_NAME
    values=[(str(k).encode(),str(v).encode()) for k,v in headers.items()]
    if cookie:values.append((b'cookie',f'{SESSION_COOKIE_NAME}={cookie}'.encode()))
    return Request({'type':'http','method':'POST','path':'/api/test','headers':values})


def helper(module):
    value=getattr(module,'_material_governance_actor',None)
    assert callable(value),'material deletion must use the original verified-session identity'
    return value


def test_anonymous_or_client_claimed_admin_cannot_manage_materials(client,monkeypatch):
    import app as m
    actor=helper(m);monkeypatch.setattr(m,'_auth_test_bypass_enabled',lambda:False)
    with pytest.raises(HTTPException) as error:actor(request(**{'x-username':'admin','x-is-admin':'true'}),'unknown')
    assert error.value.status_code==401


def test_every_authenticated_project_user_has_the_same_material_access(client,monkeypatch):
    import app as m
    project=client.post('/api/projects',json={'name':'uniform-login-governance'}).json()
    actor=helper(m);monkeypatch.setattr(m,'_auth_test_bypass_enabled',lambda:False)
    for username in ['alice','bob']:
        result=actor(request(m._CHANGLIAN_AUTH_SESSIONS.issue(username)),project['id'])
        assert result['actor_id']==username
        assert 'role' not in result and 'can_clear_project' not in result


def test_invalid_signed_session_does_not_gain_access_from_payload_or_headers(client,monkeypatch):
    import app as m
    actor=helper(m);monkeypatch.setattr(m,'_auth_test_bypass_enabled',lambda:False)
    cookie=m._CHANGLIAN_AUTH_SESSIONS.issue('alice')+'corrupted'
    with pytest.raises(HTTPException) as error:actor(request(cookie,**{'x-username':'alice'}),'unknown')
    assert error.value.status_code==401


def test_authenticated_actor_still_requires_a_real_accessible_project(client,monkeypatch):
    import app as m
    actor=helper(m);monkeypatch.setattr(m,'_auth_test_bypass_enabled',lambda:False)
    with pytest.raises(HTTPException) as error:actor(request(m._CHANGLIAN_AUTH_SESSIONS.issue('alice')),'missing_governance_project')
    assert error.value.status_code==404
