#!/usr/bin/env python3
"""Check configured websites, record metrics, and send state-change alerts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
FRONTEND_DIR = ROOT / "frontend"
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.json"
def load_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def check_site(site: dict) -> dict:
    started = time.perf_counter()
    status_code = None
    error = None
    try:
        request = Request(site["url"], headers={"User-Agent": "internal-site-monitor/1.0"})
        with urlopen(request, timeout=site.get("timeout_seconds", 5)) as response:
            status_code = response.status
    except HTTPError as exc:
        status_code, error = exc.code, str(exc)
    except (URLError, TimeoutError, OSError) as exc:
        error = str(exc)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    healthy = status_code == site.get("expected_status", 200)
    status = "SLOW" if healthy and elapsed_ms > site.get("slow_after_ms", 1000) else "UP" if healthy else "DOWN"
    return {"status": status, "status_code": status_code, "response_ms": elapsed_ms, "error": error,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def add_history(history: dict, site_name: str, result: dict, limit: int) -> None:
    samples = history.setdefault(site_name, [])
    samples.append({
        "checked_at": result["checked_at"],
        "response_ms": result["response_ms"] if result["status"] != "DOWN" else None,
    })
    history[site_name] = samples[-limit:]


def slack_alert(webhook: str, message: str) -> None:
    body = json.dumps({"text": message}).encode()
    request = Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10):
        pass


def email_alert(settings: dict, subject: str, body: str) -> None:
    host = os.environ[settings["host_env"]]
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, settings["from"], ", ".join(settings["to"])
    message.set_content(body)
    with smtplib.SMTP(host, settings.get("port", 587), timeout=10) as smtp:
        if settings.get("starttls", True):
            smtp.starttls()
        username = os.getenv(settings.get("username_env", ""))
        password = os.getenv(settings.get("password_env", ""))
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def notify(config: dict, subject: str, body: str) -> bool:
    settings = config.get("notifications", {})
    webhook = os.getenv(settings.get("slack_webhook_env", ""))
    attempted = delivered = False
    if webhook:
        attempted = True
        try:
            slack_alert(webhook, f"*{subject}*\n{body}")
            delivered = True
        except Exception as exc:
            print(f"Slack notification failed: {exc}")
    email = settings.get("email", {})
    if email.get("enabled"):
        attempted = True
        try:
            email_alert(email, subject, body)
            delivered = True
        except Exception as exc:
            print(f"Email notification failed: {exc}")
    return delivered or not attempted


def write_dashboard(results: list[dict], history: dict) -> None:
    WEB_DIR.mkdir(exist_ok=True)
    dashboard_data = [item | {"history": history[item["name"]]} for item in results]
    data = json.dumps(dashboard_data).replace("</", "<\\/")
    template = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    page = template.replace("__DASHBOARD_DATA__", data)
    (WEB_DIR / "index.html").write_text(page, encoding="utf-8")
    for asset in ("styles.css", "dashboard.js"):
        shutil.copyfile(FRONTEND_DIR / asset, WEB_DIR / asset)


def run_checks(config_path: Path) -> None:
    config = load_json(config_path, None)
    if not isinstance(config, dict):
        raise SystemExit(f"Cannot read configuration: {config_path}")
    interval_seconds = config.get("check_interval_seconds", 60)
    retention_days = config.get("history_retention_days", 7)
    if not all(type(value) is int and value > 0 for value in (interval_seconds, retention_days)):
        raise SystemExit("check_interval_seconds and history_retention_days must be positive integers")
    history_limit = retention_days * 86400 // interval_seconds
    sites = config.get("sites", [])
    names = [site["name"] for site in sites]
    if len(names) != len(set(names)):
        raise SystemExit("Site names must be unique")
    DATA_DIR.mkdir(exist_ok=True)
    state = load_json(STATE_FILE, {})
    history = load_json(HISTORY_FILE, {})
    results = []

    for site in sites:
        result = check_site(site)
        previous = state.get(site["name"], {})
        failures = 0 if result["status"] != "DOWN" else previous.get("failures", 0) + 1
        threshold = site.get("failure_threshold", config.get("failure_threshold", 3))
        was_down = previous.get("alerted_down", False)
        alerted_down = was_down
        if failures >= threshold and not was_down:
            alerted_down = notify(config, f"[DOWN] {site['name']}", f"{site['url']}\n{result['error'] or 'Unexpected HTTP status'}\nFailed checks: {failures}")
        elif failures == 0 and was_down:
            if notify(config, f"[RECOVERED] {site['name']}", f"{site['url']}\nResponse time: {result['response_ms']} ms"):
                alerted_down = False
        state[site["name"]] = {**result, "failures": failures, "alerted_down": alerted_down}
        results.append({"name": site["name"], "url": site["url"], "result": result})
        add_history(history, site["name"], result, history_limit)
        print(f"{site['name']}: {result['status']} ({result['response_ms']} ms)")

    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    HISTORY_FILE.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    write_dashboard(results, history)


def check_repeatedly(config_path: Path, interval_seconds: int) -> None:
    while True:
        try:
            run_checks(config_path)
        except Exception as exc:
            print(f"Check failed: {exc}")
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "serve"])
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "check":
        run_checks(args.config)
    else:
        config = load_json(args.config, None)
        if not isinstance(config, dict):
            raise SystemExit(f"Cannot read configuration: {args.config}")
        interval_seconds = config.get("check_interval_seconds", 60)
        if not isinstance(interval_seconds, int) or interval_seconds < 1:
            raise SystemExit("check_interval_seconds must be a positive integer")
        WEB_DIR.mkdir(exist_ok=True)
        threading.Thread(target=check_repeatedly, args=(args.config, interval_seconds), daemon=True).start()
        os.chdir(WEB_DIR)
        print(f"Dashboard: http://127.0.0.1:{args.port} (checking every {interval_seconds}s)")
        ThreadingHTTPServer(("127.0.0.1", args.port), SimpleHTTPRequestHandler).serve_forever()


if __name__ == "__main__":
    main()
