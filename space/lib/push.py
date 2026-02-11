import logging
from typing import Any

import httpx

from space.lib import devices

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send(tokens: list[str], title: str, body: str, data: dict[str, Any] | None = None) -> None:
    if not tokens:
        return

    messages = [
        {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data or {},
        }
        for token in tokens
    ]

    try:
        response = httpx.post(EXPO_PUSH_URL, json=messages, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Push notification failed: {e}")


def notify_mentions(
    mentions: list[str], author_identity: str, content: str, route: str | None = None
) -> None:
    for identity in mentions:
        if identity == author_identity:
            continue
        tokens = devices.get_push_tokens_for_handle(identity)
        if tokens:
            send(
                tokens=tokens,
                title=f"@{author_identity}",
                body=content[:100] + ("..." if len(content) > 100 else ""),
                data={"route": route} if route else None,
            )
