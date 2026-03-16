"""Auxiliary model routing for cost optimization on side tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

if TYPE_CHECKING:
    from velo.providers.base import LLMProvider


class AuxiliaryRouter:
    """Resolves provider + model for auxiliary tasks.

    Fallback chain: task-specific config -> main provider.

    Args:
        config: Root config.
        main_provider: The primary LLM provider.
        main_model: The primary model identifier.
        provider_factory: Optional factory to create providers from name+model.
    """

    def __init__(
        self,
        config: Any,
        main_provider: LLMProvider,
        main_model: str,
        provider_factory: Callable[[str, str], LLMProvider] | None = None,
    ) -> None:
        self._config = config
        self._main_provider = main_provider
        self._main_model = main_model
        self._factory = provider_factory
        self._cache: dict[str, tuple[LLMProvider, str]] = {}

    def get_provider_sync(self, task: str) -> tuple[LLMProvider, str]:
        """Return (provider, model) for the given task type.

        Args:
            task: Task type (compression, web_extract, vision, summarization).

        Returns:
            tuple: (LLMProvider, model_string)
        """
        if task in self._cache:
            return self._cache[task]

        aux_config = getattr(self._config, "auxiliary", None)
        if aux_config is None:
            return self._main_provider, self._main_model

        task_config = getattr(aux_config, task, None)
        if task_config is None or not task_config.model:
            return self._main_provider, self._main_model

        if self._factory:
            try:
                provider = self._factory(task_config.provider, task_config.model)
                result = (provider, task_config.model)
                self._cache[task] = result
                logger.info("auxiliary.routed: task={} model={}", task, task_config.model)
                return result
            except Exception as exc:
                logger.warning("auxiliary.factory_failed: task={} error={}", task, exc)

        return self._main_provider, self._main_model
