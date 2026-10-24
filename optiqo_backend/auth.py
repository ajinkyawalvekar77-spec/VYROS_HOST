"""Firebase ID-token verification for protected Optiqo API routes."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin.exceptions import FirebaseError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import DefaultCredentialsError

from .config import get_settings


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    uid: str
    email: str


LOCAL_DEVELOPMENT_USER = AuthenticatedUser(
    uid="local-development",
    email="local@optiqo.test",
)


def _is_local_development_request(request: Request) -> bool:
    if not get_settings().allow_local_development_access or request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _get_firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app("optiqo")
    except ValueError:
        options: dict[str, str] = {}
        project_id = get_settings().firebase_project_id
        if project_id:
            options["projectId"] = project_id
        try:
            return firebase_admin.initialize_app(name="optiqo", options=options or None)
        except ValueError as exc:
            try:
                return firebase_admin.get_app("optiqo")
            except ValueError:
                raise RuntimeError("Firebase Admin could not initialize its app.") from exc


def verify_firebase_token(token: str) -> dict[str, Any]:
    try:
        app = _get_firebase_app()
    except (DefaultCredentialsError, FirebaseError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "firebase_verification_unavailable",
                "message": "Firebase token verification is unavailable. Configure Application Default Credentials for the backend service account.",
            },
        ) from exc

    try:
        return firebase_auth.verify_id_token(token, app=app, check_revoked=True)
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.UserDisabledError,
        firebase_auth.UserNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_firebase_token", "message": "The Firebase ID token is invalid, expired, or revoked."},
        ) from exc
    except (DefaultCredentialsError, FirebaseError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "firebase_verification_unavailable",
                "message": "Firebase token verification is unavailable. Configure Application Default Credentials for the backend service account.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_firebase_token", "message": "The Firebase ID token is invalid or expired."},
        ) from exc


def _user_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    uid = claims.get("uid") or claims.get("sub")
    email = claims.get("email")
    if not isinstance(uid, str) or not uid or not isinstance(email, str) or not email:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_firebase_token", "message": "The Firebase token does not contain a valid user identity."},
        )
    if claims.get("email_verified") is not True:
        raise HTTPException(
            status_code=403,
            detail={"code": "email_not_verified", "message": "Verify the email address associated with this Firebase account before using Optiqo."},
        )
    return AuthenticatedUser(uid=uid, email=email)


def require_verified_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    if _is_local_development_request(request):
        return LOCAL_DEVELOPMENT_USER
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "A Firebase ID token is required for this endpoint."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_from_claims(verify_firebase_token(credentials.credentials))


def optional_verified_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser | None:
    if _is_local_development_request(request):
        return LOCAL_DEVELOPMENT_USER
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "A Firebase ID token is required for this endpoint."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_from_claims(verify_firebase_token(credentials.credentials))
