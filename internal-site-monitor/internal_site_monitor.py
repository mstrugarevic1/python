#!/usr/bin/env python3
"""Check configured websites, record metrics, and send state-change alerts."""

from __future__ import annotations

import argparse
import html
import json
import os
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
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.json"
STATUS_ICONS = {"UP": "🟢", "SLOW": "🐇", "DOWN": "🔴"}


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
    cards = []
    for index, item in enumerate(results):
        result = item["result"]
        cards.append(f"""<section class="site {result['status'].lower()}">
<h2>{html.escape(item['name'])} <span class="status">{STATUS_ICONS[result['status']]} {result['status']}</span></h2>
<p><a href="{html.escape(item['url'])}">{html.escape(item['url'])}</a></p>
<p>HTTP {result['status_code'] or '—'} · {result['response_ms']} ms · {html.escape(result['checked_at'])}</p>
<div class="chart"><canvas id="chart-{index}"></canvas></div></section>""")
    chart_data = json.dumps([history[item["name"]] for item in results]).replace("</", "<\\/")
    page = """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<title>Internal Site Monitor</title><style>
body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 16px;background:#f4f6f8;color:#18212f}
section{background:white;padding:16px;margin:16px 0;border-left:6px solid #16a34a;border-radius:6px}section.slow{border-color:#f59e0b}section.down{border-color:#dc2626}
h2{display:flex;justify-content:space-between}.status{font-size:14px}.chart{height:220px}a{color:#2563eb}.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center}input,select{font:inherit;padding:6px 8px;border:1px solid #94a3b8;border-radius:4px}</style>
<h1>Internal Site Monitor</h1>
<div class="controls"><label>Search <input id="search" type="search" placeholder="Name or URL"></label>
<label>Show metrics for <select id="range"><option value="300000">5 minutes</option><option value="900000">15 minutes</option><option value="1800000">30 minutes</option><option value="3600000">1 hour</option><option value="21600000">6 hours</option><option value="43200000">12 hours</option><option value="86400000">1 day</option><option value="259200000">3 days</option><option value="604800000">7 days</option><option value="0">All retained data</option></select></label></div>""" + "".join(cards) + f"""
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const history = {chart_data};
const charts = [];
for (const [index, samples] of history.entries()) {{
  const canvas = document.getElementById(`chart-${{index}}`);
  if (!canvas) continue;
  charts.push(new Chart(canvas, {{
    type: 'line',
    data: {{
      labels: [],
      datasets: [{{label: 'Response time (ms)', data: [], borderColor: '#334155',
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0}}]
    }},
    options: {{responsive: true, maintainAspectRatio: false, scales: {{
      x: {{grid: {{color: '#e2e8f0'}}, ticks: {{maxTicksLimit: 8}}}},
      y: {{beginAtZero: true, grid: {{color: '#e2e8f0'}}, title: {{display: true, text: 'ms'}}}}
    }}}}
  }}));
}}
document.getElementById('range').addEventListener('change', event => {{
  const cutoff = Number(event.target.value) ? Date.now() - Number(event.target.value) : 0;
  history.forEach((samples, index) => {{
    const visible = samples.filter(sample => new Date(sample.checked_at).getTime() >= cutoff);
    charts[index].data.labels = visible.map(sample => new Date(sample.checked_at).toLocaleTimeString());
    charts[index].data.datasets[0].data = visible.map(sample => sample.response_ms);
    charts[index].update();
  }});
}});
document.getElementById('range').dispatchEvent(new Event('change'));
document.getElementById('search').addEventListener('input', event => {{
  const query = event.target.value.toLowerCase();
  document.querySelectorAll('.site').forEach(site => site.hidden = !site.textContent.toLowerCase().includes(query));
}});
</script>"""
    (WEB_DIR / "index.html").write_text(page, encoding="utf-8")


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
