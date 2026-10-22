"""Authenticated, freshly confirmed local system maintenance."""
import time
from typing import Annotated, Literal
from uuid import UUID
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from .auth import bearer, require_role
from .security import decode_access_token
from .admin_service import require_idle, all_off
from .config import settings
from .wash_logic import wash_runtime

router = APIRouter(prefix='/api/system')


class HardwareRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


def request_hardware_apply(payload, commissioning):
    if commissioning.get('complete'):
        raise HTTPException(403, 'Commissioning access is closed')
    with wash_runtime.lock:
        require_idle(wash_runtime)
        transport = httpx.HTTPTransport(uds='/run/sammoy2-admin/system.sock')
        try:
            with httpx.Client(transport=transport, timeout=5) as client:
                response = client.post('http://localhost/actions', json={
                    'action': 'hardware', 'request_id': str(payload.request_id),
                    'actor': 'installer'})
                if response.status_code != 202:
                    raise HTTPException(409, 'Another maintenance operation is pending')
                data = response.json()
                return {key: data.get(key) for key in ('ok', 'request_id', 'action', 'status')}
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'System maintenance service is unavailable') from None


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['reboot', 'poweroff', 'settings', 'full']
    request_id: UUID
    confirmation: str
    cluster_isolated: bool = False


def validate_action(payload, user, issued_at, now):
    if not 0 <= now - issued_at <= 60:
        raise HTTPException(401, 'Confirm your password again')
    if payload.action in ('settings', 'full') and user['role'] != 'admin':
        raise HTTPException(403, 'Factory reset requires Admin')
    if payload.confirmation != payload.action.upper():
        raise HTTPException(400, 'Confirmation does not match')
    if payload.action == 'full' and not payload.cluster_isolated:
        raise HTTPException(409, 'Disconnect other posts from this wallet before a full reset')


@router.post('/actions')
def system_action(payload: Action,
                  user: Annotated[dict, Depends(require_role('owner', 'admin'))],
                  credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]):
    claims = decode_access_token(credentials.credentials)
    validate_action(payload, user, int(claims.get('iat', 0)), time.time())
    with wash_runtime.lock:
        require_idle(wash_runtime)
        # A missing relay module must not prevent orderly host poweroff. Reset,
        # however, requires positive OFF readback before deleting any data.
        if payload.action in ('settings', 'full'):
            from .db import db
            from .system_reset import check_ready
            try:
                with db() as connection:
                    check_ready(connection, payload.action)
            except RuntimeError as error:
                raise HTTPException(409, str(error)) from None
            all_off(wash_runtime, settings.io_helper_url)
        transport = httpx.HTTPTransport(uds='/run/sammoy2-admin/system.sock')
        try:
            with httpx.Client(transport=transport, timeout=5) as client:
                response = client.post('http://localhost/actions', json={
                    'action': payload.action, 'request_id': str(payload.request_id),
                    'actor': user['login']})
                if response.status_code != 202:
                    raise HTTPException(409, 'Another maintenance operation is pending')
                return response.json()
        except httpx.HTTPError:
            raise HTTPException(503, 'System maintenance service is unavailable') from None


@router.get('/actions/{request_id}')
def system_action_status(request_id:UUID):
    # The random request UUID is a read-only receipt. Reset revokes the login
    # token, so watching this receipt cannot depend on the old credentials.
    from fastapi.responses import JSONResponse
    transport=httpx.HTTPTransport(uds='/run/sammoy2-admin/system.sock')
    try:
        with httpx.Client(transport=transport,timeout=3) as client:
            response=client.get('http://localhost/actions/'+str(request_id))
            if response.status_code==404:raise HTTPException(404,'Maintenance operation not found')
            response.raise_for_status()
            data=response.json()
        return JSONResponse({key:data.get(key) for key in ('ok','request_id','action','status')},headers={'Cache-Control':'no-store'})
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'System maintenance status is unavailable') from None
