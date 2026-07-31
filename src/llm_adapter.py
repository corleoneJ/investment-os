from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)


class LLMAdapter(Protocol):
    def summarize(self, asset: str, facts: str, fallback: str) -> str: ...


class DisabledLLMAdapter:
    def summarize(self, asset: str, facts: str, fallback: str) -> str:
        return fallback


class HTTPJSONLLMAdapter:
    def __init__(self, protocol: str, base_url: str, model: str, api_key: str) -> None:
        self.protocol = protocol
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.session = requests.Session()
        retry = Retry(
            total=1,
            backoff_factor=0.3,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def summarize(self, asset: str, facts: str, fallback: str) -> str:
        prompt = (
            "你是审慎的投资研究助手。只根据给定事实输出一句中文总结，"
            "必须区分事实和推测，不得承诺收益，不得使用“必涨”。\n"
            f"资产：{asset}\n事实：{facts}"
        )
        try:
            if self.protocol == "anthropic":
                response = self.session.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 120,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=8,
                )
                response.raise_for_status()
                text = response.json()["content"][0]["text"]
            else:
                response = self.session.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "temperature": 0.1,
                        "max_tokens": 120,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=8,
                )
                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"]
            return " ".join(str(text).strip().split()) or fallback
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
            LOGGER.warning("LLM分析失败，已使用本地决策结果；响应内容与密钥均未记录。")
            return fallback


def build_llm_adapter(config_path: str | Path) -> LLMAdapter:
    provider = (os.getenv("LLM_PROVIDER") or "disabled").lower()
    if provider == "disabled":
        return DisabledLLMAdapter()
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    selected = config.get(provider)
    api_key = os.getenv("LLM_API_KEY") or ""
    model = os.getenv("LLM_MODEL") or ""
    if not selected or not api_key or not model:
        LOGGER.warning("LLM配置不完整，已使用本地规则决策引擎。")
        return DisabledLLMAdapter()
    base_url = os.getenv("LLM_BASE_URL") or selected.get("base_url", "")
    protocol = selected.get("protocol", "openai_compatible")
    if not base_url:
        LOGGER.warning("LLM地址未配置，已使用本地规则决策引擎。")
        return DisabledLLMAdapter()
    return HTTPJSONLLMAdapter(protocol, base_url, model, api_key)
