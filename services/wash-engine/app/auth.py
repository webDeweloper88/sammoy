from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import db
from .security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "login": row["login"],
        "role": row["role"],
        "display_name": row["display_name"],
        "must_change_password": bool(row.get("must_change_password", False)),
    }


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    with db() as conn:
        revoked = conn.execute(
            """
            SELECT 1
            FROM auth_revoked_tokens
            WHERE jti = %s AND expires_at > now()
            """,
            (jti,),
        ).fetchone()
        if revoked:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked")

        user = conn.execute(
            """
            SELECT id, login, role, display_name, password_hash, active,
                   must_change_password, auth_version
            FROM auth_users
            WHERE id = %s
            """,
            (int(user_id),),
        ).fetchone()

    if not user or not user["active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    if int(payload.get("auth_version") or 0) != int(user.get("auth_version") or 1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    return user


def require_role(*roles: str):
    def dependency(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        if user.get("must_change_password"):
            raise HTTPException(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "Password change required",
            )
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return dependency


def token_exp_from_payload(credentials: HTTPAuthorizationCredentials) -> datetime:
    payload = decode_access_token(credentials.credentials)
    return datetime.fromtimestamp(int(payload["exp"]), UTC)
