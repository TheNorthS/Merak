"""Report invalid notification setup once per configuration, without sending messages."""
import hashlib
import json
from typing import Any


async def notification_ready(ctx: Any, service: Any) -> bool:
    if not service._config.enabled_channels:
        return False
    invalid = {channel.value: service.channel_verification(channel) for channel in service._config.enabled_channels
               if not service.channel_verification(channel).get("verified")}
    if not invalid:
        return True
    fingerprint = hashlib.sha256(json.dumps(invalid, sort_keys=True, default=str).encode()).hexdigest()
    saved = ctx.run_state.load() or {}
    if saved.get("notification_warning_signature") != fingerprint:
        ctx.run_state.update_state(lambda state: state.update(notification_warning_signature=fingerprint))
        await ctx.host._emit(ctx.run, "notification_configuration_required", {
            "channels": list(invalid), "message": "通知配置尚未通过投递测试；本次跳过通知，工作流结果不受影响。",
        })
    return False
