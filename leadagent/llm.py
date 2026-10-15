"""Pluggable OpenAI-compatible LLM. Enabled only when base URL and model are set."""
from __future__ import annotations
import json
import re
import httpx
from . import config


class LLMError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_MODEL)


def chat(system: str, user: str, client: httpx.Client | None = None) -> str:
    body = {"model": config.LLM_MODEL, "temperature": 0.3,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    try:
        r = (client or httpx.Client(timeout=60)).post(config.LLM_BASE_URL.rstrip("/") + "/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise LLMError(str(e)) from e


def chat_json(system: str, user: str, client=None) -> dict:
    txt = chat(system, user, client)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError as e:
        raise LLMError(f"model did not return JSON: {e}") from e
