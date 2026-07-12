"""LLM provider implementations.

`LLMProvider` is a minimal Protocol — anything with an async `chat` method
that returns a `ChatResponse` qualifies. This keeps the rest of the codebase
provider-agnostic and makes hermetic tests trivial (see `FakeProvider`).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

# LengthFinishReasonError is not re-exported from the top-level package in
# every openai version. Import defensively so a missing symbol doesn't
# break import time.
try:
    from openai import LengthFinishReasonError  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover — only on stripped openai builds
    LengthFinishReasonError = None  # type: ignore[assignment,misc]

from fae.llm.errors import LLMError
from fae.llm.types import ChatRequest, ChatResponse

logger = logging.getLogger("fae.llm")


@runtime_checkable
class LLMProvider(Protocol):
    """The minimum surface the rest of the app needs from an LLM backend."""

    async def chat(self, request: ChatRequest) -> ChatResponse: ...


class OpenAICompatibleProvider:
    """Real provider. Works with any server speaking OpenAI's chat completions
    protocol — Qwen3 (DashScope compatible-mode), DeepSeek, vLLM, etc.

    A new `openai.OpenAI` client is built per call so we never hold a
    reference to a key longer than the request. (Async client is created
    inside `chat` to keep construction site-agnostic.)
    """

    def __init__(self, default_timeout_s: float = 10.0) -> None:
        self._default_timeout_s = default_timeout_s

    async def chat(self, request: ChatRequest) -> ChatResponse:
        cfg = request.config
        client = OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            timeout=self._default_timeout_s,
        )
        try:
            resp = client.chat.completions.create(
                model=cfg.model,
                messages=[m.model_dump() for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        except AuthenticationError as e:
            # 401 — bad / missing key.
            raise LLMError(
                code="auth",
                message=f"Authentication failed for model '{cfg.model}': {e}",
            ) from e
        except PermissionDeniedError as e:
            # 403 — key valid but not authorized for this model.
            raise LLMError(
                code="forbidden",
                message=f"Permission denied for model '{cfg.model}': {e}",
            ) from e
        except NotFoundError as e:
            # 404 — model name wrong or endpoint path wrong.
            raise LLMError(
                code="not_found",
                message=f"Model '{cfg.model}' not found at {cfg.base_url}: {e}",
            ) from e
        except RateLimitError as e:
            # 429 — back off and retry is the caller's job.
            raise LLMError(
                code="rate_limited",
                message=f"Rate limited by provider: {e}",
            ) from e
        except APITimeoutError as e:
            raise LLMError(
                code="timeout",
                message=f"LLM request timed out after {self._default_timeout_s}s",
            ) from e
        except APIConnectionError as e:
            raise LLMError(
                code="connection",
                message=f"Cannot reach LLM endpoint {cfg.base_url}: {e}",
            ) from e
        except BadRequestError as e:
            raise LLMError(
                code="bad_request",
                message=f"LLM rejected request: {e}",
            ) from e
        except Exception as e:
            # LengthFinishReasonError (max_tokens hit) lands here in openai
            # versions that expose it. We special-case on class name so the
            # version-dependent import above doesn't break control flow.
            if LengthFinishReasonError is not None and isinstance(
                e, LengthFinishReasonError  # pragma: no cover — hard to construct
            ):
                raise LLMError(
                    code="length",
                    message=f"LLM hit max_tokens limit: {e}",
                ) from e
            # Any other openai SDK error that wasn't caught above (e.g. raw
            # APIError subclasses, transport-level errors not classified as
            # connection / timeout). Normalise to "connection" so the UI
            # surfaces a useful message instead of an opaque 500.
            if isinstance(e, APIError):
                logger.warning("Unclassified openai SDK error: %s", e)
                raise LLMError(
                    code="connection",
                    message=f"LLM provider error: {e}",
                ) from e
            # Last-resort normalisation.
            logger.exception("Unexpected LLM error")
            raise LLMError(
                code="unknown",
                message=f"Unexpected LLM error: {e}",
            ) from e

        # Defensive parsing — providers sometimes return empty choices.
        if not resp.choices:
            raise LLMError(
                code="empty_response",
                message="LLM returned no choices",
            )
        content = resp.choices[0].message.content or ""
        usage: dict[str, int] | None = None
        if resp.usage is not None:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return ChatResponse(content=content, model=resp.model, usage=usage)


class FakeProvider:
    """Deterministic in-process provider. Used by tests.

    Configure behaviour via the constructor so each test owns its own
    canned responses and error injection.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        error: Exception | None = None,
        echo: bool = False,
    ) -> None:
        # If `echo` is set, the provider echoes back the last user message
        # (handy for trivial "is the wire working" smoke tests).
        self._responses = list(responses or [])
        self._error = error
        self._echo = echo
        self.calls: list[ChatRequest] = []  # observability for tests

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        if self._echo:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"),
                "",
            )
            return ChatResponse(content=last_user, model="fake-model", usage=None)
        if not self._responses:
            return ChatResponse(content="", model="fake-model", usage=None)
        return ChatResponse(
            content=self._responses.pop(0),
            model="fake-model",
            usage=None,
        )
