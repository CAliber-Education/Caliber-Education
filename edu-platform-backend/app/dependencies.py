from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from supabase import Client

from app.core.security import decode_token
from app.core.database import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Client = Depends(get_db),
) -> dict:
    """Decodes the JWT and returns the Supabase profiles row for the user."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        session_id: str = payload.get("session_id")
        if not user_id:
            raise ValueError("Token missing sub claim")
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = db.table("profiles").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
        
    # Enforce strictly 1 concurrent active session   
    if session_id and result.data.get("active_session_id") and result.data.get("active_session_id") != session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session concurrently expired: you have logged into this account from another device."
        )
        
    return result.data


ADMIN_ROLES = {"admin", "super_admin"}
MENTOR_ROLES = {"mentor", "admin", "super_admin"}
# mcq_editor is deliberately NOT in ADMIN_ROLES or MENTOR_ROLES: it must
# never pass require_admin/require_mentor, so every existing endpoint stays
# closed to it by default. It is only let through by require_mcq_author.
MCQ_AUTHOR_ROLES = {"mcq_editor", "admin", "super_admin"}


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Raises 403 if the authenticated user is not an admin or super_admin.

    No environment-based bypass: this check must always run. (A dev-mode
    bypass here previously shipped as the app's default and opened every
    admin endpoint to any logged-in student.)
    """
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Raises 403 unless the authenticated user is super_admin.

    Use this specifically for role-assignment endpoints (granting admin/
    mentor access) — regular admins can manage content/payments but must
    not be able to promote themselves or others further.
    """
    if current_user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return current_user


def require_mentor(current_user: dict = Depends(get_current_user)) -> dict:
    """Raises 403 unless the authenticated user is a mentor, admin, or super_admin."""
    if current_user.get("role") not in MENTOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mentor access required",
        )
    return current_user


def require_mcq_author(current_user: dict = Depends(get_current_user)) -> dict:
    """Raises 403 unless the user may author MCQ papers: an mcq_editor, admin,
    or super_admin.

    This only answers "may this person use the paper-authoring endpoints at
    all". An mcq_editor is additionally limited to papers they created —
    that per-paper check lives with the endpoints in app/routers/admin.py,
    since it needs the paper row.
    """
    if current_user.get("role") not in MCQ_AUTHOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MCQ authoring access required",
        )
    return current_user
