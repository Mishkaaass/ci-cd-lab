"""Real browser checks. CI opts in explicitly; a missing browser must then fail."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.security_support import OPERATOR_TOKEN, VIEWER_TOKEN

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_SECURITY") != "1",
    reason="Set RUN_BROWSER_SECURITY=1 with Chromium installed",
)
XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def browser_app(tmp_path, security_environment):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "browser.db"),
        "OPSBOARD_ENABLE_DEPLOYMENTS": "false",
        "OPSBOARD_RATE_LIMIT": "10000",
        "DEMO_SERVICE_URL": f"http://127.0.0.1:{port}",
    }
    log = (tmp_path / "server.log").open("w+")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-server-header",
            "--no-proxy-headers",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=log,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            for _ in range(100):
                try:
                    if client.get(url + "/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                log.seek(0)
                pytest.fail(log.read())
            result = client.post(
                url + "/api/incidents",
                headers={"Authorization": "Bearer " + OPERATOR_TOKEN},
                json={
                    "service": "browser-marker",
                    "severity": "warning",
                    "reason": XSS,
                },
            )
            assert result.status_code == 201, result.text
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
        browser = playwright.chromium.launch(**options)
        context = browser.new_context()
        yield context.new_page()
        context.close()
        browser.close()


def unlock(page):
    page.locator("#access-token").fill(VIEWER_TOKEN)
    page.locator("#auth-form button[type=submit]").click()


def test_stored_xss_is_text_and_token_is_not_persisted(page, browser_app):
    from playwright.sync_api import expect

    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(browser_app + "/dashboard")
    expect(page.locator("#incident-rows")).not_to_contain_text("browser-marker")
    unlock(page)
    expect(page.locator("#incident-rows")).to_contain_text(XSS)
    assert page.locator("#incident-rows img, #incident-rows script").count() == 0
    assert page.evaluate("() => window.__xss || 0") == 0
    assert page.evaluate("() => localStorage.length + sessionStorage.length") == 0
    assert page.context.cookies() == []
    assert page.locator("#access-token").input_value() == ""
    assert page.locator("#rollback-button").is_disabled()
    page.locator("#lock-button").click()
    expect(page.locator("#incident-rows")).not_to_contain_text("browser-marker")
    page.reload()
    expect(page.locator("#incident-rows")).not_to_contain_text("browser-marker")
    assert errors == []


def test_lock_prevents_late_json_from_repopulating_private_dom(page, browser_app):
    from playwright.sync_api import expect

    page.goto(browser_app + "/dashboard")
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (args[0] === '/api/dashboard') {
          const json = response.json.bind(response);
          response.json = async () => {
            window.__jsonPending = true;
            await new Promise(resolve => {window.__releaseJSON = resolve;});
            return json();
          };
        }
        return response;
      };
    }""")
    unlock(page)
    page.wait_for_function("() => window.__jsonPending === true")
    page.locator("#lock-button").click()
    page.evaluate("() => window.__releaseJSON()")
    page.wait_for_timeout(150)
    expect(page.locator("#incident-rows")).not_to_contain_text("browser-marker")


def test_expiry_clears_data_even_when_api_becomes_unavailable(page, browser_app):
    from playwright.sync_api import expect

    def short_expiry(route):
        response = route.fetch()
        payload = response.json()
        payload["expires_at"] = int(time.time()) + 3
        route.fulfill(response=response, json=payload)

    page.route("**/api/auth/me", short_expiry)
    page.goto(browser_app + "/dashboard")
    unlock(page)
    expect(page.locator("#incident-rows")).to_contain_text("browser-marker")
    page.route("**/api/**", lambda route: route.abort())
    expect(page.locator("#incident-rows")).not_to_contain_text(
        "browser-marker", timeout=7000
    )
    expect(page.locator("#auth-status")).to_contain_text("expired")
