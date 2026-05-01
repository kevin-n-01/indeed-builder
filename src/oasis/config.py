from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

OASIS_DIR = Path.home() / ".oasis"
CONFIG_PATH = OASIS_DIR / "config.json"
_FALLBACK_KEY_PATH = OASIS_DIR / ".api_key"
KEYRING_SERVICE = "oasis"
KEYRING_API_KEY = "anthropic_api_key"


class OasisConfig(BaseModel):
    search_terms: list[str] = []
    locations: list[str] = []
    job_type: Literal["fulltime", "parttime", "contract", "any"] = "fulltime"
    remote: bool = False
    resume_path: str = ""
    cover_letter_path: str = ""
    results_wanted: int = 50


def load_config() -> OasisConfig:
    OASIS_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return OasisConfig.model_validate_json(CONFIG_PATH.read_text())
    return OasisConfig()


def save_config(config: OasisConfig) -> None:
    OASIS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2))


def get_api_key() -> str | None:
    # Try system keyring first (macOS Keychain, etc.)
    try:
        import keyring
        import keyring.errors
        val = keyring.get_password(KEYRING_SERVICE, KEYRING_API_KEY)
        if val:
            return val
    except Exception:
        pass
    # Fallback: plaintext file (Linux/WSL where no keyring daemon is available)
    if _FALLBACK_KEY_PATH.exists():
        return _FALLBACK_KEY_PATH.read_text().strip() or None
    return None


def set_api_key(key: str) -> None:
    # Try system keyring first
    try:
        import keyring
        import keyring.errors
        keyring.set_password(KEYRING_SERVICE, KEYRING_API_KEY, key)
        return
    except Exception:
        pass
    # Fallback: store in ~/.oasis/.api_key with restricted permissions
    OASIS_DIR.mkdir(parents=True, exist_ok=True)
    _FALLBACK_KEY_PATH.write_text(key)
    _FALLBACK_KEY_PATH.chmod(0o600)


def output_dir() -> Path:
    d = Path.home() / "oasis-output"
    d.mkdir(parents=True, exist_ok=True)
    return d
