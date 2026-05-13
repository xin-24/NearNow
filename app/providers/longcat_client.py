
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LongCatAPIError(RuntimeError):
    """Raised when the LongCat API cannot return a usable response."""


@dataclass(frozen=True)
class LongCatConfig:
    api_key: str | None
    base_url: str = "https://api.longcat.chat"
    model: str = "LongCat-Flash-Chat"
    timeout_seconds: float = 20.0


class LongCatClient:
    """Small OpenAI-compatible LongCat client using the Python stdlib."""

    def __init__(self, config: LongCatConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> LongCatClient:
        load_env_files()
        timeout = os.getenv("LONGCAT_TIMEOUT_SECONDS", "20")
        try:
            timeout_seconds = float(timeout)
        except ValueError:
            timeout_seconds = 20.0
        return cls(
            LongCatConfig(
                api_key=os.getenv("LONGCAT_API_KEY"),
                base_url=os.getenv("LONGCAT_BASE_URL", "https://api.longcat.chat"),
                model=os.getenv("LONGCAT_MODEL", "LongCat-Flash-Chat"),
                timeout_seconds=timeout_seconds,
            )
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.config.api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        if not self.config.api_key:
            raise LongCatAPIError("LONGCAT_API_KEY is not configured")

        body = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        request = Request(
            f"{self.config.base_url.rstrip('/')}/openai/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise LongCatAPIError("LongCat chat completion request failed") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LongCatAPIError("LongCat response did not contain assistant content") from exc

        if not isinstance(content, str) or not content.strip():
            raise LongCatAPIError("LongCat response content was empty")
        return content.strip()


def load_env_files() -> None:
    """Load local env files without overriding already exported variables."""
    root = Path(__file__).resolve().parents[2]
    for path in (root / ".env", root / ".env.local"):
        if path.exists():
            load_env_file(path)


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
