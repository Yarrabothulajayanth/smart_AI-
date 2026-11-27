import os
from pathlib import Path
import secrets
import threading

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_config_lock = threading.Lock()


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def _persist_session_secret(path: Path, secret: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        if line.strip().startswith("SMARTBILL_SESSION_SECRET="):
            lines[index] = f"SMARTBILL_SESSION_SECRET={secret}"
            break
    else:
        lines.append(f"SMARTBILL_SESSION_SECRET={secret}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name == "posix":
        os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)


def load_backend_environment(path: Path = ENV_FILE) -> None:
    with _config_lock:
        values = _read_env_file(path)
        for name, value in values.items():
            os.environ.setdefault(name, value)

        secret = os.environ.get("SMARTBILL_SESSION_SECRET", "").strip()
        if not secret:
            secret = secrets.token_urlsafe(48)
            os.environ["SMARTBILL_SESSION_SECRET"] = secret

        if values.get("SMARTBILL_SESSION_SECRET") != secret:
            _persist_session_secret(path, secret)


load_backend_environment()
