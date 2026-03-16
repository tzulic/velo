"""Tests for auxiliary model routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from velo.agent.auxiliary import AuxiliaryRouter
from velo.providers.base import LLMProvider


class TestAuxiliaryRouter:
    def test_unconfigured_task_returns_main(self):
        config = MagicMock()
        config.auxiliary = MagicMock()
        config.auxiliary.compression = MagicMock(model="", provider="auto")
        main_provider = AsyncMock(spec=LLMProvider)
        router = AuxiliaryRouter(config, main_provider=main_provider, main_model="claude-opus")
        provider, model = router.get_provider_sync("compression")
        assert provider is main_provider
        assert model == "claude-opus"

    def test_configured_task_returns_override(self):
        config = MagicMock()
        config.auxiliary = MagicMock()
        config.auxiliary.compression = MagicMock(model="gemini/gemini-flash", provider="gemini")
        aux_provider = AsyncMock(spec=LLMProvider)
        main_provider = AsyncMock(spec=LLMProvider)
        router = AuxiliaryRouter(
            config,
            main_provider=main_provider,
            main_model="claude-opus",
            provider_factory=lambda name, model: aux_provider,
        )
        provider, model = router.get_provider_sync("compression")
        assert provider is aux_provider
        assert model == "gemini/gemini-flash"

    def test_unknown_task_returns_main(self):
        config = MagicMock()
        config.auxiliary = MagicMock(spec=[])
        main_provider = AsyncMock(spec=LLMProvider)
        router = AuxiliaryRouter(config, main_provider=main_provider, main_model="claude")
        provider, model = router.get_provider_sync("unknown_task")
        assert provider is main_provider

    def test_factory_failure_falls_back_to_main(self):
        config = MagicMock()
        config.auxiliary = MagicMock()
        config.auxiliary.vision = MagicMock(model="some-model", provider="bad")
        main_provider = AsyncMock(spec=LLMProvider)
        router = AuxiliaryRouter(
            config,
            main_provider=main_provider,
            main_model="claude",
            provider_factory=lambda n, m: (_ for _ in ()).throw(Exception("fail")),
        )
        provider, model = router.get_provider_sync("vision")
        assert provider is main_provider
