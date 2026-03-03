from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Walter Dashboard</title>
  <style>
    :root {
      --bg: #f8f9fb;
      --card: #ffffff;
      --line: #111111;
      --subtle: #d8dde6;
      --text: #111827;
      --muted: #4b5563;
      --buy: #0f766e;
      --sell: #b91c1c;
      --hold: #6b7280;
      --pos: #1d4ed8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    .wrap {
      max-width: 1400px;
      margin: 0 auto;
      padding: 18px 18px 24px;
    }
    .title {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 12px;
      gap: 16px;
    }
    .title h1 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.05em;
      font-weight: 700;
    }
    .status {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .grid {
      display: grid;
      grid-template-columns: 2.6fr 1.2fr;
      gap: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--subtle);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .chart-card { padding: 6px 10px 10px; }
    .chart-head {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--muted);
      margin: 4px 2px 6px;
    }
    .canvas-wrap { height: 270px; }
    canvas { width: 100%; height: 100%; display: block; }
    .stack { display: grid; gap: 10px; }
    .info-title {
      font-size: 12px;
      letter-spacing: 0.07em;
      color: var(--muted);
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .info-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 10px;
      font-size: 12px;
    }
    .label { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .thinking {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--subtle);
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .news {
      margin-top: 8px;
      border-top: 1px solid var(--subtle);
      padding-top: 8px;
      font-size: 12px;
      line-height: 1.4;
    }
    .events {
      margin: 0;
      padding-left: 16px;
      font-size: 12px;
      color: var(--muted);
      max-height: 185px;
      overflow: auto;
    }
    @media (max-width: 980px) {
      .grid { grid-template-columns: 1fr; }
      .canvas-wrap { height: 220px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <h1 id="title">WALTER LIVE DASHBOARD</h1>
      <div class="status" id="status">connecting...</div>
    </div>
    <div class="grid">
      <div class="stack">
        <div class="card chart-card">
          <div class="chart-head">
            <span>Price + Decisions</span>
            <span id="priceMeta">--</span>
          </div>
          <div class="canvas-wrap"><canvas id="priceChart"></canvas></div>
        </div>
        <div class="card chart-card">
          <div class="chart-head">
            <span>Account / Withdrawable / Position Value</span>
            <span id="valueMeta">--</span>
          </div>
          <div class="canvas-wrap"><canvas id="valueChart"></canvas></div>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <div class="info-title">Live Context</div>
          <div class="info-grid">
            <div class="label">Stage</div><div class="mono" id="stage">--</div>
            <div class="label">Order</div><div class="mono" id="order">--</div>
            <div class="label">Action</div><div class="mono" id="action">--</div>
            <div class="label">Price</div><div class="mono" id="price">--</div>
            <div class="label">Account</div><div class="mono" id="account">--</div>
            <div class="label">Avail</div><div class="mono" id="avail">--</div>
            <div class="label">Pos Value</div><div class="mono" id="pos">--</div>
            <div class="label">Req Margin</div><div class="mono" id="req">--</div>
          </div>
          <div class="thinking"><strong>Thinking</strong><br /><span id="thinking">--</span></div>
          <div class="news"><strong>Top News</strong><br /><span id="news">--</span></div>
        </div>
        <div class="card">
          <div class="info-title">Recent Events</div>
          <ul class="events" id="events"></ul>
        </div>
      </div>
    </div>
  </div>
  <script>
    const COLORS = {
      line: "#111111",
      grid: "#d8dde6",
      text: "#111827",
      muted: "#6b7280",
      buy: "#0f766e",
      sell: "#b91c1c",
      hold: "#6b7280",
      account: "#111827",
      withdrawable: "#6b7280",
      position: "#1d4ed8",
    };

    function fmtMoney(v) {
      if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2
      }).format(v);
    }

    function finiteValues(arr) {
      return (arr || []).filter(v => Number.isFinite(v));
    }

    function makeScale(min, max, outMin, outMax) {
      if (!Number.isFinite(min) || !Number.isFinite(max)) {
        return () => (outMin + outMax) / 2;
      }
      if (max <= min) {
        return () => (outMin + outMax) / 2;
      }
      return (v) => outMax - ((v - min) / (max - min)) * (outMax - outMin);
    }

    function drawChart(canvas, series, markers, options) {
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(200, Math.floor(rect.width));
      const h = Math.max(120, Math.floor(rect.height));
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, w, h);

      const pad = { l: 42, r: 10, t: 14, b: 22 };
      const innerW = w - pad.l - pad.r;
      const innerH = h - pad.t - pad.b;
      if (innerW <= 0 || innerH <= 0) return;

      const all = [];
      for (const s of series) {
        for (const v of s.values) if (Number.isFinite(v)) all.push(v);
      }
      if (!all.length) {
        ctx.fillStyle = COLORS.muted;
        ctx.font = "12px sans-serif";
        ctx.fillText("Waiting for data...", pad.l, pad.t + 18);
        return;
      }

      let min = Math.min(...all);
      let max = Math.max(...all);
      const spread = Math.max(1e-8, max - min);
      min -= spread * 0.08;
      max += spread * 0.08;

      const toY = makeScale(min, max, pad.t, h - pad.b);
      const n = Math.max(...series.map(s => s.values.length));
      const toX = (i) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * innerW);

      ctx.strokeStyle = COLORS.grid;
      ctx.lineWidth = 1;
      for (let i = 0; i < 5; i++) {
        const y = pad.t + (i / 4) * innerH;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
      }

      for (const s of series) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width || 1.7;
        ctx.beginPath();
        let started = false;
        s.values.forEach((v, i) => {
          if (!Number.isFinite(v)) return;
          const x = toX(i);
          const y = toY(v);
          if (!started) { ctx.moveTo(x, y); started = true; }
          else { ctx.lineTo(x, y); }
        });
        ctx.stroke();
      }

      if (markers && markers.length) {
        for (const m of markers) {
          if (!Number.isFinite(m.index) || !Number.isFinite(m.price)) continue;
          const x = toX(m.index);
          const y = toY(m.price);
          ctx.fillStyle =
            m.action === "buy" ? COLORS.buy : (m.action === "sell" ? COLORS.sell : COLORS.hold);
          ctx.beginPath();
          ctx.arc(x, y, 3.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.fillStyle = COLORS.muted;
      ctx.font = "11px sans-serif";
      ctx.fillText(fmtMoney(max), 2, pad.t + 10);
      ctx.fillText(fmtMoney(min), 2, h - pad.b);
      if (options && options.metaEl) {
        options.metaEl.textContent = `${fmtMoney(series[0].values.at(-1))} | range ${fmtMoney(min)} to ${fmtMoney(max)}`;
      }
    }

    function updateInfo(state) {
      const latest = state.latest || {};
      const market = latest.market || {};
      const account = latest.account || {};
      const decision = latest.decision || {};

      document.getElementById("title").textContent = `WALTER LIVE DASHBOARD | ${state.coin || "COIN"}`;
      document.getElementById("status").textContent = `updated ${state.updated_at || "--"} | points ${state.timestamps?.length || 0}`;
      document.getElementById("stage").textContent = latest.stage || "--";
      document.getElementById("order").textContent = latest.order_status || "--";
      document.getElementById("action").textContent = (decision.action || "--").toUpperCase();
      document.getElementById("price").textContent = fmtMoney(market.current_price);
      document.getElementById("account").textContent = fmtMoney(account.account_value);
      document.getElementById("avail").textContent = fmtMoney(account.withdrawable);
      document.getElementById("pos").textContent = fmtMoney(account.position_value);
      document.getElementById("req").textContent = fmtMoney(latest.required_margin);
      document.getElementById("thinking").textContent = decision.thinking || "--";

      const news = (latest.news_titles || []).slice(0, 3);
      document.getElementById("news").textContent = news.length ? news.join(" | ") : "--";

      const eventsEl = document.getElementById("events");
      eventsEl.innerHTML = "";
      (state.events || []).forEach((e) => {
        const li = document.createElement("li");
        li.textContent = e;
        eventsEl.appendChild(li);
      });
    }

    async function refresh() {
      try {
        const resp = await fetch("/api/state", { cache: "no-store" });
        const state = await resp.json();
        updateInfo(state);

        const markerIndex = new Map((state.timestamps || []).map((t, i) => [t, i]));
        const markers = (state.decision_markers || [])
          .map((m) => ({ index: markerIndex.get(m.timestamp), price: m.price, action: m.action }))
          .filter((m) => Number.isFinite(m.index));

        drawChart(
          document.getElementById("priceChart"),
          [{ values: state.prices || [], color: COLORS.line, width: 1.8 }],
          markers,
          { metaEl: document.getElementById("priceMeta") }
        );
        drawChart(
          document.getElementById("valueChart"),
          [
            { values: state.account_values || [], color: COLORS.account, width: 1.7 },
            { values: state.withdrawables || [], color: COLORS.withdrawable, width: 1.4 },
            { values: state.position_values || [], color: COLORS.position, width: 1.4 }
          ],
          [],
          { metaEl: document.getElementById("valueMeta") }
        );
      } catch (err) {
        document.getElementById("status").textContent = "dashboard connection error";
      }
    }

    refresh();
    setInterval(refresh, 750);
  </script>
</body>
</html>
"""


def _default_state() -> dict[str, Any]:
    return {
        "coin": "",
        "updated_at": "",
        "timestamps": [],
        "prices": [],
        "account_values": [],
        "withdrawables": [],
        "position_values": [],
        "decision_markers": [],
        "events": [],
        "latest": {
            "stage": "",
            "order_status": "",
            "required_margin": None,
            "market": {},
            "account": {},
            "decision": {},
            "news_titles": [],
        },
    }


class WebDashboardServer:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._state: dict[str, Any] = _default_state()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._server is not None:
            return

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _write_bytes(
                self, status: int, content_type: str, body: bytes, cache: str = "no-store"
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/" or path == "/index.html":
                    self._write_bytes(
                        200,
                        "text/html; charset=utf-8",
                        _HTML.encode("utf-8"),
                        cache="no-cache",
                    )
                    return

                if path == "/api/state":
                    with outer._lock:
                        payload = json.dumps(outer._state).encode("utf-8")
                    self._write_bytes(
                        200,
                        "application/json; charset=utf-8",
                        payload,
                    )
                    return

                if path == "/healthz":
                    self._write_bytes(200, "text/plain; charset=utf-8", b"ok")
                    return

                self._write_bytes(
                    404, "application/json; charset=utf-8", b'{"error":"not found"}'
                )

            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug("web_dashboard: " + fmt, *args)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="walter-web-dashboard", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            self._thread = None

    def update(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._state = payload

