"""Thin client for any OpenAI-compatible chat endpoint (Groq, OpenAI, Gemini-compat, Ollama)."""
import json, re
import requests
from . import config


class LLMError(Exception):
    pass


def configured() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_MODEL and config.LLM_API_KEY)


def chat_json(system: str, user: str, timeout: int = 60) -> dict:
    if not configured():
        raise LLMError("LLM not configured")
    payload = {
        "model": config.LLM_MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", json=payload, timeout=timeout,
                          headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        if r.status_code == 400 and "response_format" in r.text:  # provider without JSON mode
            payload.pop("response_format")
            r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", json=payload, timeout=timeout,
                              headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        raise LLMError(f"LLM request failed: {e}") from e
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
    try:
        return json.loads(content)
    except ValueError as e:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
        raise LLMError("LLM returned invalid JSON") from e
