"""Provider selection for LiteLLM vector-store registrations."""

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from config import Settings, settings
from litellm_registry import delete_registered_vector_store, register_vector_store


class ProviderSettingTests(unittest.TestCase):
    def test_provider_is_read_from_environment(self):
        with patch.dict(os.environ, {"VECTOR_STORE_PROVIDER": "openai"}):
            configured = Settings(_env_file=None)
        self.assertEqual(configured.vector_store_provider, "openai")

    def test_unsupported_provider_is_rejected(self):
        with patch.dict(os.environ, {"VECTOR_STORE_PROVIDER": "azure"}):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_user_scoped_registration_requires_explicit_setting(self):
        with patch.dict(os.environ, {"LITELLM_USER_SCOPED_VECTOR_STORES": "true"}):
            configured = Settings(_env_file=None)
        self.assertTrue(configured.litellm_user_scoped_vector_stores)


class RegistrationProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_uses_provider_and_matching_api_base(self):
        cases = (
            ("pg_vector", "http://pgvector.test/", "http://pgvector.test"),
            ("openai", "http://pgvector.test/", "http://pgvector.test/v1"),
            ("openai", "http://pgvector.test/v1/", "http://pgvector.test/v1"),
        )
        for provider, configured_base, expected_base in cases:
            with self.subTest(provider=provider, configured_base=configured_base):
                client = AsyncMock()
                client.__aenter__.return_value = client
                client.post.return_value = httpx.Response(200)

                with (
                    patch.object(settings, "vector_store_provider", provider),
                    patch.object(settings, "vector_store_api_base", configured_base),
                    patch.object(settings, "litellm_vector_store_registry_api_key", "registry-key"),
                    patch.object(settings, "litellm_user_scoped_vector_stores", False),
                    patch.object(settings.embedding, "base_url", "http://litellm.test"),
                    patch("litellm_registry.httpx.AsyncClient", return_value=client),
                    patch("litellm_registry._get_private_registry_team_id", new_callable=AsyncMock),
                    patch("litellm_registry._grant_store_to_owner_key", new_callable=AsyncMock) as grant,
                ):
                    await register_vector_store(
                        vector_store_id="store-id",
                        name="test store",
                        owner_key="owner-key",
                        owner_info={"user_id": "owner"},
                    )

                request = client.post.await_args
                self.assertEqual(request.args[0], "http://litellm.test/vector_store/new")
                self.assertEqual(request.kwargs["json"]["custom_llm_provider"], provider)
                self.assertEqual(request.kwargs["json"]["litellm_params"], {
                    "api_base": expected_base,
                    "api_key": "owner-key",
                })
                self.assertEqual(request.kwargs["headers"], {
                    "Authorization": "Bearer registry-key"
                })
                grant.assert_awaited_once()

    async def test_team_store_registration_uses_team_key(self):
        await self._assert_owner_registration(
            owner_info={"user_id": "creator", "team_id": "team-a"},
            user_scoped=False,
        )

    async def test_user_store_registration_uses_user_key_when_enabled(self):
        await self._assert_owner_registration(
            owner_info={"user_id": "creator"},
            user_scoped=True,
        )

    async def _assert_owner_registration(self, owner_info, user_scoped):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200)
        with (
            patch.object(settings, "vector_store_api_base", "http://pgvector.test"),
            patch.object(settings, "litellm_user_scoped_vector_stores", user_scoped),
            patch.object(settings.embedding, "base_url", "http://litellm.test"),
            patch("litellm_registry.httpx.AsyncClient", return_value=client),
            patch("litellm_registry._get_private_registry_team_id", new_callable=AsyncMock),
            patch("litellm_registry._grant_store_to_owner_key", new_callable=AsyncMock) as grant,
        ):
            await register_vector_store(
                vector_store_id="store-id",
                name="test store",
                owner_key="owner-key",
                owner_info=owner_info,
            )
        self.assertEqual(client.post.await_args.kwargs["headers"], {
            "Authorization": "Bearer owner-key"
        })
        grant.assert_not_awaited()

    async def test_deletion_uses_admin_key_for_any_owner(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200)
        with (
            patch.object(settings, "litellm_api_key", "admin-key"),
            patch.object(settings.embedding, "base_url", "http://litellm.test"),
            patch("litellm_registry.httpx.AsyncClient", return_value=client),
        ):
            await delete_registered_vector_store("store-id")
        self.assertEqual(client.post.await_args.kwargs["headers"], {
            "Authorization": "Bearer admin-key"
        })


if __name__ == "__main__":
    unittest.main()
