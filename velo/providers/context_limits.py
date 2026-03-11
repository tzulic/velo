"""Model context window limits and token estimation."""

from typing import Any

# Pattern-based lookup: first match wins.
# Patterns matched against model.lower(); ordered specific → general.
# Sources: explodingtopics.com/blog/list-of-llms (March 2026), siliconflow.com
CONTEXT_WINDOWS: list[tuple[str, int]] = [
    # Anthropic — Claude 4.x / 4.5 / 4.6 all use 200K
    ("claude", 200_000),
    # OpenAI — o-series reasoning models
    ("o3", 200_000),
    ("o4", 200_000),
    # OpenAI — GPT-5.x family (400K)
    ("gpt-5", 400_000),
    # OpenAI — GPT-4.1 (1M context)
    ("gpt-4.1", 1_000_000),
    # OpenAI — GPT-4.5, GPT-4o (128K)
    ("gpt-4", 128_000),
    # Google — Gemini 2.5/3.x (all 1M)
    ("gemini", 1_000_000),
    # DeepSeek — V3/V3.1/V3.2 (128-164K), R1 (131K)
    ("deepseek", 128_000),
    # Alibaba — Qwen 3/3.5 (262K native)
    ("qwen", 262_000),
    # Moonshot — Kimi K2/K2.5 (1M context)
    ("kimi", 1_000_000),
    ("moonshot", 128_000),
    # Meta — Llama 4 Scout (10M), Maverick (1M)
    ("llama-4-scout", 10_000_000),
    ("llama-4-maverick", 1_000_000),
    ("llama", 128_000),
    # xAI — Grok 4.1 (2M), Grok 4 (256K)
    ("grok-4.1", 2_000_000),
    ("grok", 256_000),
    # Zhipu — GLM-5
    ("glm", 128_000),
    # MiniMax
    ("minimax", 128_000),
    # Mistral — specific families first, then general fallback
    ("codestral", 256_000),   # Codestral: confirmed 256K context
    ("devstral", 256_000),    # Devstral: 256–262K range, 256K safe floor
    ("mistral", 128_000),     # All other Mistral models default to 128K
    # Groq (hosted, varies by model)
    ("groq", 128_000),
]

_DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model: str, override: int | None = None) -> int:
    """Get the context window size for a model.

    Args:
        model: The model identifier (e.g. "anthropic/claude-opus-4-5").
        override: Optional user-provided override.

    Returns:
        int: The context window size in tokens.
    """
    if override is not None:
        return override
    model_lower = model.lower()
    for pattern, limit in CONTEXT_WINDOWS:
        if pattern in model_lower:
            return limit
    return _DEFAULT_CONTEXT_WINDOW


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate using chars/4 heuristic.

    Args:
        messages: List of chat messages.

    Returns:
        int: Estimated token count.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(item)) for item in content)
        # Count tool_calls arguments
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            total += len(fn.get("arguments", ""))
    return total // 4
