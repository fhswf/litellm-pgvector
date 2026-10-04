from typing import Any

import httpx

from config import settings


class LiteLLMRegistryError(RuntimeError):
    """A registration or access-control operation failed in LiteLLM."""


def _litellm_base_url() -> str:
    return settings.embedding.base_url.rstrip("/")


def _admin_headers() -> dict[str, str]:
    if not settings.litellm_api_key:
        raise LiteLLMRegistryError("LITELLM_API_KEY is not configured")
    return {"Authorization": f"Bearer {settings.litellm_api_key}"}


def _registry_headers() -> dict[str, str]:
    if not settings.litellm_vector_store_registry_api_key:
        raise LiteLLMRegistryError(
            "LITELLM_VECTOR_STORE_REGISTRY_API_KEY is not configured"
        )
    return {
        "Authorization": (
            f"Bearer {settings.litellm_vector_store_registry_api_key}"
        )
    }


async def _get_key_info(api_key: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{_litellm_base_url()}/key/info",
                params={"key": api_key},
                headers=_admin_headers(),
            )
    except httpx.HTTPError as exc:
        raise LiteLLMRegistryError("Could not contact LiteLLM key-info API") from exc

    if response.status_code != 200:
        raise LiteLLMRegistryError(
            f"LiteLLM key-info API returned HTTP {response.status_code}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise LiteLLMRegistryError("LiteLLM returned invalid key-info data") from exc


async def _get_private_registry_team_id(owner_info: dict[str, Any]) -> str:
    if not settings.litellm_vector_store_registry_api_key:
        raise LiteLLMRegistryError(
            "LITELLM_VECTOR_STORE_REGISTRY_API_KEY is not configured"
        )
    expected_team_id = settings.litellm_vector_store_registry_team_id
    if not expected_team_id:
        raise LiteLLMRegistryError(
            "LITELLM_VECTOR_STORE_REGISTRY_TEAM_ID is not configured"
        )

    registry_info = await _get_key_info(
        settings.litellm_vector_store_registry_api_key
    )
    actual_team_id = registry_info.get("info", {}).get("team_id")
    if not actual_team_id or actual_team_id != expected_team_id:
        raise LiteLLMRegistryError(
            "The LiteLLM registry key is not assigned to the configured private team"
        )

    owner_team_id = owner_info.get("team_id")
    if owner_team_id and owner_team_id == actual_team_id:
        raise LiteLLMRegistryError(
            "The store owner key cannot belong to the private registry team"
        )
    return str(actual_team_id)


async def _list_stores_accessible_to_key(api_key: str) -> set[str]:
    endpoint = f"{_litellm_base_url()}/vector_store/list"
    headers = {"Authorization": f"Bearer {api_key}"}
    accessible_ids: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            page = 1
            while True:
                response = await client.get(
                    endpoint,
                    params={"page": page, "page_size": 100},
                    headers=headers,
                )
                if response.status_code != 200:
                    raise LiteLLMRegistryError(
                        "Could not list the user's existing LiteLLM vector stores "
                        f"(HTTP {response.status_code})"
                    )
                payload = response.json()
                for store in payload.get("data", []):
                    vector_store_id = store.get("vector_store_id")
                    if vector_store_id:
                        accessible_ids.add(str(vector_store_id))

                total_pages = int(payload.get("total_pages", page))
                if page >= total_pages:
                    return accessible_ids
                page += 1
    except httpx.HTTPError as exc:
        raise LiteLLMRegistryError(
            "Could not contact LiteLLM vector-store list API"
        ) from exc
    except ValueError as exc:
        raise LiteLLMRegistryError(
            "LiteLLM returned invalid vector-store list data"
        ) from exc


async def _grant_store_to_owner_key(
    *,
    owner_key: str,
    owner_info: dict[str, Any],
    vector_store_id: str,
) -> None:
    accessible_ids = await _list_stores_accessible_to_key(owner_key)
    permission = owner_info.get("object_permission") or {}
    if isinstance(permission, str):
        try:
            import json

            permission = json.loads(permission)
        except ValueError as exc:
            raise LiteLLMRegistryError(
                "LiteLLM returned invalid key object permissions"
            ) from exc
    if not isinstance(permission, dict):
        raise LiteLLMRegistryError("LiteLLM returned invalid key object permissions")

    allowed_ids = permission.get("vector_stores") or []
    if not isinstance(allowed_ids, list):
        raise LiteLLMRegistryError("LiteLLM returned invalid vector-store permissions")
    allowed_ids = {str(store_id) for store_id in allowed_ids}
    allowed_ids.update(accessible_ids)
    allowed_ids.add(vector_store_id)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{_litellm_base_url()}/key/update",
                headers=_admin_headers(),
                json={
                    "key": owner_key,
                    "object_permission": {
                        "vector_stores": sorted(allowed_ids)
                    },
                },
            )
    except httpx.HTTPError as exc:
        raise LiteLLMRegistryError("Could not update LiteLLM key permissions") from exc

    if response.status_code != 200:
        raise LiteLLMRegistryError(
            f"LiteLLM key-permission update returned HTTP {response.status_code}"
        )


async def register_vector_store(
    *,
    vector_store_id: str,
    name: str,
    owner_key: str,
    owner_info: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Register a private vector store and allow only its owner's key."""
    if not settings.vector_store_api_base:
        raise LiteLLMRegistryError("VECTOR_STORE_API_BASE is not configured")
    await _get_private_registry_team_id(owner_info)

    provider = settings.vector_store_provider
    api_base = settings.vector_store_api_base.rstrip("/")
    if api_base.endswith("/v1"):
        api_base = api_base[:-3]
    if provider == "openai":
        api_base = f"{api_base}/v1"

    request_body = {
        "vector_store_id": vector_store_id,
        "custom_llm_provider": provider,
        "vector_store_name": name,
        "vector_store_metadata": metadata or {},
        "litellm_params": {
            "api_base": api_base,
            "api_key": owner_key,
        },
    }

    registered = False
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{_litellm_base_url()}/vector_store/new",
                headers=_registry_headers(),
                json=request_body,
            )
        if response.status_code not in (200, 201):
            raise LiteLLMRegistryError(
                f"LiteLLM vector-store registration returned HTTP {response.status_code}"
            )
        registered = True
        await _grant_store_to_owner_key(
            owner_key=owner_key,
            owner_info=owner_info,
            vector_store_id=vector_store_id,
        )
    except httpx.HTTPError as exc:
        error = LiteLLMRegistryError("Could not contact LiteLLM vector-store API")
        if registered:
            try:
                await delete_registered_vector_store(vector_store_id)
            except LiteLLMRegistryError:
                pass
        raise error from exc
    except Exception:
        if registered:
            try:
                await delete_registered_vector_store(vector_store_id)
            except LiteLLMRegistryError:
                pass
        raise


async def delete_registered_vector_store(vector_store_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{_litellm_base_url()}/vector_store/delete",
                headers=_registry_headers(),
                json={"vector_store_id": vector_store_id},
            )
    except httpx.HTTPError as exc:
        raise LiteLLMRegistryError(
            "Could not contact LiteLLM vector-store delete API"
        ) from exc

    # Treat deleting an unregistered/legacy store as idempotent success. The
    # application database remains the source of truth for whether it exists.
    if response.status_code not in (200, 404):
        raise LiteLLMRegistryError(
            f"LiteLLM vector-store deletion returned HTTP {response.status_code}"
        )
