"""Native Google Gemini provider — direct SDK calls via google-genai."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from velo.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCallRequest,
    strip_model_prefix,
)

# Finish-reason mapping from Gemini to our standard.
_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "stop",
    "RECITATION": "stop",
}


def _synthetic_tool_id(name: str, args: dict[str, Any]) -> str:
    """Generate a short deterministic ID for a Gemini function call.

    Gemini doesn't assign IDs to function calls, so we generate one from
    the function name and arguments for consistent tool_call_id tracking.

    Args:
        name: Function name.
        args: Function arguments dict.

    Returns:
        str: 9-char hex ID.
    """
    raw = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=True)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:9]


class GeminiProvider(LLMProvider):
    """LLM provider using the native Google GenAI SDK.

    Uses the unified ``google-genai`` SDK (GA, v1.0+) with
    ``client.aio.models.generate_content()`` for async calls.
    """

    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
        default_model: str = "gemini-2.5-flash",
    ):
        super().__init__(api_key, api_base)
        from google import genai

        self._default_model = default_model
        self._client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[Any]]:
        """Convert OpenAI-format messages to Gemini format.

        Returns:
            tuple: (system_instruction, contents) where system_instruction is
            the extracted system prompt and contents is a list of Gemini Content objects.
        """
        from google.genai import types

        system_parts: list[str] = []
        contents: list[Any] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("text"):
                            system_parts.append(item["text"])

            elif role == "user":
                parts = _build_user_parts(msg)
                if parts:
                    contents.append(types.Content(role="user", parts=parts))

            elif role == "assistant":
                parts = _build_model_parts(msg)
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
                # Tool results → user Content with function_response parts.
                content = msg.get("content", "")
                name = msg.get("name", "tool")
                if isinstance(content, str):
                    try:
                        result = json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        result = {"result": content}
                elif isinstance(content, dict):
                    result = content
                else:
                    result = {"result": str(content)}
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(name=name, response=result)],
                ))

        # Enforce role alternation by merging consecutive same-role Content.
        merged = _merge_consecutive_roles(contents)

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, merged

    # ------------------------------------------------------------------
    # Tool conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> Any:
        """Convert OpenAI-format tools to Gemini FunctionDeclarations.

        Args:
            tools: OpenAI-format tool definitions.

        Returns:
            list: Gemini Tool objects with function declarations.
        """
        from google.genai import types

        declarations: list[Any] = []
        for tool in tools:
            fn = tool.get("function", tool) if tool.get("type") == "function" else tool
            name = fn.get("name")
            if not name:
                continue
            declarations.append(types.FunctionDeclaration(
                name=name,
                description=fn.get("description", ""),
                parameters=fn.get("parameters"),
            ))

        if not declarations:
            return None
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _map_tool_choice(tool_choice: str) -> Any:
        """Map OpenAI tool_choice to Gemini FunctionCallingConfig.

        Args:
            tool_choice: OpenAI tool choice string.

        Returns:
            Gemini ToolConfig or None.
        """
        from google.genai import types

        mode_map = {
            "auto": "AUTO",
            "required": "ANY",
            "none": "NONE",
        }
        mode = mode_map.get(tool_choice, "AUTO")
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode=mode),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """Strip 'gemini/' prefix from model name."""
        return strip_model_prefix(model, "gemini/")

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_config(
        self,
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        tool_choice: str,
        system_instruction: str | None,
    ) -> Any:
        """Build Gemini GenerateContentConfig.

        Returns:
            GenerateContentConfig object.
        """
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "max_output_tokens": max(1, max_tokens),
            "temperature": temperature,
        }

        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        if tools:
            gemini_tools = self._convert_tools(tools)
            if gemini_tools:
                config_kwargs["tools"] = gemini_tools
                config_kwargs["tool_config"] = self._map_tool_choice(tool_choice)
                config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                    disable=True,
                )

        return types.GenerateContentConfig(**config_kwargs)

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,  # noqa: ARG002 — interface conformance
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Send a generate_content request via the Gemini SDK.

        Args:
            messages: List of message dicts (OpenAI format).
            tools: Optional tool definitions.
            model: Model identifier (e.g. 'gemini-2.5-flash').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            reasoning_effort: Unused by Gemini (interface conformance).
            tool_choice: Tool selection mode.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        resolved = self._strip_prefix(model or self._default_model)
        sanitized = self._sanitize_empty_content(messages)
        system_instruction, contents = self._convert_messages(sanitized)

        config = self._build_config(tools, max_tokens, temperature, tool_choice, system_instruction)

        try:
            response = await self._client.aio.models.generate_content(
                model=resolved,
                contents=contents,
                config=config,
            )
            return self._parse_response(response)
        except Exception as e:
            return _handle_error(e)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,  # noqa: ARG002 — interface conformance
        tool_choice: str = "auto",
    ) -> AsyncIterator[StreamChunk]:
        """Stream generate_content via the Gemini SDK.

        Yields text deltas and a final chunk with tool calls, usage, and finish reason.

        Yields:
            StreamChunk with incremental deltas and final metadata.
        """
        resolved = self._strip_prefix(model or self._default_model)
        sanitized = self._sanitize_empty_content(messages)
        system_instruction, contents = self._convert_messages(sanitized)

        config = self._build_config(tools, max_tokens, temperature, tool_choice, system_instruction)

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=resolved,
                contents=contents,
                config=config,
            )
        except Exception as e:
            resp = _handle_error(e)
            yield StreamChunk(
                delta=resp.content or "",
                finish_reason="error",
                error_code=resp.error_code,
            )
            return

        accumulated_tool_calls: list[ToolCallRequest] = []
        last_finish = "stop"
        last_chunk: Any = None

        async for chunk in stream:
            last_chunk = chunk
            # Yield text directly if available.
            text = getattr(chunk, "text", None)
            if text:
                yield StreamChunk(delta=text)

            # Accumulate function calls from candidates.
            if chunk.candidates:
                for candidate in chunk.candidates:
                    if candidate.finish_reason:
                        raw = str(candidate.finish_reason)
                        last_finish = _FINISH_REASON_MAP.get(raw, "stop")
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            fn_call = getattr(part, "function_call", None)
                            if fn_call:
                                args = dict(fn_call.args) if fn_call.args else {}
                                accumulated_tool_calls.append(ToolCallRequest(
                                    id=_synthetic_tool_id(fn_call.name, args),
                                    name=fn_call.name,
                                    arguments=args,
                                ))

        # Emit final chunk.
        usage = _extract_stream_usage(last_chunk) if last_chunk else {}
        if accumulated_tool_calls:
            last_finish = "tool_calls"
        yield StreamChunk(
            finish_reason=last_finish,
            tool_calls=accumulated_tool_calls or None,
            usage=usage or None,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """Parse Gemini GenerateContentResponse into LLMResponse.

        Args:
            response: Gemini response object.

        Returns:
            LLMResponse with normalized content and metadata.
        """
        if not response.candidates:
            return LLMResponse(content=None, finish_reason="error", error_code="bad_request")

        candidate = response.candidates[0]
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                fn_call = getattr(part, "function_call", None)
                if fn_call:
                    args = dict(fn_call.args) if fn_call.args else {}
                    tool_calls.append(ToolCallRequest(
                        id=_synthetic_tool_id(fn_call.name, args),
                        name=fn_call.name,
                        arguments=args,
                    ))

        # Map finish reason.
        raw_finish = str(candidate.finish_reason) if candidate.finish_reason else "STOP"
        finish_reason = _FINISH_REASON_MAP.get(raw_finish, "stop")
        if tool_calls:
            finish_reason = "tool_calls"

        # Usage.
        usage = {}
        meta = getattr(response, "usage_metadata", None)
        if meta:
            prompt = getattr(meta, "prompt_token_count", 0) or 0
            completion = getattr(meta, "candidates_token_count", 0) or 0
            usage = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self._default_model


# ======================================================================
# Module-level helpers
# ======================================================================


def _build_user_parts(msg: dict[str, Any]) -> list[Any]:
    """Build Gemini Part list from a user message."""
    from google.genai import types

    content = msg.get("content", "")
    if isinstance(content, str):
        return [types.Part.from_text(text=content or "(empty)")]
    if isinstance(content, list):
        parts: list[Any] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(types.Part.from_text(text=item.get("text", "")))
        return parts or [types.Part.from_text(text="(empty)")]
    return [types.Part.from_text(text="(empty)")]


def _build_model_parts(msg: dict[str, Any]) -> list[Any]:
    """Build Gemini Part list from an assistant message."""
    from google.genai import types

    parts: list[Any] = []

    # Text content.
    content = msg.get("content")
    if isinstance(content, str) and content:
        parts.append(types.Part.from_text(text=content))
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(types.Part.from_text(text=item["text"]))

    # Tool calls → function_call parts.
    for tc in msg.get("tool_calls") or []:
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            parts.append(types.Part.from_function_call(
                name=fn.get("name", ""),
                args=args if isinstance(args, dict) else {},
            ))

    return parts


def _merge_consecutive_roles(contents: list[Any]) -> list[Any]:
    """Merge consecutive same-role Content to enforce Gemini's alternation requirement."""
    if not contents:
        return []

    merged: list[Any] = []
    for content in contents:
        if merged and merged[-1].role == content.role:
            # Combine parts from both Content objects.
            merged[-1] = type(content)(
                role=content.role,
                parts=list(merged[-1].parts or []) + list(content.parts or []),
            )
        else:
            merged.append(content)
    return merged


def _extract_stream_usage(chunk: Any) -> dict[str, int]:
    """Extract usage from the last stream chunk."""
    meta = getattr(chunk, "usage_metadata", None)
    if not meta:
        return {}
    prompt = getattr(meta, "prompt_token_count", 0) or 0
    completion = getattr(meta, "candidates_token_count", 0) or 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _handle_error(exc: Exception) -> LLMResponse:
    """Classify a Gemini SDK exception into an LLMResponse with error_code."""
    from velo.providers.errors import classify_error

    error_msg = str(exc)
    code = classify_error(error_msg)

    logger.warning("gemini.request_failed: {}", error_msg[:200])
    return LLMResponse(
        content=f"Error calling Gemini: {error_msg}",
        finish_reason="error",
        error_code=code,
    )
