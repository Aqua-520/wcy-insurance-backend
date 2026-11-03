"""
会话事件广播器(进程内)。

用途: 会话有新消息/状态变更时, 通知正在订阅该会话的连接。
设计要点: **只推信号, 不推正文** —— 订阅方收到信号后用 after_id 增量拉 REST,
所以丢一条事件不影响正确性, 重连按 after_id 补齐即可。

多 worker 部署时把 publish/subscribe 换成 PG LISTEN/NOTIFY 即可, 调用方接口不变。
"""
import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class ThreadBroadcaster:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, thread_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(str(thread_id), set()).add(queue)
        return queue

    def unsubscribe(self, thread_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(str(thread_id))
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(str(thread_id), None)

    def publish(self, thread_id: str, event: dict[str, Any]) -> None:
        """推送信号; 订阅者队列满时丢弃(客户端靠增量拉取兜底), 绝不阻塞业务。"""
        for queue in list(self._subscribers.get(str(thread_id), ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("会话事件队列已满, 丢弃信号 thread=%s", thread_id)


broadcaster = ThreadBroadcaster()
