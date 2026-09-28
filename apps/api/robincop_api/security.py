from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from .config import settings


def require_admin(x_admin_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="管理员身份验证失败")
