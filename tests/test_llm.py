import json

import questlog as ql


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_summarize_uses_llm(monkeypatch):
    cfg = {
        "ollama": {
            "enabled": True, 
            "endpoint": "http://localhost:11434/api/generate",
            "summarization": {"model": "qwen2.5:7b-instruct"}
        },
        "projects": ["Demo"],
        "max_ocr_lines": 5,
    }
    app = "Cursor"
    window_title = "Editing foo.py — repo"
    ocr_top = ["def main():", "pass"]
    project_guess = ("Demo", 0.9)
    clues = {"urls": [], "domains": [], "repo_tokens": ["repo"]}

    llm_json = {
        "response": json.dumps({
            "summary": "Working on foo.py",
            "coarse_task": "Coding",
            "confidence": 0.9,
        })
    }

    def _fake_post(url, json=None, timeout=10):
        return _Resp(llm_json)

    monkeypatch.setattr(ql.requests, "post", _fake_post)

    summary, coarse_task, confidence = ql.summarize(cfg, app, window_title, ocr_top, project_guess, clues)
    assert summary == "Working on foo.py"
    assert coarse_task == "Coding"
    assert abs(confidence - 0.9) < 1e-6


