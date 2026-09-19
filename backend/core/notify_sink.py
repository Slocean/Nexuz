"""无头服务器通知汇：scheduler / interpreter 的 emit 回调接收端。

桌面版把 emit 接到 UI 事件队列；服务器版没有 UI，事件去向：
- 全部事件写 log_hub（必开）；
- 选中事件（定时触发/失败、流程结束）异步 POST webhook，失败重试 1 次，
  绝不阻塞调度与解释器线程。

webhook 地址：构造参数 > config.json [server].webhook_url；未配置则只写日志。
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 外发 webhook 的事件白名单：定时任务触发/失败 + 流程结束（成功与失败都可见）
WEBHOOK_EVENTS = frozenset(
    {"schedule_fired", "schedule_error", "flow_finished", "flow_stopped"}
)

_WEBHOOK_TIMEOUT_S = 10.0


def config_webhook_url() -> str:
    from backend.paths import load_app_config

    section = load_app_config().get("server")
    if isinstance(section, dict):
        return str(section.get("webhook_url") or "").strip()
    return ""


class NotifySink:
    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        source: str = "nexuz-server",
        poster: Callable[[dict[str, Any]], None] | None = None,
    ):
        # poster 仅供测试注入；生产用 _post_webhook
        self._webhook_url = (webhook_url if webhook_url is not None else config_webhook_url()).strip()
        self._source = source
        self._poster = poster
        self._lock = threading.Lock()

    @property
    def webhook_url(self) -> str:
        return self._webhook_url

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        event = str(event or "")
        payload = payload if isinstance(payload, dict) else {}
        logger.info("notify event=%s payload=%s", event, json.dumps(payload, ensure_ascii=False, default=str))
        if self._webhook_url and event in WEBHOOK_EVENTS:
            body = self._build_body(event, payload)
            threading.Thread(
                target=self._deliver,
                args=(body,),
                daemon=True,
                name="nexuz-notify-webhook",
            ).start()

    def _build_body(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": self._source,
            "event": event,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def _deliver(self, body: dict[str, Any]) -> None:
        if self._poster is not None:
            try:
                self._poster(body)
            except Exception as exc:
                logger.warning("webhook poster 失败 event=%s: %s", body.get("event"), exc)
            return
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(2):  # 失败重试 1 次
            try:
                req = urllib.request.Request(
                    self._webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as resp:
                    if 200 <= resp.status < 300:
                        return
                    last_exc = RuntimeError(f"webhook HTTP {resp.status}")
            except Exception as exc:
                last_exc = exc
        logger.warning("webhook 外发失败 event=%s: %s", body.get("event"), last_exc)
