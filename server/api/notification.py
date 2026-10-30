"""通知服务 API"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from ..services.notification import notification_service, NotifyChannel

router = APIRouter(prefix="/api/notify", tags=["notification"])


class NotifyConfigUpdate(BaseModel):
    feishu_webhook: Optional[str] = None
    slack_webhook: Optional[str] = None
    email_smtp_host: Optional[str] = None
    email_smtp_port: Optional[int] = None
    email_sender: Optional[str] = None
    email_password: Optional[str] = None
    email_recipients: Optional[List[str]] = None
    enabled_channels: Optional[List[str]] = None


class TestNotifyRequest(BaseModel):
    channel: str = "all"  # "feishu" | "slack" | "email" | "all"
    message: str = "This is a test notification from MERAK."


@router.get("/config")
async def get_config():
    """Get persisted configuration without returning secrets."""
    return {
        **notification_service.public_config(),
        "verification": {
            channel.value: notification_service.channel_verification(channel)
            for channel in NotifyChannel
        },
    }


def _prospective_payload(channel: NotifyChannel, updates: dict) -> dict:
    cfg = notification_service._config
    if channel == NotifyChannel.FEISHU:
        return {"webhook": updates.get("feishu_webhook", cfg.feishu_webhook)}
    if channel == NotifyChannel.SLACK:
        return {"webhook": updates.get("slack_webhook", cfg.slack_webhook)}
    return {
        "smtp_host": updates.get("email_smtp_host", cfg.email_smtp_host),
        "smtp_port": updates.get("email_smtp_port", cfg.email_smtp_port),
        "sender": updates.get("email_sender", cfg.email_sender),
        "password": updates.get("email_password", cfg.email_password),
        "recipients": updates.get("email_recipients", cfg.email_recipients),
    }


@router.post("/config")
async def update_config(req: NotifyConfigUpdate):
    """Persist notification configuration while preserving omitted secrets."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "enabled_channels" in updates:
        try:
            channels = [NotifyChannel(c) for c in updates["enabled_channels"]]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Unknown notification channel: {exc}") from exc
        cfg = notification_service._config
        feishu = updates.get("feishu_webhook", cfg.feishu_webhook)
        slack = updates.get("slack_webhook", cfg.slack_webhook)
        email_ready = all([
            updates.get("email_smtp_host", cfg.email_smtp_host),
            updates.get("email_sender", cfg.email_sender),
            updates.get("email_password", cfg.email_password),
            updates.get("email_recipients", cfg.email_recipients),
        ])
        missing = []
        if NotifyChannel.FEISHU in channels and not feishu:
            missing.append("Feishu webhook")
        if NotifyChannel.SLACK in channels and not slack:
            missing.append("Slack webhook")
        if NotifyChannel.EMAIL in channels and not email_ready:
            missing.append("email SMTP/sender/password/recipients")
        if missing:
            raise HTTPException(status_code=422, detail=f"Missing configuration: {', '.join(missing)}")
        unverified = [
            channel.value
            for channel in channels
            if not notification_service._verification_store.is_verified(
                "notification",
                channel.value,
                _prospective_payload(channel, updates),
            )
        ]
        if unverified:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Notification channels must pass a delivery test before they can be enabled: "
                    + ", ".join(unverified)
                ),
            )
        updates["enabled_channels"] = channels
    notification_service.update_config(**updates)
    return {"status": "updated", "config": notification_service.public_config()}


@router.post("/test")
async def test_notify(req: TestNotifyRequest):
    """发送测试通知"""
    if req.channel == "all":
        channels = [
            channel for channel in NotifyChannel
            if notification_service.channel_configured(channel)
        ]
    else:
        try:
            channels = [NotifyChannel(req.channel)]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Unknown notification channel: {req.channel}") from exc
    result = await notification_service.notify(
        title="MERAK 通知测试",
        content=req.message,
        level="info",
        extra={"Source": "Manual test"},
        channels=channels,
        require_enabled=False,
        require_verified=False,
    )
    tested_channels = channels
    for channel in tested_channels:
        notification_service._verification_store.record(
            "notification",
            channel.value,
            notification_service.channel_payload(channel),
            channel.value in result["sent"],
            result["errors"].get(channel.value, "Delivery verified"),
        )
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result)
    return {
        "status": "sent",
        **result,
        "verification": {
            channel.value: notification_service.channel_verification(channel)
            for channel in tested_channels
        },
    }
