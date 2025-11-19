import json
from urllib.parse import urlparse, urlunparse

import pytest
import requests
import yaml


def _tags_endpoint(generate_url: str) -> str:
    parts = urlparse(generate_url)
    # Replace path with /api/tags regardless of existing path
    return urlunparse((parts.scheme, parts.netloc, "/api/tags", "", "", ""))


def test_ollama_running_and_generate_small():
    cfg = yaml.safe_load(open("config.yaml"))
    oll = cfg.get("ollama", {})
    endpoint = oll.get("endpoint", "http://localhost:11434/api/generate")
    
    # Test summarization model
    summarization_cfg = oll.get("summarization", {})
    model = summarization_cfg.get("model", "deepseek-r1:7b-qwen-distill-q4_K_M")

    # Ping tags endpoint to check server availability
    try:
        r = requests.get(_tags_endpoint(endpoint), timeout=1.5)
    except Exception as e:
        pytest.skip(f"Ollama not reachable: {e}")
        return

    if r.status_code != 200:
        pytest.skip(f"Ollama responded non-200 to /api/tags: {r.status_code}")

    data = r.json()
    # Handle both {models:[...]} and [...] shapes; skip on unexpected
    if isinstance(data, dict) and "models" in data:
        listing = data.get("models") or []
    elif isinstance(data, list):
        listing = data
    else:
        pytest.skip(f"Unexpected /api/tags payload shape: {type(data).__name__}")
        return
    try:
        models = {m.get("name") for m in listing if isinstance(m, dict)}
    except Exception:
        pytest.skip("Unable to parse models from /api/tags response")
        return
    if model not in models:
        pytest.skip(f"Model {model} not present on Ollama. Run: ollama pull {model}")

    # Small non-streaming generate request
    try:
        gr = requests.post(
            endpoint,
            json={"model": model, "prompt": "Return JSON {\"ok\": true}", "stream": False},
            timeout=30,
        )
        gr.raise_for_status()
    except Exception as e:
        pytest.fail(f"Ollama generate request failed: {e}")

    resp = gr.json()
    assert "response" in resp, "Missing 'response' field in Ollama reply"
    # Best-effort: response should contain ok true JSON or at least some text
    assert isinstance(resp["response"], str) and len(resp["response"]) > 0


