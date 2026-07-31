from __future__ import annotations

import logging
import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)


class FeishuClient:
    def __init__(self, webhook: str | None = None, timeout: float = 8.0) -> None:
        self.webhook = webhook if webhook is not None else os.getenv("FEISHU_WEBHOOK", "")
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @property
    def configured(self) -> bool:
        return bool(self.webhook and self.webhook.startswith("https://"))

    def send(self, text: str) -> bool:
        if not self.configured:
            LOGGER.warning("未配置 FEISHU_WEBHOOK，已完成扫描但跳过发送。")
            return False
        try:
            response = self.session.post(
                self.webhook,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", payload.get("StatusCode", 0)) not in (0, None):
                LOGGER.error("飞书返回失败状态（响应内容已隐藏）。")
                return False
            return True
        except (requests.RequestException, ValueError):
            LOGGER.error("飞书发送失败（地址与响应内容已隐藏）。")
            return False
