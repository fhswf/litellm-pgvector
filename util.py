import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config import settings
from httpx import AsyncClient

security = HTTPBearer()

async def get_litellm_vkey_info(credentials: HTTPAuthorizationCredentials = Depends(security)):
    litellm_api_key = settings.litellm_api_key
    litellm_host = settings.embedding.base_url
    provided_litellm_vkey = credentials.credentials

    # LiteLLM's master key can access all stores when calling this service
    # directly. It is deliberately not accepted as the owner of a new store.
    if litellm_api_key and hmac.compare_digest(provided_litellm_vkey, litellm_api_key):
        return {"key": provided_litellm_vkey, "info": {}, "is_admin": True}

    async with AsyncClient() as client:
        response = await client.get(
            f"{litellm_host.rstrip('/')}/key/info",
            params={"key": provided_litellm_vkey},
            headers={"Authorization": f"Bearer {litellm_api_key}"}
            )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid API key")
        key_info = response.json()
        user_role = str(
            key_info.get("info", {}).get("user_role")
            or key_info.get("user_role", "")
        ).lower()
        key_info["is_admin"] = user_role.rsplit(".", 1)[-1] == "proxy_admin"
        return key_info


def is_litellm_admin(litellm_vkey_info: dict) -> bool:
    return bool(litellm_vkey_info.get("is_admin"))


def get_litellm_user_id(litellm_vkey_info: dict) -> str:
    user_id = litellm_vkey_info.get("info", {}).get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="A LiteLLM user ID is required for this operation",
        )
    return str(user_id)


def scope_to_litellm_user(statement, model, litellm_vkey_info: dict):
    if is_litellm_admin(litellm_vkey_info):
        return statement
    return statement.where(model.user_id == get_litellm_user_id(litellm_vkey_info))
