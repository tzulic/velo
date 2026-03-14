"""
Provider Registry — single source of truth for LLM provider metadata.

Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  2. Add a field to ProvidersConfig in config/schema.py.
  Done. Config matching, status display, and provider creation all derive from here.

Order matters — it controls match priority and fallback. Gateways first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    """One LLM provider's metadata. See PROVIDERS below for real examples."""

    # identity
    name: str  # config field name, e.g. "dashscope"
    keywords: tuple[str, ...]  # model-name keywords for matching (lowercase)
    display_name: str = ""  # shown in `velo status`

    # provider type — determines which native SDK class to instantiate.
    # Values: "anthropic", "openai", "mistral", "gemini", "azure", "codex", "cli", "custom"
    provider_type: str = "openai"

    # gateway / local detection
    is_gateway: bool = False  # routes any model (OpenRouter, AiHubMix)
    is_local: bool = False  # local deployment (vLLM, Ollama)
    detect_by_key_prefix: str = ""  # match api_key prefix, e.g. "sk-or-"
    detect_by_base_keyword: str = ""  # match substring in api_base URL
    default_api_base: str = ""  # fallback base URL

    # gateway behavior
    strip_model_prefix: bool = False  # strip "provider/" before passing to API

    # per-model param overrides, e.g. (("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # OAuth-based providers (e.g., OpenAI Codex) don't use API keys
    is_oauth: bool = False  # if True, uses OAuth flow instead of API key

    # Provider supports cache_control on content blocks (e.g. Anthropic prompt caching)
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        """Display label for this provider."""
        return self.display_name or self.name.title()


# ---------------------------------------------------------------------------
# PROVIDERS — the registry. Order = priority. Copy any entry as template.
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Custom (any OpenAI-compatible endpoint) ===========================
    ProviderSpec(
        name="custom",
        keywords=(),
        display_name="Custom",
        provider_type="custom",
        is_gateway=True,
    ),
    # === Azure OpenAI (direct API calls with API version 2024-10-21) =====
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure-openai"),
        display_name="Azure OpenAI",
        provider_type="azure",
    ),
    # === Gateways (detected by api_key / api_base, not model name) =========
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        display_name="OpenRouter",
        provider_type="openai",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        supports_prompt_caching=True,
    ),
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        display_name="AiHubMix",
        provider_type="openai",
        is_gateway=True,
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,
    ),
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        display_name="SiliconFlow",
        provider_type="openai",
        is_gateway=True,
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
    ),
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        display_name="VolcEngine",
        provider_type="openai",
        is_gateway=True,
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
    ),
    # === Standard providers (matched by model-name keywords) ===============
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        display_name="Anthropic",
        provider_type="anthropic",
        supports_prompt_caching=True,
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        display_name="OpenAI",
        provider_type="openai",
    ),
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        display_name="OpenAI Codex",
        provider_type="codex",
        detect_by_base_keyword="codex",
        default_api_base="https://chatgpt.com/backend-api",
        is_oauth=True,
    ),
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        display_name="Github Copilot",
        provider_type="codex",
        is_oauth=True,
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        display_name="DeepSeek",
        provider_type="openai",
        default_api_base="https://api.deepseek.com",
    ),
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        display_name="Gemini",
        provider_type="gemini",
    ),
    ProviderSpec(
        name="xai",
        keywords=("xai", "grok"),
        display_name="xAI",
        provider_type="openai",
        default_api_base="https://api.x.ai/v1",
    ),
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        display_name="Zhipu AI",
        provider_type="openai",
        default_api_base="https://open.bigmodel.cn/api/paas/v4/",
    ),
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        display_name="DashScope",
        provider_type="openai",
        default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        display_name="Moonshot",
        provider_type="openai",
        default_api_base="https://api.moonshot.ai/v1",
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),
    ),
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        display_name="MiniMax",
        provider_type="openai",
        default_api_base="https://api.minimax.io/v1",
    ),
    ProviderSpec(
        name="mistral",
        keywords=("mistral", "magistral", "devstral", "codestral", "ministral"),
        display_name="Mistral AI",
        provider_type="mistral",
    ),
    # === Claude CLI (no API key — uses Claude Max subscription) ============
    ProviderSpec(
        name="claude_cli",
        keywords=("claude_cli",),
        display_name="Claude CLI",
        provider_type="cli",
    ),
    # === Local deployment ==================================================
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        display_name="vLLM/Local",
        provider_type="openai",
        is_local=True,
    ),
    # === Auxiliary ==========================================================
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        display_name="Groq",
        provider_type="openai",
        default_api_base="https://api.groq.com/openai/v1",
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_by_model(model: str) -> ProviderSpec | None:
    """Match a standard provider by model-name keyword (case-insensitive).

    Skips gateways/local — those are matched by api_key/api_base instead.
    """
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    std_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    # Prefer explicit provider prefix — prevents `github-copilot/...codex` matching openai_codex.
    for spec in std_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec

    for spec in std_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized for kw in spec.keywords
        ):
            return spec
    return None


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    """Detect gateway/local provider.

    Priority:
      1. provider_name — if it maps to a gateway/local spec, use it directly.
      2. api_key prefix — e.g. "sk-or-" → OpenRouter.
      3. api_base keyword — e.g. "aihubmix" in URL → AiHubMix.
    """
    if provider_name:
        spec = find_by_name(provider_name)
        if spec and (spec.is_gateway or spec.is_local):
            return spec

    for spec in PROVIDERS:
        if spec.detect_by_key_prefix and api_key and api_key.startswith(spec.detect_by_key_prefix):
            return spec
        if spec.detect_by_base_keyword and api_base and spec.detect_by_base_keyword in api_base:
            return spec

    return None


def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by config field name, e.g. "dashscope"."""
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None
