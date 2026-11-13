from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from dotenv import dotenv_values


ROOT_DIR = Path(__file__).resolve().parents[2]
ACCOUNT_SPECS = (
    ("TEST_ADMIN_A", "agency_a", "admin"),
    ("TEST_AGENT_A", "agency_a", "agent"),
    ("TEST_SUBAGENT_A", "agency_a", "subagent"),
    ("TEST_ADMIN_B", "agency_b", "admin"),
    ("TEST_AGENT_B", "agency_b", "agent"),
)


@dataclass(frozen=True)
class VaultAccount:
    username: str
    password: str
    agency_id: str
    role: str


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Vault:
    def __init__(self, accounts: Mapping[str, VaultAccount]) -> None:
        self._accounts = dict(accounts)
        self._token_accounts: dict[str, str] = {}
        self._lock = Lock()

    @classmethod
    def from_env(cls, root_dir: Path = ROOT_DIR) -> Vault:
        values: dict[str, str] = {}
        for path in (root_dir / ".env.example", root_dir / ".env"):
            for key, value in dotenv_values(path).items():
                if value is not None:
                    values[key] = value
        values.update(os.environ)

        accounts: dict[str, VaultAccount] = {}
        for prefix, agency_id, role in ACCOUNT_SPECS:
            username = values.get(f"{prefix}_USERNAME", prefix.lower())
            password = values.get(f"{prefix}_PASSWORD", "")
            if not username or not password:
                raise ValueError(f"Missing test credentials for {prefix}.")
            accounts[username] = VaultAccount(
                username=username,
                password=password,
                agency_id=agency_id,
                role=role,
            )
        return cls(accounts)

    def account(self, username: str) -> VaultAccount | None:
        return self._accounts.get(username)

    def accounts(self) -> tuple[VaultAccount, ...]:
        return tuple(self._accounts.values())

    def validate_login(self, username: object, password: object) -> bool:
        if not isinstance(username, str) or not isinstance(password, str):
            return False
        account = self._accounts.get(username)
        if account is None:
            return False
        return hmac.compare_digest(
            account.password.encode("utf-8"),
            password.encode("utf-8"),
        )

    def register_token(self, username: str, token: str) -> None:
        if username not in self._accounts:
            raise ValueError("Cannot register a token for an unknown vault account.")
        with self._lock:
            self._token_accounts[_token_digest(token)] = username

    def account_for_token(self, token: str) -> VaultAccount | None:
        with self._lock:
            username = self._token_accounts.get(_token_digest(token))
        return self._accounts.get(username) if username is not None else None

    def is_trusted_token(self, token: str) -> bool:
        return self.account_for_token(token) is not None
