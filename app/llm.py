from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from threading import local
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.model_router import EnvironmentModelRouter, ModelRoute
from app.usage import UsageTracker
from app.validation import ValidationError, ValidationManager, validation_context


SYSTEM_PROMPT = (
    "You are AIOS, a helpful AI assistant inside a local chatbot app. "
    "Answer clearly, stay practical, and ask a short follow-up question when the user goal is unclear."
)


class LLMError(RuntimeError):
    pass


ROUTER = EnvironmentModelRouter()
USAGE = UsageTracker()
VALIDATION = ValidationManager.from_env()
_ROUTE_STATE = local()


def generate_response(messages: list[dict[str, str]]) -> tuple[str, str]:
    text, route = _generate_response_once(messages)
    active_route = [route]

    def retry(feedback: str) -> str:
        retry_messages = [*messages, {"role": "system", "content": feedback}]
        corrected, retry_route = _generate_response_once(retry_messages)
        active_route[0] = retry_route
        return corrected

    try:
        validated = VALIDATION.process(text, validation_context(messages), retry=retry)
    except ValidationError as exc:
        raise LLMError(str(exc)) from exc
    return validated, active_route[0].provider


def generate_response_stream(messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
    chunks, route = generate_with_router(messages, stream=True)
    assert not isinstance(chunks, str)
    output = "".join(chunks).strip()
    USAGE.record(route.provider, route.model, route.task, messages, output)
    active_route = [route]

    def retry(feedback: str) -> str:
        retry_messages = [*messages, {"role": "system", "content": feedback}]
        corrected, retry_route = _generate_response_once(retry_messages)
        active_route[0] = retry_route
        return corrected

    try:
        validated = VALIDATION.process(output, validation_context(messages), retry=retry)
    except ValidationError as exc:
        raise LLMError(str(exc)) from exc
    return iter((validated,)), active_route[0].provider


def _generate_response_once(messages: list[dict[str, str]]) -> tuple[str, ModelRoute]:
    text, route = generate_with_router(messages, stream=False)
    assert isinstance(text, str)
    USAGE.record(route.provider, route.model, route.task, messages, text)
    return text, route


def generate_with_router(
    messages: list[dict[str, str]], stream: bool
) -> tuple[str | Iterator[str], ModelRoute]:
    try:
        routes = ROUTER.routes(messages, configured_providers())
    except ValueError as exc:
        raise LLMError(str(exc)) from exc
    errors: list[str] = []
    for route in routes:
        _ROUTE_STATE.active = route
        try:
            if route.provider in {"openai", "groq", "deepseek"}:
                result = chat_completions_stream(route.provider, messages) if stream else chat_completions(route.provider, messages)
            else:
                result = gemini_stream(messages) if stream else gemini(messages)
            return result, route
        except LLMError as exc:
            errors.append(f"{route.provider}: {exc}")
    if errors:
        raise LLMError("All configured providers failed. " + " | ".join(errors))
    raise LLMError("No LLM provider is configured. Add an API key to .env.")


def current_route() -> ModelRoute | None:
    return getattr(_ROUTE_STATE, "active", None)


def generate_with_fallback(messages: list[dict[str, str]]) -> tuple[str, str]:
    errors: list[str] = []
    for provider in configured_providers():
        try:
            if provider in {"openai", "groq", "deepseek"}:
                return chat_completions(provider, messages), provider
            if provider == "gemini":
                return gemini(messages), provider
        except LLMError as exc:
            errors.append(f"{provider}: {exc}")

    if errors:
        raise LLMError(
            "All configured providers failed. Please verify your API keys and network connection. "
            + " | ".join(errors)
        )
    raise LLMError(
        "No LLM provider is configured. Add an API key to .env, for example GROQ_API_KEY or GEMINI_API_KEY."
    )


def generate_stream_with_fallback(messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
    errors: list[str] = []
    for provider in configured_providers():
        try:
            if provider in {"openai", "groq", "deepseek"}:
                return chat_completions_stream(provider, messages), provider
            if provider == "gemini":
                return gemini_stream(messages), provider
        except LLMError as exc:
            errors.append(f"{provider}: {exc}")

    if errors:
        raise LLMError(
            "All configured providers failed. Please verify your API keys and network connection. "
            + " | ".join(errors)
        )
    raise LLMError(
        "No LLM provider is configured. Add an API key to .env, for example GROQ_API_KEY or GEMINI_API_KEY."
    )


def configured_providers() -> list[str]:
    providers: list[str] = []
    if os.getenv("GROQ_API_KEY"):
        providers.append("groq")
    if os.getenv("GEMINI_API_KEY"):
        providers.append("gemini")
    if os.getenv("OPENAI_API_KEY"):
        providers.append("openai")
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append("deepseek")
    return providers


def chat_completions(provider: str, messages: list[dict[str, str]]) -> str:
    configs = {
        "openai": {
            "key": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
        "groq": {
            "key": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "llama-3.1-8b-instant",
        },
        "deepseek": {
            "key": "DEEPSEEK_API_KEY",
            "url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
        },
    }
    config = configs[provider]
    api_key = require_env(config["key"])
    model = provider_model(provider, config["model"])
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7")),
    }
    data = post_json(
        config["url"],
        payload,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AIOS-Starter/0.1",
        },
    )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected {provider} response shape.") from exc


def chat_completions_stream(provider: str, messages: list[dict[str, str]]) -> Iterator[str]:
    configs = {
        "openai": {
            "key": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
        "groq": {
            "key": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "llama-3.1-8b-instant",
        },
        "deepseek": {
            "key": "DEEPSEEK_API_KEY",
            "url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
        },
    }
    config = configs[provider]
    api_key = require_env(config["key"])
    model = provider_model(provider, config["model"])
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7")),
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "AIOS-Starter/0.1",
    }
    return stream_chat_completions(config["url"], payload, headers, provider)


def gemini(messages: list[dict[str, str]]) -> str:
    api_key = require_env("GEMINI_API_KEY")
    prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7"))},
    }
    errors: list[str] = []
    for model in gemini_models_to_try():
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            data = post_json(
                url,
                payload,
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "AIOS-Starter/0.1",
                },
            )
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts).strip()
        except LLMError as exc:
            errors.append(f"{model}: {exc}")
            continue
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected gemini response shape.") from exc

    raise LLMError("All Gemini models failed. " + " | ".join(errors))


