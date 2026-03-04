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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f3f4f5;
      --bg-accent: #ebedef;
      --card: #ffffff;
      --line: #101114;
      --subtle: #d5d9de;
      --text: #111318;
      --muted: #5b616c;
      --buy: #106949;
      --sell: #b11f1f;
      --hold: #6b7280;
      --account: #101114;
      --focus: #1f4cb0;
      --radius: 9px;
      --shadow: 0 8px 30px rgba(12, 20, 38, 0.05);
      --soft-panel: #f7f9fb;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      line-height: 1.4;
      color: var(--text);
      background:
        radial-gradient(1200px 380px at 100% -80px, var(--bg-accent), transparent 70%),
        radial-gradient(1000px 380px at -80px 100%, #eceff2, transparent 65%),
        var(--bg);
    }

    .wrap {
      max-width: 1460px;
      margin: 0 auto;
      padding: 20px 20px 24px;
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
      font-size: 19px;
      letter-spacing: 0.13em;
      font-weight: 600;
      text-transform: uppercase;
    }

    .status {
      color: var(--muted);
      font-size: 12px;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      white-space: nowrap;
      padding: 3px 8px;
      border: 1px solid #d9dde3;
      border-radius: 999px;
      background: #fafbfc;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 2.7fr) minmax(360px, 1.3fr);
      gap: 12px;
      align-items: start;
    }

    .stack {
      display: grid;
      gap: 12px;
    }

    .card {
      background: var(--card);
      border: 1px solid var(--subtle);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 11px 13px;
    }

    .chart-card {
      padding: 10px 12px 12px;
    }

    .chart-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      font-size: 11px;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin: 1px 2px 8px;
      text-transform: uppercase;
      font-weight: 500;
    }

    .chart-head span:last-child {
      letter-spacing: 0;
      text-transform: none;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
    }

    .canvas-wrap {
      height: 280px;
      border: 1px solid #eceff3;
      border-radius: 8px;
      background: linear-gradient(180deg, #ffffff 0%, #fbfcfd 100%);
      overflow: hidden;
    }

    .legend {
      display: flex;
      gap: 12px;
      margin: 0 2px 8px;
      color: var(--muted);
      font-size: 11px;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    .legend-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      display: inline-block;
    }

    .legend-dot.buy { background: var(--buy); }
    .legend-dot.sell { background: var(--sell); }
    .legend-dot.hold { background: var(--hold); }

    canvas {
      width: 100%;
      height: 100%;
      display: block;
    }

    .info-title {
      font-size: 12px;
      letter-spacing: 0.11em;
      color: var(--muted);
      margin-bottom: 10px;
      text-transform: uppercase;
      font-weight: 600;
    }

    .hint {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 10px;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    .info-grid {
      display: grid;
      grid-template-columns: 102px minmax(0, 1fr);
      gap: 8px 12px;
      font-size: 13px;
    }

    .label {
      color: var(--muted);
      letter-spacing: 0.01em;
    }

    .mono {
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: #14181f;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #stage,
    #order,
    #detailTime,
    #detailSizeLev {
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .thinking,
    .news {
      margin-top: 10px;
      padding: 8px 9px 0;
      border-top: 1px solid var(--subtle);
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      color: #14181f;
      background: linear-gradient(180deg, var(--soft-panel), rgba(247, 249, 251, 0));
      border-radius: 4px;
    }

    .decision-grid {
      display: grid;
      grid-template-columns: 102px minmax(0, 1fr);
      gap: 8px 12px;
      font-size: 13px;
      margin-bottom: 10px;
    }

    .pre-block {
      border-top: 1px solid var(--subtle);
      padding-top: 10px;
      margin-top: 10px;
    }

    .pre-title {
      font-size: 11px;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 4px;
    }

    .pre-content {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      font-size: 12px;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      color: #161d27;
      max-height: 190px;
      overflow: auto;
      padding: 8px 10px;
      background: var(--soft-panel);
      border: 1px solid #e7ecf1;
      border-radius: 6px;
    }

    .events {
      margin: 0;
      padding: 0;
      list-style: none;
      font-size: 12px;
      color: #28303b;
      max-height: 200px;
      overflow: auto;
      line-height: 1.5;
    }

    .event-item {
      border-bottom: 1px solid #edf1f4;
      padding: 6px 0;
      font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11.5px;
    }

    .event-item:last-child {
      border-bottom: none;
    }

    @media (max-width: 1080px) {
      .grid { grid-template-columns: 1fr; }
      .canvas-wrap { height: 236px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      <h1 id="title">Walter Live Dashboard</h1>
      <div class="status" id="status">connecting...</div>
    </div>
    <div class="grid">
      <div class="stack">
        <div class="card chart-card">
          <div class="chart-head">
            <span>Price + Decision Points</span>
            <span id="priceMeta">--</span>
          </div>
          <div class="legend">
            <span class="legend-item"><span class="legend-dot buy"></span>buy</span>
            <span class="legend-item"><span class="legend-dot sell"></span>sell</span>
            <span class="legend-item"><span class="legend-dot hold"></span>hold</span>
          </div>
          <div class="canvas-wrap"><canvas id="priceChart"></canvas></div>
        </div>
        <div class="card chart-card">
          <div class="chart-head">
            <span>Account Value (Shared X-Axis)</span>
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
          <div class="thinking"><strong>Latest Thinking</strong><br /><span id="thinking">--</span></div>
          <div class="news"><strong>Top News</strong><br /><span id="news">--</span></div>
        </div>
        <div class="card">
          <div class="info-title">Decision Point Details</div>
          <div class="hint">Click a decision marker on the top chart.</div>
          <div class="decision-grid">
            <div class="label">Time</div><div class="mono" id="detailTime">--</div>
            <div class="label">Action</div><div class="mono" id="detailAction">--</div>
            <div class="label">Price</div><div class="mono" id="detailPrice">--</div>
            <div class="label">Size / Lev</div><div class="mono" id="detailSizeLev">--</div>
          </div>
          <div class="pre-block">
            <div class="pre-title">LLM Input</div>
            <pre class="pre-content" id="detailInput">--</pre>
          </div>
          <div class="pre-block">
            <div class="pre-title">Thinking</div>
            <pre class="pre-content" id="detailThinking">--</pre>
          </div>
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
      line: "#101114",
      grid: "#d9dde3",
      axis: "#8a92a0",
      muted: "#68717f",
      buy: "#106949",
      sell: "#b11f1f",
      hold: "#6b7280",
      account: "#101114",
      highlight: "#1f4cb0",
    };

    const viewState = {
      selectedMarkerKey: null,
      markerHitboxes: [],
      latestApiState: null,
      interactionsBound: false,
    };

    function fmtMoney(v) {
      if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(v);
    }

    function fmtAxisMoney(v) {
      if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 1,
        notation: "compact",
      }).format(v);
    }

    function fmtNum(v, digits = 3) {
      if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
      return Number(v).toFixed(digits);
    }

    function fmtClock(ts, withDate = false) {
      if (!ts) return "--";
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return "--";
      if (withDate) {
        return d.toLocaleString("en-US", {
          month: "short",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
      }
      return d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    }

    function makeScale(min, max, outMin, outMax) {
      if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
        return () => (outMin + outMax) / 2;
      }
      return (v) => outMax - ((v - min) / (max - min)) * (outMax - outMin);
    }

    function finiteValues(arr) {
      return (arr || []).filter((v) => Number.isFinite(v));
    }

    function computeDomain(values) {
      if (!values.length) {
        return { min: 0, max: 1 };
      }
      let min = Math.min(...values);
      let max = Math.max(...values);
      const spread = max - min;
      if (spread < 1e-9) {
        const pad = Math.max(Math.abs(max) * 0.008, 1);
        min -= pad;
        max += pad;
        return { min, max };
      }
      const pad = spread * 0.08;
      return { min: min - pad, max: max + pad };
    }

    function buildTicks(min, max, count = 5) {
      const ticks = [];
      for (let i = 0; i < count; i += 1) {
        ticks.push(min + (i / (count - 1)) * (max - min));
      }
      return ticks;
    }

    function lastFinite(values) {
      for (let i = values.length - 1; i >= 0; i -= 1) {
        if (Number.isFinite(values[i])) return values[i];
      }
      return null;
    }

    function markerKey(marker) {
      return `${marker.timestamp}|${marker.action}|${marker.index}`;
    }

    function traceDecisionMarker(ctx, action, x, y, r) {
      const act = (action || "").toLowerCase();
      ctx.beginPath();
      if (act === "buy") {
        ctx.moveTo(x, y - r);
        ctx.lineTo(x + r * 0.92, y + r * 0.85);
        ctx.lineTo(x - r * 0.92, y + r * 0.85);
        ctx.closePath();
        return;
      }
      if (act === "sell") {
        ctx.moveTo(x, y + r);
        ctx.lineTo(x + r * 0.92, y - r * 0.85);
        ctx.lineTo(x - r * 0.92, y - r * 0.85);
        ctx.closePath();
        return;
      }
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }

    function drawChart(canvas, series, markers, options = {}) {
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(220, Math.floor(rect.width));
      const h = Math.max(130, Math.floor(rect.height));
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;

      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, w, h);

      const showXAxis = Boolean(options.showXAxis);
      const pad = { l: 72, r: 12, t: 14, b: showXAxis ? 34 : 16 };
      const innerW = w - pad.l - pad.r;
      const innerH = h - pad.t - pad.b;
      if (innerW <= 0 || innerH <= 0) return [];

      const all = [];
      for (const s of series) {
        for (const v of s.values || []) {
          if (Number.isFinite(v)) all.push(v);
        }
      }
      if (!all.length) {
        ctx.fillStyle = COLORS.muted;
        ctx.font = '12px "IBM Plex Sans", sans-serif';
        ctx.fillText("Waiting for data...", pad.l, pad.t + 20);
        return [];
      }

      const domain = computeDomain(all);
      const toY = makeScale(domain.min, domain.max, pad.t, h - pad.b);
      const n = Math.max(
        1,
        options.pointCount || 0,
        ...series.map((s) => (s.values || []).length),
      );
      const toX = (i) => pad.l + (n <= 1 ? innerW * 0.5 : (i / (n - 1)) * innerW);

      ctx.strokeStyle = COLORS.grid;
      ctx.lineWidth = 1;
      const ticks = buildTicks(domain.min, domain.max, 5);
      ticks.forEach((tick) => {
        const y = toY(tick);
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
      });

      for (let i = 0; i < 5; i += 1) {
        const x = pad.l + (i / 4) * innerW;
        ctx.beginPath();
        ctx.moveTo(x, pad.t);
        ctx.lineTo(x, h - pad.b);
        ctx.stroke();
      }

      ctx.fillStyle = COLORS.axis;
      ctx.font = '11px "IBM Plex Mono", ui-monospace, monospace';
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ticks.forEach((tick) => {
        const y = toY(tick);
        ctx.fillText(fmtAxisMoney(tick), 6, y);
      });

      for (const s of series) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width || 1.8;
        ctx.beginPath();
        let started = false;
        (s.values || []).forEach((v, i) => {
          if (!Number.isFinite(v)) return;
          const x = toX(i);
          const y = toY(v);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        });
        ctx.stroke();
      }

      const hitboxes = [];
      (markers || []).forEach((m) => {
        if (!Number.isFinite(m.index) || !Number.isFinite(m.price)) return;
        const x = toX(m.index);
        const y = toY(m.price);
        const selected = markerKey(m) === options.selectedMarkerKey;
        const dotRadius = selected ? 5.8 : 4.2;
        const color =
          m.action === "buy" ? COLORS.buy : (m.action === "sell" ? COLORS.sell : COLORS.hold);

        ctx.fillStyle = color;
        traceDecisionMarker(ctx, m.action, x, y, dotRadius);
        ctx.fill();

        ctx.strokeStyle = selected ? COLORS.highlight : "#ffffff";
        ctx.lineWidth = selected ? 2 : 1.4;
        traceDecisionMarker(ctx, m.action, x, y, dotRadius + 0.4);
        ctx.stroke();

        hitboxes.push({
          x,
          y,
          r: dotRadius + 4,
          key: markerKey(m),
          data: m,
        });
      });

      if (showXAxis) {
        const labels = options.xLabels || [];
        const labelIndexes = Array.from(
          new Set(
            [0, Math.round((n - 1) * 0.5), n - 1]
              .map((idx) => Math.max(0, Math.min(n - 1, idx)))
          )
        );
        ctx.fillStyle = COLORS.axis;
        ctx.font = '11px "IBM Plex Mono", ui-monospace, monospace';
        ctx.textBaseline = "top";
        labelIndexes.forEach((idx) => {
          const x = toX(idx);
          const text = fmtClock(labels[idx], false);
          if (idx === 0) ctx.textAlign = "left";
          else if (idx === n - 1) ctx.textAlign = "right";
          else ctx.textAlign = "center";
          ctx.fillText(text, x, h - pad.b + 8);
        });
      }

      if (options.metaEl) {
        const latest = lastFinite((series[0] && series[0].values) || []);
        options.metaEl.textContent = `${fmtMoney(latest)} | y ${fmtMoney(domain.min)} to ${fmtMoney(domain.max)}`;
      }

      return hitboxes;
    }

    function updateInfo(state) {
      const latest = state.latest || {};
      const market = latest.market || {};
      const account = latest.account || {};
      const decision = latest.decision || {};

      document.getElementById("title").textContent =
        `WALTER LIVE DASHBOARD | ${state.coin || "COIN"}`;
      document.getElementById("status").textContent =
        `updated ${state.updated_at || "--"} | points ${state.timestamps?.length || 0}`;

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
        li.className = "event-item";
        li.textContent = e;
        eventsEl.appendChild(li);
      });
    }

    function renderDecisionDetails(marker) {
      if (!marker) {
        document.getElementById("detailTime").textContent = "--";
        document.getElementById("detailAction").textContent = "--";
        document.getElementById("detailPrice").textContent = "--";
        document.getElementById("detailSizeLev").textContent = "--";
        document.getElementById("detailInput").textContent = "--";
        document.getElementById("detailThinking").textContent = "--";
        return;
      }

      document.getElementById("detailTime").textContent = fmtClock(marker.timestamp, true);
      document.getElementById("detailAction").textContent = (marker.action || "--").toUpperCase();
      document.getElementById("detailPrice").textContent = fmtMoney(marker.price);
      const size = marker.size;
      const lev = marker.leverage;
      const sizeLev = `${fmtNum(size, 5)} / ${lev !== null && lev !== undefined ? lev : "n/a"}x`;
      document.getElementById("detailSizeLev").textContent = sizeLev;
      document.getElementById("detailInput").textContent = marker.llm_input || "--";
      document.getElementById("detailThinking").textContent = marker.thinking || "--";
    }

    function findMarkerAt(x, y) {
      let closest = null;
      let best = Number.POSITIVE_INFINITY;
      for (const hb of viewState.markerHitboxes) {
        const dx = x - hb.x;
        const dy = y - hb.y;
        const dist = Math.hypot(dx, dy);
        if (dist <= hb.r && dist < best) {
          best = dist;
          closest = hb;
        }
      }
      return closest;
    }

    function bindInteractions() {
      if (viewState.interactionsBound) return;
      const canvas = document.getElementById("priceChart");
      if (!canvas) return;

      const toCanvasCoord = (evt) => {
        const rect = canvas.getBoundingClientRect();
        return {
          x: (evt.clientX - rect.left) * (canvas.width / rect.width),
          y: (evt.clientY - rect.top) * (canvas.height / rect.height),
        };
      };

      canvas.addEventListener("mousemove", (evt) => {
        const { x, y } = toCanvasCoord(evt);
        const hit = findMarkerAt(x, y);
        canvas.style.cursor = hit ? "pointer" : "default";
      });

      canvas.addEventListener("mouseleave", () => {
        canvas.style.cursor = "default";
      });

      canvas.addEventListener("click", (evt) => {
        const { x, y } = toCanvasCoord(evt);
        const hit = findMarkerAt(x, y);
        if (!hit) return;
        viewState.selectedMarkerKey = hit.key;
        renderDecisionDetails(hit.data);
        if (viewState.latestApiState) {
          redrawCharts(viewState.latestApiState);
        }
      });

      viewState.interactionsBound = true;
    }

    function redrawCharts(state) {
      const timestamps = state.timestamps || [];
      const sharedCount = Math.max(
        timestamps.length,
        (state.prices || []).length,
        (state.account_values || []).length,
      );
      const markerIndex = new Map(timestamps.map((t, i) => [t, i]));
      const markers = (state.decision_markers || [])
        .map((m) => ({
          ...m,
          index: markerIndex.get(m.timestamp),
        }))
        .filter((m) => Number.isFinite(m.index) && Number.isFinite(m.price));

      if (viewState.selectedMarkerKey && !markers.some((m) => markerKey(m) === viewState.selectedMarkerKey)) {
        viewState.selectedMarkerKey = null;
        renderDecisionDetails(null);
      }

      viewState.markerHitboxes = drawChart(
        document.getElementById("priceChart"),
        [{ values: state.prices || [], color: COLORS.line, width: 1.9 }],
        markers,
        {
          metaEl: document.getElementById("priceMeta"),
          pointCount: sharedCount,
          selectedMarkerKey: viewState.selectedMarkerKey,
          showXAxis: false,
        },
      );

      drawChart(
        document.getElementById("valueChart"),
        [{ values: state.account_values || [], color: COLORS.account, width: 1.9 }],
        [],
        {
          metaEl: document.getElementById("valueMeta"),
          pointCount: sharedCount,
          xLabels: timestamps,
          showXAxis: true,
        },
      );
    }

    async function refresh() {
      try {
        const resp = await fetch("/api/state", { cache: "no-store" });
        const state = await resp.json();
        viewState.latestApiState = state;
        updateInfo(state);
        redrawCharts(state);
      } catch (err) {
        document.getElementById("status").textContent = "dashboard connection error";
      }
    }

    bindInteractions();
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
