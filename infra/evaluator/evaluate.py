from __future__ import annotations

import functools
import http.server
import io
import json
import math
import re
import threading
from pathlib import Path

from PIL import Image, ImageStat  # type: ignore[import-not-found]
from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

SUBMISSION = Path("/submission")
OUTPUT = Path("/output")


def check(name: str, passed: bool, detail: object = None) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def valid_state(state: object) -> bool:
    if not isinstance(state, dict):
        return False
    player = state.get("player")
    return bool(
        state.get("phase") in {"ready", "playing", "paused", "won", "lost"}
        and isinstance(state.get("score"), (int, float))
        and isinstance(player, dict)
        and all(isinstance(player.get(axis), (int, float)) and math.isfinite(player[axis]) for axis in "xyz")
        and isinstance(state.get("relaysRestored"), int)
        and 0 <= state["relaysRestored"] <= 3
        and isinstance(state.get("charge"), (int, float))
        and math.isfinite(state["charge"])
        and state.get("seed") == 94721
        and isinstance(state.get("restartCount"), int)
        and state["restartCount"] >= 0
    )


def main() -> int:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=SUBMISSION)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    checks: list[dict] = [check("build", True)]
    browser_errors: list[str] = []
    external_requests: list[str] = []
    viewports = [(1440, 900, "desktop"), (390, 844, "phone")]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--use-gl=angle",
                    "--use-angle=swiftshader",
                    "--enable-unsafe-swiftshader",
                ],
            )
            for width, height, label in viewports:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: browser_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.on(
                    "request",
                    lambda request: external_requests.append(request.url)
                    if not request.url.startswith(url)
                    else None,
                )
                page.goto(url, wait_until="networkidle", timeout=30_000)
                page.wait_for_selector("canvas", timeout=15_000)
                state_before = page.evaluate("() => window.__AETHERPLAY__ ?? null")
                checks.append(check(f"{label}.runtime-contract", valid_state(state_before), state_before))
                overflow = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
                checks.append(check(f"{label}.no-horizontal-overflow", overflow <= 2, overflow))
                page.screenshot(path=str(OUTPUT / f"{label}.png"), full_page=False)
                canvas_shot = page.locator("canvas").first.screenshot()
                image = Image.open(io.BytesIO(canvas_shot)).convert("RGB").resize((64, 64))
                variance = sum(ImageStat.Stat(image).var)
                checks.append(check(f"{label}.nonblank", variance > 30, round(variance, 2)))

                buttons = page.get_by_role(
                    "button",
                    name=re.compile(r"start|play|begin|launch|enter|restore", re.IGNORECASE),
                )
                if buttons.count():
                    buttons.first.click()
                else:
                    page.keyboard.press("Space")
                page.wait_for_timeout(500)
                state_started = page.evaluate("() => window.__AETHERPLAY__ ?? null")
                checks.append(
                    check(
                        f"{label}.starts",
                        isinstance(state_started, dict)
                        and state_started.get("phase") in {"playing", "won", "lost"},
                        state_started,
                    )
                )
                page.keyboard.down("ArrowLeft")
                page.keyboard.down("KeyW")
                page.wait_for_timeout(700)
                page.keyboard.up("KeyW")
                page.keyboard.up("ArrowLeft")
                state_after = page.evaluate("() => window.__AETHERPLAY__ ?? null")
                moved = state_after != state_started and valid_state(state_after)
                checks.append(check(f"{label}.updates-during-input", moved, state_after))
                context.close()
            browser.close()
    except Exception as error:  # noqa: BLE001 - report evaluator failures as evidence
        checks.append(check("evaluator-completed", False, repr(error)))
    finally:
        server.shutdown()

    checks.append(check("no-page-errors", not browser_errors, browser_errors))
    checks.append(check("no-runtime-network", not external_requests, external_requests))
    report = {
        "schema_version": 1,
        "trusted": True,
        "passed": all(item["passed"] for item in checks),
        "build": {"passed": True, "exit_code": 0},
        "checks": checks,
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
