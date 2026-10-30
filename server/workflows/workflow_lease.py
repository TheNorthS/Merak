"""Process-safe active-workflow lease for one project."""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock


LEASE_RENEWAL_GRACE_SECONDS = 90.0


def _effective_lease_expiry(claim: Any) -> float:
    """Bound crash recovery by the last successful heartbeat.

    ``expires_at`` prevents early takeover, while ``renewed_at`` prevents a
    killed backend from blocking the same project for the old one-hour TTL.
    Active workflow owners renew every 30 seconds, so three missed heartbeats
    are sufficient evidence that the lease is orphaned.
    """

    if not isinstance(claim, dict):
        return 0.0
    try:
        expires_at = float(claim.get("expires_at") or 0.0)
    except (TypeError, ValueError):
        expires_at = 0.0
    try:
        renewed_at = float(
            claim.get("renewed_at") or claim.get("claimed_at") or 0.0
        )
    except (TypeError, ValueError):
        renewed_at = 0.0
    if renewed_at > 0:
        return min(expires_at, renewed_at + LEASE_RENEWAL_GRACE_SECONDS)
    return expires_at



class ProjectRunLease:
    """One durable active-workflow lease for a project across processes."""

    MARKER_STALE_GRACE_SECONDS = 5.0

    def __init__(self, project_path: str):
        self.project_path = Path(project_path or ".").expanduser().resolve()
        self.path = self.project_path / ".merak" / "active-workflow.json"
        self.marker_path = self.path.with_suffix(".claim")

    def _create_claim_marker(self, token: str) -> bool:
        """Create the process-independent claim marker with create-only semantics."""

        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.marker_path.open("x", encoding="utf-8") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False

    def _acquire_claim_marker(
        self,
        token: str,
        *,
        existing_expires_at: float,
        now: float,
    ) -> bool:
        """Win the durable slot even if an underlying advisory lock misbehaves."""

        if self._create_claim_marker(token):
            return True
        if existing_expires_at > now:
            return False
        if existing_expires_at <= 0:
            try:
                marker_age = max(0.0, now - self.marker_path.stat().st_mtime)
            except FileNotFoundError:
                marker_age = self.MARKER_STALE_GRACE_SECONDS
            except OSError:
                return False
            if marker_age < self.MARKER_STALE_GRACE_SECONDS:
                # Another process may have created the marker immediately before
                # committing its lease JSON. Fail closed instead of stealing it.
                return False
        try:
            self.marker_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return self._create_claim_marker(token)

    def _release_claim_marker(self, token: str) -> None:
        """Remove only the marker owned by ``token``."""

        try:
            current = self.marker_path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            ).strip()
            if current == token:
                self.marker_path.unlink()
        except (FileNotFoundError, OSError):
            pass

    def _load_unlocked(self) -> dict[str, Any]:
        for attempt in range(6):
            try:
                raw = self.path.read_text(encoding="utf-8-sig")
                break
            except FileNotFoundError:
                return {}
            except OSError as exc:
                retryable = (
                    isinstance(exc, PermissionError)
                    or getattr(exc, "winerror", None) in {5, 32}
                )
                if retryable and attempt < 5:
                    time.sleep(min(0.25, 0.01 * (2 ** attempt)))
                    continue
                raise RuntimeError(
                    f"Active workflow lease is unreadable: {self.path}"
                ) from exc
        try:
            payload = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            # Claiming over an unreadable/corrupt record could start a second
            # workflow while an earlier owner is still active. Fail closed and
            # require explicit recovery instead.
            raise RuntimeError(
                f"Active workflow lease is corrupt: {self.path}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Active workflow lease is corrupt: {self.path}"
            )
        return payload

    def active_claim(self) -> dict[str, Any]:
        """Return only a currently live claim."""

        with path_lock(self.path):
            claim = self._load_unlocked()
            expires_at = _effective_lease_expiry(claim)
            if not str(claim.get("token") or "") or expires_at <= time.time():
                return {}
            return copy.deepcopy(claim)

    def claim(
        self,
        *,
        run_id: str,
        owner_id: str,
        source: str = "fresh",
        lease_seconds: float = 86400.0,
    ) -> str:
        """Compare-and-set the single active workflow slot for this project."""

        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return ""
        with path_lock(self.path):
            existing = self._load_unlocked()
            now = time.time()
            existing_expires_at = _effective_lease_expiry(existing)
            if str(existing.get("token") or "") and existing_expires_at > now:
                return ""
            token = uuid.uuid4().hex
            if not self._acquire_claim_marker(
                token,
                existing_expires_at=existing_expires_at,
                now=now,
            ):
                return ""
            try:
                atomic_write_json(
                    self.path,
                    {
                        "schema": 1,
                        "run_id": clean_run_id,
                        "token": token,
                        "owner_id": str(owner_id or ""),
                        "source": str(source or "fresh"),
                        "claimed_at": now,
                        "renewed_at": now,
                        "expires_at": now + max(60.0, float(lease_seconds)),
                    },
                )
            except BaseException:
                self._release_claim_marker(token)
                raise
            return token

    def renew(
        self,
        token: str,
        *,
        run_id: str,
        lease_seconds: float = 86400.0,
    ) -> bool:
        with path_lock(self.path):
            claim = self._load_unlocked()
            if (
                not isinstance(claim, dict)
                or claim.get("token") != token
                or str(claim.get("run_id") or "") != str(run_id or "")
            ):
                return False
            now = time.time()
            claim["renewed_at"] = now
            claim["expires_at"] = now + max(60.0, float(lease_seconds))
            atomic_write_json(self.path, claim)
            return True

    def release(self, token: str, *, run_id: str) -> bool:
        with path_lock(self.path):
            claim = self._load_unlocked()
            if (
                not isinstance(claim, dict)
                or claim.get("token") != token
                or str(claim.get("run_id") or "") != str(run_id or "")
            ):
                return False
            # Keep an auditable but immediately expired record. Avoid unlink races
            # with readers and let the next claimant atomically replace it.
            now = time.time()
            claim["released_at"] = now
            claim["expires_at"] = now
            atomic_write_json(self.path, claim)
            self._release_claim_marker(token)
            return True



