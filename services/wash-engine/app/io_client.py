from typing import Any

import httpx
from fastapi import HTTPException, status

from .config import settings


async def io_request(path: str, method: str = "GET", json: dict[str, Any] | None = None) -> Any:
    url = f"{settings.io_helper_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.request(method, url, json=json)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Modbus I/O helper unavailable: {exc.__class__.__name__}",
        ) from exc