def gemini_stream(messages: list[dict[str, str]]) -> Iterator[str]:
    api_key = require_env("GEMINI_API_KEY")
    prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7"))},
    }
    errors: list[str] = []
    for model in gemini_models_to_try():
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        try:
            return stream_gemini(url, payload, model)
        except LLMError as exc:
            errors.append(f"{model}: {exc}")
            continue

    raise LLMError("All Gemini streaming models failed. " + " | ".join(errors))


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    attempts = int(os.getenv("AIOS_LLM_RETRIES", "2")) + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60"))) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise LLMError("The LLM provider request timed out.") from exc
        except (ConnectionResetError, ConnectionAbortedError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise LLMError(connection_error_message(exc)) from exc
        except URLError as exc:
            last_error = exc
            reason = exc.reason
            if attempt == attempts - 1:
                raise LLMError(connection_error_message(reason)) from exc

        time.sleep(0.7 * (attempt + 1))

    raise LLMError(connection_error_message(last_error))


def stream_chat_completions(
    url: str, payload: dict[str, Any], headers: dict[str, str], provider: str
) -> Iterator[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        response = urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60")))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM streaming request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise LLMError("The LLM provider streaming request timed out.") from exc
    except (ConnectionResetError, ConnectionAbortedError) as exc:
        raise LLMError(connection_error_message(exc)) from exc
    except URLError as exc:
        raise LLMError(connection_error_message(exc.reason)) from exc

    def events() -> Iterator[str]:
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                event = line.removeprefix("data:").strip()
                if event == "[DONE]":
                    return
                chunk = parse_chat_completion_stream_event(event, provider)
                if chunk:
                    yield chunk
        finally:
            response.close()

    return events()


def stream_gemini(url: str, payload: dict[str, Any], model: str) -> Iterator[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "AIOS-Starter/0.1",
        },
        method="POST",
    )
    try:
        response = urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60")))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"Gemini streaming request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise LLMError("The Gemini streaming request timed out.") from exc
    except (ConnectionResetError, ConnectionAbortedError) as exc:
        raise LLMError(connection_error_message(exc)) from exc
    except URLError as exc:
        raise LLMError(connection_error_message(exc.reason)) from exc

    def events() -> Iterator[str]:
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                event = line.removeprefix("data:").strip()
                chunk = parse_gemini_stream_event(event, model)
                if chunk:
                    yield chunk
        finally:
            response.close()

    return events()


def parse_chat_completion_stream_event(event: str, provider: str) -> str:
    try:
        data = json.loads(event)
        choice = data.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        content = delta.get("content", "")
        if isinstance(content, str):
            return content
        return ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected {provider} streaming response shape.") from exc


def parse_gemini_stream_event(event: str, model: str) -> str:
    try:
        data = json.loads(event)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts if isinstance(part.get("text", ""), str))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected Gemini streaming response shape for {model}.") from exc


def require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise LLMError(f"{name} is missing. Add it to .env and restart the app.")
    return value


def provider_model(provider: str, default: str) -> str:
    active_route = current_route()
    if active_route and active_route.provider == provider:
        return active_route.model
    specific_names = {
        "openai": "AIOS_OPENAI_MODEL",
        "groq": "AIOS_GROQ_MODEL",
        "deepseek": "AIOS_DEEPSEEK_MODEL",
        "gemini": "AIOS_GEMINI_MODEL",
    }
    specific = os.getenv(specific_names[provider], "").strip()
    fallback = os.getenv("AIOS_DEFAULT_MODEL", "").strip()
    return specific or fallback or default


def gemini_models_to_try() -> list[str]:
    configured = provider_model("gemini", "gemini-2.0-flash")
    candidates = [
        configured,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.5-flash",
    ]
    unique: list[str] = []
    for model in candidates:
        if model and model not in unique:
            unique.append(model)
    return unique


def connection_error_message(error: object) -> str:
    return (
        f"Could not reach the LLM provider: {error}. "
        "This is usually a provider/network reset, not a prompt problem. "
        "Use AIOS_PROVIDER=auto to fall back to another configured provider."
    )
