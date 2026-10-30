"""Versioned password hashing built on Python's OpenSSL-backed scrypt."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


class PasswordHashError(ValueError):
    """Raised when a stored password hash is malformed or unsupported."""


class ScryptPasswordHasher:
    algorithm = "scrypt"
    n = 2**14
    r = 8
    p = 1
    salt_bytes = 16
    key_bytes = 32

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        try:
            return base64.urlsafe_b64decode(value + padding)
        except (ValueError, TypeError) as exc:
            raise PasswordHashError("Malformed password hash encoding") from exc

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(self.salt_bytes)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=self.n,
            r=self.r,
            p=self.p,
            dklen=self.key_bytes,
        )
        return "$".join((
            self.algorithm,
            str(self.n),
            str(self.r),
            str(self.p),
            self._encode(salt),
            self._encode(derived),
        ))

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, raw_n, raw_r, raw_p, raw_salt, raw_key = encoded.split("$")
            if algorithm != self.algorithm:
                return False
            n, r, p = int(raw_n), int(raw_r), int(raw_p)
            if (n, r, p) != (self.n, self.r, self.p):
                return False
            salt, expected = self._decode(raw_salt), self._decode(raw_key)
            actual = hashlib.scrypt(
                password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                dklen=len(expected),
            )
        except (ValueError, PasswordHashError):
            return False
        return hmac.compare_digest(actual, expected)
