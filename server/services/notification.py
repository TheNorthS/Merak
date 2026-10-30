"""
通知服务 — 飞书 / Slack / Email

Workflow 完成或失败时发送通知。
支持多通道同时推送。
"""

import asyncio
import html
import os
import json
import smtplib
import sqlite3
from contextlib import closing
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

import structlog

from .connection_verification import ConnectionVerificationStore

logger = structlog.get_logger()


class NotifyChannel(str, Enum):
    FEISHU = "feishu"
    SLACK = "slack"
    EMAIL = "email"


@dataclass
class NotifyConfig:
    """通知配置"""
    feishu_webhook: str = ""
    slack_webhook: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 465
    email_sender: str = ""
    email_password: str = ""
    email_recipients: list[str] = field(default_factory=list)
    enabled_channels: list[NotifyChannel] = field(default_factory=list)


class NotificationService:
    """统一通知服务"""

    def __init__(self, db_path: str | Path = "./merak_ide.db"):
        self._config = NotifyConfig()
        self._db_path = Path(db_path)
        self._verification_store = ConnectionVerificationStore(self._db_path)
        self._load_persisted()
        self._load_from_env()

    def _load_persisted(self):
        try:
            with closing(sqlite3.connect(str(self._db_path), timeout=5)) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS notification_settings (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                )
                row = connection.execute("SELECT payload FROM notification_settings WHERE id = 1").fetchone()
            if not row:
                return
            payload = json.loads(row[0])
            for key, value in payload.items():
                if key == "enabled_channels":
                    value = [NotifyChannel(item) for item in value]
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
        except Exception as exc:
            logger.warning("Failed to load notification settings", error=str(exc))

    def _persist(self):
        payload = {
            "feishu_webhook": self._config.feishu_webhook,
            "slack_webhook": self._config.slack_webhook,
            "email_smtp_host": self._config.email_smtp_host,
            "email_smtp_port": self._config.email_smtp_port,
            "email_sender": self._config.email_sender,
            "email_password": self._config.email_password,
            "email_recipients": self._config.email_recipients,
            "enabled_channels": [item.value for item in self._config.enabled_channels],
        }
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self._db_path), timeout=5)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS notification_settings (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO notification_settings (id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP",
                (json.dumps(payload, ensure_ascii=False),),
            )
            connection.commit()

    def _load_from_env(self):
        """从环境变量加载配置"""
        self._config.feishu_webhook = os.environ.get("FEISHU_WEBHOOK_URL") or self._config.feishu_webhook
        self._config.slack_webhook = os.environ.get("SLACK_WEBHOOK_URL") or self._config.slack_webhook
        self._config.email_smtp_host = os.environ.get("SMTP_HOST") or self._config.email_smtp_host
        self._config.email_smtp_port = int(os.environ.get("SMTP_PORT") or self._config.email_smtp_port)
        self._config.email_sender = os.environ.get("SMTP_SENDER") or self._config.email_sender
        self._config.email_password = os.environ.get("SMTP_PASSWORD") or self._config.email_password
        recipients = os.environ.get("NOTIFY_EMAIL_RECIPIENTS", "")
        if recipients:
            self._config.email_recipients = [r.strip() for r in recipients.split(",") if r.strip()]

        # 自动启用有配置的通道
        if self._config.feishu_webhook:
            if NotifyChannel.FEISHU not in self._config.enabled_channels:
                self._config.enabled_channels.append(NotifyChannel.FEISHU)
        if self._config.slack_webhook:
            if NotifyChannel.SLACK not in self._config.enabled_channels:
                self._config.enabled_channels.append(NotifyChannel.SLACK)
        if self._config.email_smtp_host and self._config.email_sender:
            if NotifyChannel.EMAIL not in self._config.enabled_channels:
                self._config.enabled_channels.append(NotifyChannel.EMAIL)

    def update_config(self, persist: bool = True, **kwargs):
        """更新配置"""
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)
        if persist:
            self._persist()

    def public_config(self) -> dict:
        """Return non-secret configuration details for settings hydration."""
        return {
            "feishu_webhook": bool(self._config.feishu_webhook),
            "slack_webhook": bool(self._config.slack_webhook),
            "email_configured": bool(
                self._config.email_smtp_host
                and self._config.email_sender
                and self._config.email_password
                and self._config.email_recipients
            ),
            "email_smtp_host": self._config.email_smtp_host,
            "email_smtp_port": self._config.email_smtp_port,
            "email_sender": self._config.email_sender,
            "email_recipients": self._config.email_recipients,
            "enabled_channels": [
                channel.value for channel in self._config.enabled_channels
            ],
        }

    def channel_payload(self, channel: NotifyChannel) -> dict:
        if channel == NotifyChannel.FEISHU:
            return {"webhook": self._config.feishu_webhook}
        if channel == NotifyChannel.SLACK:
            return {"webhook": self._config.slack_webhook}
        return {
            "smtp_host": self._config.email_smtp_host,
            "smtp_port": self._config.email_smtp_port,
            "sender": self._config.email_sender,
            "password": self._config.email_password,
            "recipients": list(self._config.email_recipients),
        }

    def channel_configured(self, channel: NotifyChannel) -> bool:
        payload = self.channel_payload(channel)
        if channel in {NotifyChannel.FEISHU, NotifyChannel.SLACK}:
            return bool(payload["webhook"])
        return all([
            payload["smtp_host"],
            payload["sender"],
            payload["password"],
            payload["recipients"],
        ])

    def channel_verification(self, channel: NotifyChannel) -> dict:
        status = self._verification_store.status(
            "notification",
            channel.value,
            self.channel_payload(channel),
        )
        return {
            **status,
            "configured": self.channel_configured(channel),
        }

    async def notify(
        self,
        title: str,
        content: str,
        level: str = "info",
        extra: Optional[dict] = None,
        channels: Optional[list[NotifyChannel]] = None,
        require_enabled: bool = True,
        require_verified: bool = False,
    ) -> dict:
        """发送通知到所有启用的通道

        level: "info" | "success" | "warning" | "error"
        """
        requested = channels if channels is not None else self._config.enabled_channels
        selected = list(requested)
        errors = {}
        if require_enabled:
            disabled = [
                channel for channel in selected
                if channel not in self._config.enabled_channels
            ]
            errors.update({
                channel.value: "Notification channel is not enabled"
                for channel in disabled
            })
            selected = [
                channel for channel in selected
                if channel in self._config.enabled_channels
            ]
        if require_verified:
            unverified = [
                channel for channel in selected
                if not self.channel_verification(channel)["verified"]
            ]
            errors.update({
                channel.value: "Current notification configuration has not passed a delivery test"
                for channel in unverified
            })
            selected = [channel for channel in selected if channel not in unverified]
        if not selected:
            if not errors:
                errors["configuration"] = "No enabled notification channels"
            return {"success": False, "sent": [], "errors": errors}

        tasks = []
        for channel in selected:
            if channel == NotifyChannel.FEISHU:
                tasks.append(self._send_feishu(title, content, level, extra))
            elif channel == NotifyChannel.SLACK:
                tasks.append(self._send_slack(title, content, level, extra))
            elif channel == NotifyChannel.EMAIL:
                tasks.append(self._send_email(title, content, level, extra))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        sent = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors[selected[i].value] = str(result)
                logger.warning("Notification failed", channel=selected[i], error=str(result))
            else:
                sent.append(selected[i].value)
        return {"success": not errors and bool(sent), "sent": sent, "errors": errors}

    async def _send_feishu(self, title: str, content: str, level: str, extra: Optional[dict]):
        """飞书机器人 webhook 通知"""
        if not self._config.feishu_webhook:
            raise RuntimeError("Feishu webhook is not configured")
        try:
            import httpx
        except ImportError:
            raise RuntimeError("pip install httpx")

        # 飞书卡片消息
        color = {"info": "blue", "success": "green", "warning": "orange", "error": "red"}.get(level, "blue")
        emoji = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(level, "ℹ️")

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"{emoji} {title}"},
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                ],
            },
        }

        # 添加额外信息
        if extra:
            fields = []
            for k, v in extra.items():
                fields.append({"is_short": True, "text": {"tag": "lark_md", "content": f"**{k}:** {v}"}})
            if fields:
                card["card"]["elements"].append({"tag": "div", "fields": fields})

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._config.feishu_webhook, json=card)
            if resp.status_code != 200:
                raise RuntimeError(f"Feishu webhook failed: {resp.text}")
            try:
                payload = resp.json()
            except Exception:
                payload = {}
            api_code = payload.get("code", payload.get("StatusCode", 0))
            if api_code not in (None, 0, "0"):
                detail = payload.get("msg") or payload.get("StatusMessage") or resp.text
                raise RuntimeError(f"Feishu webhook rejected the message: {detail}")

        logger.debug("Feishu notification sent", title=title)

    async def _send_slack(self, title: str, content: str, level: str, extra: Optional[dict]):
        """Slack webhook 通知"""
        if not self._config.slack_webhook:
            raise RuntimeError("Slack webhook is not configured")
        try:
            import httpx
        except ImportError:
            raise RuntimeError("pip install httpx")

        color = {"info": "#36a64f", "success": "#2eb886", "warning": "#daa038", "error": "#cc0000"}.get(level, "#36a64f")
        emoji = {"info": ":information_source:", "success": ":white_check_mark:", "warning": ":warning:", "error": ":x:"}.get(level, ":information_source:")

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} {title}",
                    "text": content,
                    "fields": [
                        {"title": k, "value": str(v), "short": True}
                        for k, v in (extra or {}).items()
                    ],
                    "footer": "Merak Research Assistant",
                }
            ]
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._config.slack_webhook, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Slack webhook failed: {resp.text}")
            try:
                response_payload = resp.json()
            except Exception:
                response_payload = None
            if isinstance(response_payload, dict) and response_payload.get("ok") is False:
                raise RuntimeError(
                    f"Slack webhook rejected the message: {response_payload.get('error', 'unknown error')}"
                )

        logger.debug("Slack notification sent", title=title)

    async def _send_email(self, title: str, content: str, level: str, extra: Optional[dict]):
        """邮件通知"""
        if not (
            self._config.email_smtp_host
            and self._config.email_sender
            and self._config.email_password
            and self._config.email_recipients
        ):
            raise RuntimeError("Email notification configuration is incomplete")

        emoji = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(level, "ℹ️")

        # 构建 HTML 邮件
        extra_html = ""
        if extra:
            rows = "".join(
                f"<tr><td><b>{html.escape(str(k))}</b></td>"
                f"<td>{html.escape(str(v))}</td></tr>"
                for k, v in extra.items()
            )
            extra_html = f"<table border='1' cellpadding='5' style='border-collapse:collapse;margin-top:10px'>{rows}</table>"

        escaped_title = html.escape(title)
        escaped_content = html.escape(content)
        html_body = f"""
        <div style="font-family:system-ui;max-width:600px">
            <h2>{emoji} {escaped_title}</h2>
            <div style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:6px">{escaped_content}</div>
            {extra_html}
            <hr style="margin-top:20px">
            <p style="color:#888;font-size:12px">Sent by Merak Research Assistant</p>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Merak] {emoji} {title}"
        msg["From"] = self._config.email_sender
        msg["To"] = ", ".join(self._config.email_recipients)
        msg.attach(MIMEText(content, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # 使用线程池避免阻塞
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._smtp_send, msg)
        logger.debug("Email notification sent", title=title, recipients=len(self._config.email_recipients))

    def _smtp_send(self, msg: MIMEMultipart):
        """同步发送邮件"""
        if self._config.email_smtp_port == 465:
            server = smtplib.SMTP_SSL(self._config.email_smtp_host, self._config.email_smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(self._config.email_smtp_host, self._config.email_smtp_port, timeout=15)
            server.starttls()

        server.login(self._config.email_sender, self._config.email_password)
        server.send_message(msg)
        server.quit()

    # ==================== 便捷方法 ====================

    async def workflow_completed(self, workflow_name: str, duration_s: float, nodes_completed: int):
        """Workflow 完成通知"""
        minutes = duration_s / 60
        return await self.notify(
            title=f"Workflow 完成: {workflow_name}",
            content=f"工作流已成功完成所有 {nodes_completed} 个节点。",
            level="success",
            extra={"Duration": f"{minutes:.1f} min", "Nodes": str(nodes_completed)},
            require_verified=True,
        )

    async def workflow_failed(self, workflow_name: str, node_name: str, error: str):
        """Workflow 失败通知"""
        return await self.notify(
            title=f"Workflow 失败: {workflow_name}",
            content=f"节点 `{node_name}` 执行失败:\n{error[:500]}",
            level="error",
            extra={"Failed Node": node_name},
            require_verified=True,
        )

    async def experiment_completed(self, experiment_name: str, metrics: dict):
        """实验完成通知"""
        metrics_str = "\n".join(f"- {k}: {v}" for k, v in metrics.items())
        return await self.notify(
            title=f"实验完成: {experiment_name}",
            content=f"实验结果:\n{metrics_str}" if metrics_str else "实验已完成。",
            level="success",
            extra=metrics,
            require_verified=True,
        )

    async def audit_alert(self, layer: str, verdict: str, reason: str):
        """审计告警"""
        level = "error" if verdict == "FAIL" else "warning"
        return await self.notify(
            title=f"审计告警: {layer} → {verdict}",
            content=reason,
            level=level,
            extra={"Layer": layer, "Verdict": verdict},
            require_verified=True,
        )


# 全局实例
notification_service = NotificationService()
