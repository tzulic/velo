"""DM pairing code management for granting channel access."""

from __future__ import annotations

import json
import secrets
import string
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LEN = 4
_CODE_PREFIX = "VELO-"


@dataclass
class _PairingCode:
    code: str
    max_uses: int = 1
    uses: int = 0
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)


class PairingManager:
    """Manages pairing codes for granting channel access.

    Args:
        workspace: Agent workspace path.
        max_uses: Default max uses per code.
        max_attempts_per_hour: Rate limit for validation attempts.
    """

    def __init__(self, workspace: Path, max_uses: int = 1, max_attempts_per_hour: int = 5) -> None:
        self._workspace = workspace
        self._default_max_uses = max_uses
        self._max_attempts = max_attempts_per_hour
        self._codes_file = workspace / "pairing_codes.json"
        self._allowlist_file = workspace / "pairing_allowlist.json"
        self._codes: dict[str, _PairingCode] = {}
        self._allowlist: dict[str, list[str]] = {}
        self._attempts: dict[str, list[float]] = {}
        self._load()

    def _load(self) -> None:
        """Load persisted codes and allowlist from disk."""
        if self._codes_file.exists():
            try:
                data = json.loads(self._codes_file.read_text())
                for code, info in data.items():
                    self._codes[code] = _PairingCode(**info)
            except (json.JSONDecodeError, TypeError):
                pass
        if self._allowlist_file.exists():
            try:
                self._allowlist = json.loads(self._allowlist_file.read_text())
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        """Persist codes and allowlist to disk."""
        codes_data = {}
        for code, pc in self._codes.items():
            codes_data[code] = {
                "code": pc.code,
                "max_uses": pc.max_uses,
                "uses": pc.uses,
                "expires_at": pc.expires_at,
                "created_at": pc.created_at,
            }
        self._codes_file.write_text(json.dumps(codes_data, indent=2))
        self._allowlist_file.write_text(json.dumps(self._allowlist, indent=2))

    def generate_code(self, max_uses: int | None = None, expires_hours: int = 24) -> str:
        """Generate a unique pairing code.

        Args:
            max_uses: Maximum number of times this code can be used (default: instance default).
            expires_hours: Hours until the code expires (default: 24).

        Returns:
            str: A unique pairing code in the format "VELO-XXXX".
        """
        suffix = "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LEN))
        code = f"{_CODE_PREFIX}{suffix}"
        # Reason: collision is unlikely but possible; loop ensures uniqueness
        while code in self._codes:
            suffix = "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LEN))
            code = f"{_CODE_PREFIX}{suffix}"
        self._codes[code] = _PairingCode(
            code=code,
            max_uses=max_uses if max_uses is not None else self._default_max_uses,
            expires_at=time.time() + (expires_hours * 3600),
        )
        self._save()
        logger.info("pairing.code_generated: {}", code)
        return code

    def validate_code(self, code: str, sender_id: str, channel: str) -> bool:
        """Validate a pairing code and add the sender to the allowlist on success.

        Args:
            code: The pairing code to validate.
            sender_id: The unique identifier of the sender (e.g. Telegram user ID).
            channel: The channel name (e.g. "telegram").

        Returns:
            bool: True if the code is valid and the sender has been paired, False otherwise.
        """
        now = time.time()

        # Rate limiting: count attempts in the last hour
        attempts = self._attempts.get(sender_id, [])
        attempts = [t for t in attempts if now - t < 3600]
        if len(attempts) >= self._max_attempts:
            logger.warning("pairing.rate_limited: sender={}", sender_id)
            return False
        attempts.append(now)
        self._attempts[sender_id] = attempts

        pc = self._codes.get(code)
        if pc is None:
            return False
        if now > pc.expires_at:
            return False
        if pc.uses >= pc.max_uses:
            return False

        pc.uses += 1
        if channel not in self._allowlist:
            self._allowlist[channel] = []
        if sender_id not in self._allowlist[channel]:
            self._allowlist[channel].append(sender_id)
        self._save()
        logger.info("pairing.validated: code={} sender={} channel={}", code, sender_id, channel)
        return True

    def is_paired(self, sender_id: str, channel: str) -> bool:
        """Check if a sender is in the allowlist for a given channel.

        Args:
            sender_id: The unique identifier of the sender.
            channel: The channel name.

        Returns:
            bool: True if the sender is paired, False otherwise.
        """
        return sender_id in self._allowlist.get(channel, [])
