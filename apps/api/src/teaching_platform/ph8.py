import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass
class PH8Error(Exception):
    code: str
    message: str
    retryable: bool = False


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/chat/completions") else f"{value}/chat/completions"


def _parse_content(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PH8Error("invalid_response", "模型响应缺少可解析内容") from exc
    if isinstance(content, dict):
        result = content
    elif isinstance(content, str):
        text = content.strip()
        if text.startswith("```"):
            text = text.removeprefix("```").removeprefix("json").removesuffix("```").strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise PH8Error("invalid_response", "模型响应不是有效 JSON") from None
            try:
                result = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise PH8Error("invalid_response", "模型响应不是有效 JSON") from exc
    else:
        raise PH8Error("invalid_response", "模型响应格式不支持")
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise PH8Error("invalid_response", "模型响应缺少逐题结果")
    return result


class PH8Client:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def grade_submission(self, *, assignment_title: str, questions: list[dict], answers: dict[str, str]) -> dict[str, Any]:
        if not self.settings.ph8_api_key:
            raise PH8Error("not_configured", "PH8_API_KEY 未配置")
        request = {
            "model": self.settings.ph8_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是作业批改助手。只返回 JSON，不要 Markdown 或额外解释。"
                        "JSON 格式必须是 {\"items\":[{\"question_id\":\"...\","
                        "\"score\":0,\"feedback\":\"...\"}]}。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"assignment_title": assignment_title, "questions": questions, "answers": answers},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        client = self._client or httpx.Client(timeout=self.settings.ph8_timeout_seconds)
        try:
            response = client.post(
                _endpoint(self.settings.ph8_base_url),
                headers={"Authorization": f"Bearer {self.settings.ph8_api_key}"},
                json=request,
            )
        except httpx.TimeoutException as exc:
            raise PH8Error("timeout", "模型请求超时", retryable=True) from exc
        except httpx.RequestError as exc:
            raise PH8Error("network_error", "模型网络请求失败", retryable=True) from exc
        finally:
            if self._owns_client:
                client.close()
        if response.status_code == 429:
            raise PH8Error("rate_limited", "模型请求受到限流", retryable=True)
        if response.status_code >= 500:
            raise PH8Error("upstream_error", "模型服务暂时不可用", retryable=True)
        if response.status_code >= 400:
            raise PH8Error("upstream_rejected", "模型请求被拒绝")
        try:
            body = response.json()
        except ValueError as exc:
            raise PH8Error("invalid_response", "模型响应不是有效 JSON") from exc
        return _parse_content(body)
