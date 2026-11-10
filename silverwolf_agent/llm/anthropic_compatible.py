from __future__ import annotations

import json
import random
import time
from typing import Any
from urllib import request, error

from .base import BaseLLMClient
from .errors import LLMServiceError
from ..models import ChatMessage, LLMResponse, ToolCall


class AnthropicCompatibleClient(BaseLLMClient):
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 1000,
        temperature: float = 0.8,
        timeout: int = 90,
        max_retries: int = 3,
        retry_base_seconds: float = 1.5,
    ) -> None:
        if not api_key:
            raise ValueError("api_key 不能为空")
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        if retry_base_seconds < 0:
            raise ValueError("retry_base_seconds 不能小于 0")

        self.api_key = api_key
        self.endpoint = self._normalize_endpoint(base_url)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds

    @staticmethod
    def _normalize_endpoint(base_url: str) -> str:
        value = base_url.rstrip("/")
        if value.endswith("/v1/messages"):
            return value
        if value.endswith("/v1"):
            return value + "/messages"
        return value + "/v1/messages"

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 30.0)
            except ValueError:
                pass

        # 1.5s, 3s, 6s...，加少量抖动，避免同时重试。
        delay = self.retry_base_seconds * (2 ** attempt)
        jitter = random.uniform(0.0, 0.5)
        return min(delay + jitter, 30.0)

    def _perform_request(self, body: bytes) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            req = request.Request(
                self.endpoint,
                data=body,
                method="POST",
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "authorization": f"Bearer {self.api_key}",
                    "anthropic-version": "2023-06-01",
                },
            )

            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))

            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code in self.RETRYABLE_STATUS_CODES
                last_error = exc

                if retryable and attempt < self.max_retries:
                    retry_after = (
                        exc.headers.get("Retry-After")
                        if exc.headers is not None
                        else None
                    )
                    time.sleep(self._retry_delay(attempt, retry_after))
                    continue

                raise LLMServiceError(
                    f"模型接口返回 HTTP {exc.code}: {detail}",
                    status_code=exc.code,
                    retryable=retryable,
                ) from exc

            except error.URLError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt, None))
                    continue
                raise LLMServiceError(
                    f"无法连接模型接口：{exc.reason}",
                    status_code=None,
                    retryable=True,
                ) from exc

        raise LLMServiceError(
            f"模型接口调用失败：{last_error}",
            retryable=True,
        )

    def complete(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [
                {"role": item.role, "content": item.content}
                for item in messages
            ],
        }
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw = self._perform_request(body)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in raw.get("content", []):
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text", "")))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=dict(block.get("input") or {}),
                    )
                )

        # 兼容部分服务商返回 OpenAI 风格 choices。
        if not text_parts and "choices" in raw:
            choice = (raw.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                text_parts.append(content)

        return LLMResponse(
            text="\n".join(part for part in text_parts if part).strip(),
            tool_calls=tool_calls,
            raw=raw,
        )
