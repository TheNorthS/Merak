"""Provider-safe context preparation for agent sessions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from . import Message, ModelProvider
from .session_models import AgentEvent, AgentSession


# Working context is deliberately bounded even when a gateway advertises a
# larger model window. Full tool outputs remain in the durable transcript.
DEFAULT_WORKING_CONTEXT_TOKENS = 64_000


class AgentContextMixin:
    def _messages_for_model(self, messages: list[Message], system_prompt_override: Optional[str]) -> list[Message]:
        if not system_prompt_override:
            return messages
        if messages and messages[0].role == "system":
            merged_system = f"{messages[0].content}\n\n{system_prompt_override}"
            return [Message(role="system", content=merged_system), *messages[1:]]
        return [Message(role="system", content=system_prompt_override), *messages]

    @staticmethod
    def _clone_message(message: Message) -> Message:
        return Message(
            role=message.role,
            content=message.content or "",
            tool_calls=[dict(item) for item in message.tool_calls],
            tool_call_id=message.tool_call_id,
            name=message.name,
        )

    @staticmethod
    def _message_token_estimate(message: Message) -> int:
        payload = message.content or ""
        if message.tool_calls:
            payload += json.dumps(
                message.tool_calls,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        return max(4, (len(payload) + 3) // 4 + 8)

    def _persist_session_transcript(
        self, session: AgentSession,
    ) -> Optional[Path]:
        from .session_persistence import persist_session_transcript

        return persist_session_transcript(session)
    def restore_session(
        self, session_id: str, project_path: str, *, system_prompt: str = "",
    ) -> Optional[AgentSession]:
        from .session_persistence import restore_session

        return restore_session(
            self._sessions, session_id, project_path,
            system_prompt=system_prompt,
        )
    def _repair_tool_message_pairs(
        self,
        messages: list[Message],
    ) -> tuple[list[Message], int]:
        """Return a provider-safe view with complete, unique tool pairs."""
        repaired: list[Message] = []
        seen_ids: set[str] = set()
        repair_count = 0
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "tool":
                # An orphan tool result is invalid for OpenAI and Anthropic
                # message protocols. It remains in the persisted transcript.
                repair_count += 1
                index += 1
                continue
            if message.role != "assistant" or not message.tool_calls:
                repaired.append(self._clone_message(message))
                index += 1
                continue

            following: list[Message] = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                following.append(messages[cursor])
                cursor += 1
            used_results: set[int] = set()
            normalized_calls: list[dict[str, Any]] = []
            normalized_results: list[Message] = []
            for call_index, raw_call in enumerate(message.tool_calls):
                call = dict(raw_call)
                original_id = str(call.get("id") or "").strip()
                normalized_id = original_id
                if not normalized_id or normalized_id in seen_ids:
                    seed = (
                        f"{index}:{call_index}:{original_id}:"
                        f"{call.get('name') or ''}"
                    )
                    normalized_id = (
                        "merak_tool_"
                        + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
                    )
                    repair_count += 1
                seen_ids.add(normalized_id)
                call["id"] = normalized_id
                normalized_calls.append(call)

                matching_index = next((
                    result_index
                    for result_index, result in enumerate(following)
                    if result_index not in used_results
                    and str(result.tool_call_id or "") == original_id
                ), None)
                if matching_index is None:
                    normalized_results.append(Message(
                        role="tool",
                        content=(
                            "Tool result unavailable because the prior session "
                            "was interrupted before the result was recorded."
                        ),
                        tool_call_id=normalized_id,
                    ))
                    repair_count += 1
                else:
                    used_results.add(matching_index)
                    result = self._clone_message(following[matching_index])
                    result.tool_call_id = normalized_id
                    normalized_results.append(result)

            repair_count += max(0, len(following) - len(used_results))
            assistant = self._clone_message(message)
            assistant.tool_calls = normalized_calls
            repaired.extend([assistant, *normalized_results])
            index = cursor
        return repaired, repair_count

    @staticmethod
    def _context_units(messages: list[Message]) -> list[list[Message]]:
        """Group assistant tool calls with all of their tool results."""
        units: list[list[Message]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            unit = [message]
            index += 1
            if message.role == "assistant" and message.tool_calls:
                while index < len(messages) and messages[index].role == "tool":
                    unit.append(messages[index])
                    index += 1
            units.append(unit)
        return units

    @staticmethod
    def _compaction_summary(
        omitted: list[Message],
        *,
        max_chars: int = 12000,
    ) -> str:
        tool_counts: dict[str, int] = {}
        paths: list[str] = []
        errors: list[str] = []
        constraints: list[str] = []
        for message in omitted:
            if message.role == "user" and message.content:
                clean = " ".join(message.content.split())
                if clean and clean not in constraints:
                    constraints.append(clean[:320])
            for call in message.tool_calls:
                name = str(call.get("name") or "unknown")
                tool_counts[name] = tool_counts.get(name, 0) + 1
                arguments = call.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                if isinstance(arguments, dict):
                    for key in ("path", "file_path", "target_path", "cwd"):
                        value = str(arguments.get(key) or "").strip()
                        if value and value not in paths:
                            paths.append(value)
            if message.role == "tool" and message.content:
                clean = " ".join(message.content.split())
                if re.search(
                    r"(?:error|failed|exception|timeout|invalid|missing|blocked)",
                    clean,
                    re.IGNORECASE,
                ) and clean not in errors:
                    errors.append(clean[:400])
        lines = [
            "[MERAK deterministic context compaction]",
            f"Earlier messages omitted from the model view: {len(omitted)}.",
            "The complete transcript remains persisted under .merak/agent-sessions/.",
        ]
        if constraints:
            lines.append("Earlier user constraints:")
            lines.extend(f"- {item}" for item in constraints[-8:])
        if tool_counts:
            lines.append(
                "Earlier tool activity: "
                + ", ".join(
                    f"{name} x{count}"
                    for name, count in sorted(tool_counts.items())
                )
                + "."
            )
        if paths:
            lines.append("Files and working paths already referenced:")
            lines.extend(f"- {item}" for item in paths[-24:])
        if errors:
            lines.append("Unresolved or error observations retained from earlier turns:")
            lines.extend(f"- {item}" for item in errors[-12:])
        return "\n".join(lines)[:max(256, max_chars)]

    @classmethod
    def _compact_oversized_unit(
        cls,
        unit: list[Message],
        token_budget: int,
    ) -> list[Message]:
        """Keep a provider-valid digest of one oversized conversational unit."""
        token_budget = max(64, token_budget)
        compacted: list[Message] = []
        content_budget = max(128, token_budget * 4 // max(1, len(unit)))
        for message in unit:
            clone = cls._clone_message(message)
            if clone.tool_calls:
                calls: list[dict[str, Any]] = []
                for raw_call in clone.tool_calls:
                    call = dict(raw_call)
                    arguments = call.get("arguments")
                    parsed_arguments = arguments
                    if isinstance(arguments, str):
                        try:
                            parsed_arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            parsed_arguments = arguments
                    if isinstance(parsed_arguments, dict):
                        bounded_arguments: dict[str, Any] = {}
                        for key, value in parsed_arguments.items():
                            if isinstance(value, str) and len(value) > 2048:
                                digest = hashlib.sha256(
                                    value.encode("utf-8")
                                ).hexdigest()[:16]
                                bounded_arguments[str(key)] = (
                                    f"[omitted {len(value)} chars; sha256={digest}]"
                                )
                            else:
                                bounded_arguments[str(key)] = value
                        call["arguments"] = bounded_arguments
                    elif isinstance(parsed_arguments, str) and len(parsed_arguments) > 2048:
                        digest = hashlib.sha256(
                            parsed_arguments.encode("utf-8")
                        ).hexdigest()[:16]
                        call["arguments"] = (
                            f"[omitted {len(parsed_arguments)} chars; sha256={digest}]"
                        )
                    calls.append(call)
                clone.tool_calls = calls

            content = clone.content or ""
            if len(content) > content_budget:
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
                preview_chars = max(48, content_budget - 120)
                clone.content = (
                    content[:preview_chars]
                    + f"\n[MERAK omitted {len(content) - preview_chars} chars "
                    f"from oversized context; sha256={digest}]"
                )
            compacted.append(clone)

        while (
            len(compacted) > 1
            and sum(cls._message_token_estimate(item) for item in compacted)
            > token_budget
        ):
            # Preserve the assistant tool call and one result digest. Extra
            # results remain in the durable transcript and compaction summary.
            compacted.pop()
        if (
            compacted
            and sum(cls._message_token_estimate(item) for item in compacted)
            > token_budget
        ):
            message = compacted[0]
            available_chars = max(64, (token_budget - 24) * 4)
            message.content = (message.content or "")[:available_chars]
        return compacted

    def _compact_model_messages(
        self, messages: list[Message], token_limit: int,
    ) -> tuple[list[Message], dict[str, Any]]:
        """Compact old units while preserving the system/task and recent pairs."""
        estimate_before = sum(self._message_token_estimate(item) for item in messages)
        if estimate_before <= token_limit:
            return messages, {
                "compacted": False,
                "estimated_tokens_before": estimate_before,
                "estimated_tokens_after": estimate_before,
                "omitted_messages": 0,
            }
        prefix, remaining, prefix_tokens = self._context_prefix(
            messages, token_limit
        )
        selected, omitted, selected_tokens = self._recent_context_selection(
            remaining, token_limit, prefix_tokens
        )
        summary_budget = max(
            64, token_limit - prefix_tokens - selected_tokens - 24
        )
        summary = Message(
            role="user",
            content=self._compaction_summary(
                omitted, max_chars=min(12000, summary_budget * 4)
            ),
        )
        compacted = [*prefix, summary, *selected]
        estimate_after = sum(
            self._message_token_estimate(item) for item in compacted
        )
        if estimate_after > token_limit:
            overflow = estimate_after - token_limit
            summary.content = summary.content[:max(
                256, len(summary.content) - overflow * 4 - 64
            )]
            estimate_after = sum(
                self._message_token_estimate(item) for item in compacted
            )
        return compacted, {
            "compacted": True,
            "estimated_tokens_before": estimate_before,
            "estimated_tokens_after": estimate_after,
            "omitted_messages": len(omitted),
            "retained_messages": len(compacted),
            "token_limit": token_limit,
        }

    def _context_prefix(
        self, messages: list[Message], token_limit: int,
    ) -> tuple[list[Message], list[Message], int]:
        system = [item for item in messages if item.role == "system"]
        non_system = [item for item in messages if item.role != "system"]
        initial_task: list[Message] = []
        remaining = non_system
        for index, message in enumerate(non_system):
            if message.role == "user":
                initial_task = [message]
                remaining = non_system[:index] + non_system[index + 1:]
                break
        prefix = [*system, *initial_task]
        prefix_tokens = sum(self._message_token_estimate(item) for item in prefix)
        prefix_budget = max(128, int(token_limit * 0.60))
        if prefix_tokens > prefix_budget:
            per_message = max(64, prefix_budget // max(1, len(prefix)))
            prefix = [
                compacted
                for message in prefix
                for compacted in self._compact_oversized_unit([message], per_message)
            ]
            prefix_tokens = sum(
                self._message_token_estimate(item) for item in prefix
            )
        return prefix, remaining, prefix_tokens

    def _recent_context_selection(
        self, remaining: list[Message], token_limit: int, prefix_tokens: int,
    ) -> tuple[list[Message], list[Message], int]:
        units = self._context_units(remaining)
        selected_reversed: list[list[Message]] = []
        selected_tokens = 0
        reserve = min(3000, max(64, token_limit // 8))
        recent_budget = max(64, token_limit - prefix_tokens - reserve - 32)
        for unit in reversed(units):
            unit_tokens = sum(self._message_token_estimate(item) for item in unit)
            if selected_tokens + unit_tokens > recent_budget:
                if not selected_reversed:
                    compacted = self._compact_oversized_unit(unit, recent_budget)
                    compacted_tokens = sum(
                        self._message_token_estimate(item) for item in compacted
                    )
                    if compacted and compacted_tokens <= recent_budget:
                        selected_reversed.append(compacted)
                        selected_tokens += compacted_tokens
                break
            selected_reversed.append(unit)
            selected_tokens += unit_tokens
        selected_units = list(reversed(selected_reversed))
        omitted_count = max(0, len(units) - len(selected_units))
        omitted = [message for unit in units[:omitted_count] for message in unit]
        selected = [message for unit in selected_units for message in unit]
        return selected, omitted, selected_tokens
    async def _prepare_messages_for_model(
        self,
        *,
        session: AgentSession,
        provider: ModelProvider,
        system_prompt_override: Optional[str],
        max_tokens: int,
        on_event: Optional[Callable[[AgentEvent], Any]],
    ) -> list[Message]:
        """Persist the full transcript and build a bounded provider-safe view."""
        transcript_path = self._persist_session_transcript(session)
        merged = self._messages_for_model(
            session.messages,
            system_prompt_override,
        )
        repaired, repair_count = self._repair_tool_message_pairs(merged)
        repair_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    (item.role, item.tool_call_id, item.tool_calls)
                    for item in repaired
                ],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        if repair_count and repair_fingerprint != session.last_repair_fingerprint:
            session.last_repair_fingerprint = repair_fingerprint
            await self._emit(on_event, AgentEvent(type="context_repaired", data={
                "session_id": session.id,
                "repair_count": repair_count,
                "transcript_path": str(transcript_path or ""),
            }))

        try:
            provider_context = int(provider.max_context)
        except (TypeError, ValueError, AttributeError):
            provider_context = 1_000_000
        if session.context_token_limit > 0:
            token_limit = max(128, int(session.context_token_limit))
        else:
            available = max(16_000, provider_context - max_tokens - 4096)
            token_limit = min(DEFAULT_WORKING_CONTEXT_TOKENS, max(16_000, int(available * 0.72)))
        from .review_read_progress import with_review_read_progress
        repaired = with_review_read_progress(repaired, session)
        compacted, info = self._compact_model_messages(repaired, token_limit)
        if info.get("compacted"):
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        (item.role, item.content, item.tool_call_id, item.tool_calls)
                        for item in compacted
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:20]
            if fingerprint != session.last_compaction_fingerprint:
                session.last_compaction_fingerprint = fingerprint
                session.context_compactions += 1
                await self._emit(on_event, AgentEvent(type="context_compacted", data={
                    "session_id": session.id,
                    "compaction_count": session.context_compactions,
                    "transcript_path": str(transcript_path or ""),
                    **info,
                }))
        return compacted

