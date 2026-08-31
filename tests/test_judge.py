import functools
import http.server
import json
import threading
import urllib.request
from pathlib import Path

from web3dgamebench.judge import QuietHandler

ROOT = Path(__file__).resolve().parents[1]


def test_signal_drift_rubric_matches_prompt() -> None:
    rubric = json.loads((ROOT / "infra/judge/rubrics/signal-drift.json").read_text())
    prompt = (ROOT / "infra/judge/prompts/signal-drift.md").read_text()
    assert sum(item["weight"] for item in rubric["criteria"]) == 100
    assert len({item["id"] for item in rubric["criteria"]}) == len(rubric["criteria"])
    for index, item in enumerate(rubric["criteria"], start=1):
        assert f'{index}. {item["id"]} ({item["weight"]})' in prompt


def test_judge_server_blocks_runtime_connections(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>test</title>")
    handler = functools.partial(QuietHandler, directory=tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/", timeout=2
        )
        policy = response.headers["Content-Security-Policy"]
        assert "connect-src 'none'" in policy
        assert "form-action 'none'" in policy
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()
