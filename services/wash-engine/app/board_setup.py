"""Unfinished-installer board selection through fixed host actions."""
from typing import Literal
from uuid import UUID
import httpx
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict
from .admin_service import require_idle
from .wash_logic import wash_runtime


class BoardChoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    board_id:Literal['cubie-a7a','cl3566-a-e']
    request_id:UUID


def host_board():
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds='/run/sammoy2-admin/system.sock'),timeout=5) as client:
            r=client.get('http://localhost/board');r.raise_for_status();return r.json()
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'Board detection service is unavailable') from None


def request_board(payload,commissioning):
    if commissioning.get('complete'):raise HTTPException(403,'Commissioning is closed')
    with wash_runtime.lock:
        require_idle(wash_runtime)
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds='/run/sammoy2-admin/system.sock'),timeout=5) as client:
                r=client.post('http://localhost/actions',json={'action':'board-'+payload.board_id,'request_id':str(payload.request_id),'actor':'installer'})
                if r.status_code!=202:raise HTTPException(409,'Another maintenance operation is pending')
                data=r.json()
                return {k:data.get(k) for k in ('ok','request_id','action','status')}
        except (httpx.HTTPError,ValueError):
            raise HTTPException(503,'Board selection service is unavailable') from None
