"""Vast.ai provider orchestration for managed experiment runs."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace
from typing import Any, Optional

from .experiment_runtime_state import RunManifestStore, RuntimeOutcome, RuntimeSpec
from .ssh_manager import SSHServerConfig, ssh_manager

_BASE_URL = "https://console.vast.ai/api/v0"


class VastRuntimeMixin:
    async def _run_vast(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        snapshot: dict[str, Any],
        attempt_number: int,
        on_event: Any,
    ) -> RuntimeOutcome:
        api_key = os.environ.get("VASTAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("VASTAI_API_KEY is not configured")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("Vast.ai requires httpx") from exc
        headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
        instance_id: Optional[int] = None
        server_id = ""
        preserve = False
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            try:
                offer = await self._select_vast_offer(
                    client, spec, store, attempt_number, on_event, headers
                )
                instance_id = await self._create_vast_instance(
                    client, spec, store, attempt_number, offer, headers
                )
                host, port = await self._wait_for_vast_ssh(
                    client, _BASE_URL, headers, instance_id, spec
                )
                self._raise_if_stop_requested(spec)
                server_id = self._register_vast_ssh(
                    spec, instance_id, host, port, offer
                )
                started = time.time()
                outcome = await self._run_ssh(
                    replace(
                        spec, backend="vast_ai", server_id=server_id,
                        remote_base_dir="/workspace/.merak/runs",
                    ),
                    store, snapshot, attempt_number, on_event,
                )
                outcome.metadata.update({
                    "instance_id": instance_id,
                    "gpu": offer.get("gpu_name"),
                    "hourly_usd": float(offer.get("dph_total") or 0),
                    "estimated_cost_usd": round(
                        float(offer.get("dph_total") or 0)
                        * (time.time() - started) / 3600, 4
                    ),
                })
                return outcome
            except asyncio.CancelledError:
                preserve = not bool(self.stop_reason(spec.run_id))
                raise
            finally:
                await self._cleanup_vast(
                    client, spec, store, on_event, headers,
                    instance_id, server_id, preserve,
                )

    async def _select_vast_offer(
        self, client: Any, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, on_event: Any, headers: dict[str, str],
    ) -> dict[str, Any]:
        store.update_attempt(attempt, status="precheck", provider="vast_ai")
        search = {
            "verified": {"eq": True}, "rentable": {"eq": True},
            "num_gpus": {"gte": 1}, "gpu_ram": {"gte": spec.vast_gpu_ram_mb},
            "reliability": {"gte": 0.95}, "order": [["dph_total", "asc"]],
            "limit": 10,
        }
        response = await client.post(f"{_BASE_URL}/bundles/", json=search, headers=headers)
        if not response.is_success:
            raise RuntimeError(
                f"Vast.ai offer search failed: HTTP {response.status_code} {response.text[:500]}"
            )
        eligible = [
            offer for offer in response.json().get("offers", [])
            if float(offer.get("dph_total") or 0) <= spec.vast_max_hourly_usd
        ]
        if not eligible:
            raise RuntimeError(
                f"No Vast.ai offer met GPU RAM/reliability and ${spec.vast_max_hourly_usd:.2f}/h cost limit"
            )
        offer = eligible[0]
        maximum_cost = float(offer.get("dph_total") or 0) * spec.timeout_seconds / 3600
        if maximum_cost > spec.max_remote_cost_usd:
            raise RuntimeError(
                f"Vast.ai worst-case cost ${maximum_cost:.2f} exceeds run budget ${spec.max_remote_cost_usd:.2f}"
            )
        await self._emit(on_event, "experiment_provider_selected", {
            "run_id": spec.run_id, "backend": "vast_ai",
            "offer_id": offer.get("id"), "gpu": offer.get("gpu_name"),
            "hourly_usd": float(offer.get("dph_total") or 0),
            "maximum_cost_usd": maximum_cost,
        })
        return offer

    @staticmethod
    async def _create_vast_instance(
        client: Any, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, offer: dict[str, Any], headers: dict[str, str],
    ) -> int:
        payload = {
            "client_id": "me", "image": spec.vast_image, "disk": spec.vast_disk_gb,
            "onstart": "#!/bin/bash\nmkdir -p /workspace\n",
        }
        response = await client.put(
            f"{_BASE_URL}/asks/{offer['id']}/", json=payload, headers=headers
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Vast.ai instance creation failed: {response.text[:500]}")
        instance_id = int(response.json().get("new_contract"))
        store.update_attempt(attempt, provider_metadata={
            "instance_id": instance_id, "offer_id": offer.get("id"),
            "gpu": offer.get("gpu_name"),
            "hourly_usd": float(offer.get("dph_total") or 0),
            "auto_destroy": spec.auto_destroy,
        })
        return instance_id

    @staticmethod
    def _register_vast_ssh(
        spec: RuntimeSpec, instance_id: int, host: str, port: int,
        offer: dict[str, Any],
    ) -> str:
        server_id = f"vast_{instance_id}_{spec.run_id}"
        ssh_manager.add_server(SSHServerConfig(
            id=server_id, name=f"Vast.ai {instance_id}", host=host,
            port=port, username="root", work_dir="/workspace", gpu_count=1,
            gpu_type=str(offer.get("gpu_name") or ""),
        ))
        return server_id

    async def _cleanup_vast(
        self, client: Any, spec: RuntimeSpec, store: RunManifestStore,
        on_event: Any, headers: dict[str, str], instance_id: Optional[int],
        server_id: str, preserve: bool,
    ) -> None:
        if server_id:
            try:
                await ssh_manager.disconnect(server_id)
            finally:
                ssh_manager._configs.pop(server_id, None)
        if instance_id is None or not spec.auto_destroy or preserve:
            return
        try:
            response = await client.delete(
                f"{_BASE_URL}/instances/{instance_id}/", headers=headers
            )
            destroyed = response.is_success
            store.update(provider_cleanup={"instance_id": instance_id,
                         "status": "destroyed" if destroyed else "cleanup_required",
                         "http_status": response.status_code})
            store.append_event("vast_instance_destroyed" if destroyed else "vast_cleanup_failed", {
                "instance_id": instance_id, "http_status": response.status_code,
            })
            await self._emit(on_event, "experiment_provider_cleanup", {
                "run_id": spec.run_id, "backend": "vast_ai",
                "instance_id": instance_id, "destroyed": response.is_success,
            })
        except Exception as exc:
            store.update(provider_cleanup={"instance_id": instance_id,
                         "status": "cleanup_required", "error": str(exc)})
            store.append_event("vast_cleanup_failed", {
                "instance_id": instance_id, "error": str(exc),
            })
            await self._emit(on_event, "experiment_provider_cleanup", {
                "run_id": spec.run_id, "backend": "vast_ai", "instance_id": instance_id,
                "destroyed": False, "error": str(exc),
            })
