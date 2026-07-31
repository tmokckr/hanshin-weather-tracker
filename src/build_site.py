"""SQLiteのデータから docs/index.html を生成する（GitHub Pages公開用の静的サイト）。

デザイン/レイアウトはユーザー承認済みのモック(hanshin-mock.html)を踏襲し、
中身のデータだけ実データに差し替える。フィルタは実際に動作するよう
クライアントサイドJSで軽く実装する。
"""
from __future__ import annotations

import json
import sys
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_conn, init_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"

DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]

STATUS_LABEL = {
    "confirmed": "確定", "forecast": "予報", "scheduled": "予定",
    "postponed": "順延", "suspended": "中断", "cancelled": "中止",
}


def sky_to_icon(sky: str | None) -> str:
    if not sky:
        return "—"
    if "雷" in sky:
        return "⛈️"
    if "雪" in sky:
        return "❄️"
    if "雨" in sky:
        return "🌧️" if "強" in sky or "本" in sky else "🌦️"
    if "曇" in sky:
        return "☁️" if "本" in sky else "⛅"
    if "晴" in sky:
        return "☀️" if "快" in sky else "🌤️"
    return "🌡️"


def build_game_records(conn) -> list[dict]:
    games = conn.execute(
        """
        SELECT g.*, s.official_name AS stadium_name, s.is_dome
        FROM games g JOIN stadiums s ON g.stadium_id = s.id
        ORDER BY g.game_date
        """
    ).fetchall()

    forecasts_by_game: dict[int, list[dict]] = {}
    for row in conn.execute("SELECT * FROM forecasts ORDER BY game_id, fetched_at"):
        forecasts_by_game.setdefault(row["game_id"], []).append({
            "t": row["fetched_at"], "sky": row["sky"] or "—",
            "temp": f"{row['temp']:.0f}℃" if row["temp"] is not None else "—",
            "pop": f"{row['pop']*100:.0f}%" if row["pop"] is not None else "—",
        })

    games_by_id = {g["id"]: g for g in games}
    records = []
    for g in games:
        d = date_cls.fromisoformat(g["game_date"])
        dow = DOW_JA[d.weekday()]
        is_dome = bool(g["is_dome"])

        if is_dome:
            weather = {"icon": "—", "label": "屋内（対象外）", "temp": "—"}
        elif g["status"] == "confirmed" and g["actual_sky"]:
            weather = {"icon": sky_to_icon(g["actual_sky"]), "label": g["actual_sky"],
                       "temp": f"{g['actual_temp']:.0f}℃" if g["actual_temp"] is not None else "—"}
        elif g["status"] in ("forecast",) and g["id"] in forecasts_by_game:
            latest = forecasts_by_game[g["id"]][-1]
            weather = {"icon": sky_to_icon(latest["sky"]), "label": latest["sky"], "temp": latest["temp"]}
        elif g["status"] == "cancelled":
            weather = {"icon": "🌧️", "label": "中止", "temp": "—"}
        else:
            weather = {"icon": "—", "label": "未取得", "temp": "—"}

        detail = {"type": "plain", "note": g["note"] or ""}
        if g["linked_game_id"] and g["linked_game_id"] in games_by_id:
            linked = games_by_id[g["linked_game_id"]]
            ld = date_cls.fromisoformat(linked["game_date"])
            detail = {
                "type": "linked",
                "linkedTo": f"{ld.month}/{ld.day}({DOW_JA[ld.weekday()]}) と関連",
                "note": g["note"] or "",
            }
        elif g["id"] in forecasts_by_game:
            detail = {"type": "forecast-history", "rows": forecasts_by_game[g["id"]]}

        records.append({
            "date": f"{d.month:02d}/{d.day:02d}",
            "dow": dow,
            "side": g["side"],
            "opponent": g["opponent"],
            "stadium": g["stadium_name"],
            "dome": is_dome,
            "status": g["status"],
            "weather": weather,
            "detail": detail,
            "hanshinScore": g["hanshin_score"],
            "opponentScore": g["opponent_score"],
        })
    return records


CSS = """
:root {
  --bg: #f5f2ea; --surface: #ffffff; --surface-2: #ece7d9; --ink: #1c1a16;
  --muted: #6b6558; --border: #ddd6c4; --accent: #b8860b; --accent-ink: #14110a;
  --good: #2f6b3f; --good-bg: #e3ede4; --warn: #a15c00; --warn-bg: #f3e3c8;
  --bad: #9c3b34; --bad-bg: #f1ddd8; --info: #395a7a; --info-bg: #dfe6ec;
  --dome: #5c4a7a; --dome-bg: #e7e0ee; --shadow: 0 1px 2px rgba(28,26,22,0.06), 0 1px 1px rgba(28,26,22,0.04);
}
:root[data-theme="dark"] {
  --bg: #17140f; --surface: #211d16; --surface-2: #2a251c; --ink: #ece6d8;
  --muted: #a89f8c; --border: #3a3327; --accent: #e0a52c; --accent-ink: #1a1509;
  --good: #7cbf8a; --good-bg: #223229; --warn: #e0a542; --warn-bg: #3a2c15;
  --bad: #e08379; --bad-bg: #3a2420; --info: #8fb3d6; --info-bg: #212d38;
  --dome: #c4a8e8; --dome-bg: #2a2236; --shadow: 0 1px 2px rgba(0,0,0,0.4);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #17140f; --surface: #211d16; --surface-2: #2a251c; --ink: #ece6d8;
    --muted: #a89f8c; --border: #3a3327; --accent: #e0a52c; --accent-ink: #1a1509;
    --good: #7cbf8a; --good-bg: #223229; --warn: #e0a542; --warn-bg: #3a2c15;
    --bad: #e08379; --bad-bg: #3a2420; --info: #8fb3d6; --info-bg: #212d38;
    --dome: #c4a8e8; --dome-bg: #2a2236; --shadow: 0 1px 2px rgba(0,0,0,0.4);
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--ink);
  font-family: -apple-system, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.5; padding: 32px clamp(16px, 4vw, 48px) 64px;
}
.wrap { max-width: 1080px; margin: 0 auto; }
header.page {
  display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
  flex-wrap: wrap; margin-bottom: 4px; border-bottom: 3px solid var(--accent); padding-bottom: 14px;
}
h1 { font-size: 22px; font-weight: 800; letter-spacing: 0.01em; margin: 0; text-wrap: balance; }
h1 .stripe {
  display: inline-block; background: var(--accent-ink); color: var(--accent); padding: 2px 8px;
  margin-right: 8px; border-radius: 3px; font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-weight: 700; font-size: 15px; letter-spacing: 0.04em;
}
.subtitle { color: var(--muted); font-size: 12.5px; margin-top: 6px; }
.meta-note { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0 22px; }
.filter-group {
  display: flex; align-items: center; gap: 6px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; box-shadow: var(--shadow);
}
.filter-group label { font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap; }
select { background: transparent; border: none; color: var(--ink); font-size: 13px; font-family: inherit; padding: 2px 4px; }
select:focus-visible { outline: 2px solid var(--accent); border-radius: 4px; }
.stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 24px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; box-shadow: var(--shadow); }
.stat .n { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat .l { color: var(--muted); font-size: 11.5px; margin-top: 2px; }
.list { display: flex; flex-direction: column; gap: 8px; }
.game { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); overflow: hidden; }
.game-row {
  display: grid; grid-template-columns: 92px 1fr 150px 160px 110px 28px; align-items: center;
  gap: 14px; padding: 12px 14px; cursor: pointer;
}
.game-row:hover { background: var(--surface-2); }
.game-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.date { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums; font-size: 13px; color: var(--muted); line-height: 1.3; }
.date .dow { font-size: 11px; }
.matchup { display: flex; align-items: center; gap: 8px; min-width: 0; }
.side-badge { font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; letter-spacing: 0.03em; flex-shrink: 0; }
.side-badge.home { background: var(--accent-ink); color: var(--accent); }
.side-badge.away { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
.opponent { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.score { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums; color: var(--muted); font-size: 12px; margin-left: 4px; }
.stadium { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12.5px; min-width: 0; }
.stadium .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dome-icon {
  flex-shrink: 0; width: 15px; height: 15px; border-radius: 50%; background: var(--dome-bg); color: var(--dome);
  display: inline-flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700;
}
.weather-cell { font-size: 12.5px; display: flex; align-items: center; gap: 6px; }
.weather-cell .icon { font-size: 15px; }
.weather-cell .temp { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums; color: var(--muted); }
.weather-cell.na { color: var(--muted); font-style: italic; }
.status-chip { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 999px; text-align: center; letter-spacing: 0.02em; white-space: nowrap; }
.status-chip.confirmed { background: var(--good-bg); color: var(--good); }
.status-chip.forecast { background: var(--info-bg); color: var(--info); }
.status-chip.scheduled { background: var(--surface-2); color: var(--muted); }
.status-chip.postponed, .status-chip.suspended { background: var(--warn-bg); color: var(--warn); }
.status-chip.cancelled { background: var(--bad-bg); color: var(--bad); }
.chevron { color: var(--muted); font-size: 12px; transition: transform 0.15s ease; justify-self: end; }
.game.open .chevron { transform: rotate(90deg); }
.detail { display: none; border-top: 1px solid var(--border); padding: 14px 14px 16px 106px; background: var(--surface-2); font-size: 12.5px; }
.game.open .detail { display: block; }
.link-note { display: inline-flex; align-items: center; gap: 5px; color: var(--warn); font-weight: 600; margin-bottom: 10px; }
.forecast-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.forecast-table caption { text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
.forecast-table th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11.5px; padding: 4px 10px 4px 0; border-bottom: 1px solid var(--border); }
.forecast-table td { padding: 5px 10px 5px 0; border-bottom: 1px dashed var(--border); }
.forecast-table tr:last-child td { border-bottom: none; font-weight: 600; }
.note-text { color: var(--muted); margin-top: 10px; }
.empty-msg { color: var(--muted); text-align: center; padding: 40px 0; font-size: 13px; }
@media (max-width: 720px) {
  .game-row {
    grid-template-columns: 1fr auto;
    grid-template-areas: "date chevron" "matchup matchup" "stadium weather" "status status";
    row-gap: 6px;
  }
  .date { grid-area: date; } .chevron { grid-area: chevron; } .matchup { grid-area: matchup; }
  .stadium { grid-area: stadium; } .weather-cell { grid-area: weather; justify-self: end; }
  .status-chip { grid-area: status; justify-self: start; } .detail { padding-left: 14px; }
}
footer.mock-note { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--border); color: var(--muted); font-size: 11.5px; }
"""

JS_TEMPLATE = """
const games = __GAMES_JSON__;

const listEl = document.getElementById("game-list");
const statusLabel = __STATUS_LABEL_JSON__;

function renderDetail(g) {
  const d = g.detail;
  let inner = "";
  if (d.type === "linked") {
    inner += `<div class="link-note">↔ ${d.linkedTo}</div>`;
  }
  if (d.type === "forecast-history") {
    inner += `<table class="forecast-table">
      <caption>予報の変化履歴（取得のたびに追記）</caption>
      <thead><tr><th>取得時刻(UTC)</th><th>天気</th><th>気温</th><th>降水確率</th></tr></thead>
      <tbody>${d.rows.map(r => `<tr><td>${r.t}</td><td>${r.sky}</td><td>${r.temp}</td><td>${r.pop}</td></tr>`).join("")}</tbody>
    </table>`;
  }
  if (d.note) inner += `<div class="note-text">${d.note}</div>`;
  if (!inner) inner = `<div class="note-text">追加情報はありません。</div>`;
  return inner;
}

function scoreText(g) {
  if (g.hanshinScore === null || g.hanshinScore === undefined) return "";
  return `<span class="score">${g.hanshinScore}-${g.opponentScore}</span>`;
}

function renderRow(g, idx) {
  const domeChip = g.dome ? `<span class="dome-icon" title="ドーム球場">D</span>` : "";
  const weatherClass = g.weather.label.includes("対象外") ? "weather-cell na" : "weather-cell";
  return `
    <div class="game" id="game-${idx}" data-side="${g.side}" data-status="${g.status}" data-dome="${g.dome}" data-opponent="${g.opponent}">
      <div class="game-row" role="button" tabindex="0" aria-expanded="false" data-idx="${idx}">
        <div class="date">${g.date}<div class="dow">(${g.dow})</div></div>
        <div class="matchup">
          <span class="side-badge ${g.side}">${g.side === "home" ? "HOME" : "AWAY"}</span>
          <span class="opponent">対 ${g.opponent}</span>${scoreText(g)}
        </div>
        <div class="stadium">${domeChip}<span class="name">${g.stadium}</span></div>
        <div class="${weatherClass}"><span class="icon">${g.weather.icon}</span><span>${g.weather.label}</span><span class="temp">${g.weather.temp}</span></div>
        <div class="status-chip ${g.status}">${statusLabel[g.status] || g.status}</div>
        <div class="chevron">▶</div>
      </div>
      <div class="detail">${renderDetail(g)}</div>
    </div>
  `;
}

function applyFilters() {
  const side = document.getElementById("f-side").value;
  const status = document.getElementById("f-status").value;
  const venue = document.getElementById("f-venue").value;
  const opp = document.getElementById("f-opp").value;
  let visible = 0;
  document.querySelectorAll(".game").forEach(el => {
    let ok = true;
    if (side !== "all" && el.dataset.side !== side) ok = false;
    if (status !== "all" && el.dataset.status !== status) ok = false;
    if (venue === "outdoor" && el.dataset.dome === "true") ok = false;
    if (venue === "dome" && el.dataset.dome === "false") ok = false;
    if (opp !== "all" && el.dataset.opponent !== opp) ok = false;
    el.style.display = ok ? "" : "none";
    if (ok) visible++;
  });
  document.getElementById("visible-count").textContent = visible;
}

listEl.innerHTML = games.map(renderRow).join("");

const opponents = [...new Set(games.map(g => g.opponent))].sort();
const oppSel = document.getElementById("f-opp");
opponents.forEach(o => {
  const opt = document.createElement("option");
  opt.value = o; opt.textContent = o;
  oppSel.appendChild(opt);
});

listEl.addEventListener("click", (e) => {
  const row = e.target.closest(".game-row");
  if (!row) return;
  toggle(row);
});
listEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    const row = e.target.closest(".game-row");
    if (!row) return;
    e.preventDefault();
    toggle(row);
  }
});
function toggle(row) {
  const parent = row.closest(".game");
  const willOpen = !parent.classList.contains("open");
  parent.classList.toggle("open");
  row.setAttribute("aria-expanded", String(willOpen));
}

["f-side", "f-status", "f-venue", "f-opp"].forEach(id => {
  document.getElementById(id).addEventListener("change", applyFilters);
});
applyFilters();
"""


def render_html(records: list[dict], generated_at: str) -> str:
    total = len(records)
    confirmed = sum(1 for r in records if r["status"] == "confirmed")
    forecast = sum(1 for r in records if r["status"] == "forecast")
    trouble = sum(1 for r in records if r["status"] in ("postponed", "suspended"))

    js = (JS_TEMPLATE
          .replace("__GAMES_JSON__", json.dumps(records, ensure_ascii=False))
          .replace("__STATUS_LABEL_JSON__", json.dumps(STATUS_LABEL, ensure_ascii=False)))

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>阪神＊天気トラッカー</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="page">
    <div>
      <h1><span class="stripe">HT</span>阪神＊天気トラッカー</h1>
      <div class="subtitle">阪神タイガース 一軍公式戦 — 球場 × 天気（予報・確定）管理</div>
    </div>
    <div class="meta-note">最終更新: {generated_at} ／ <span id="visible-count">{total}</span>/{total}試合を表示</div>
  </header>

  <div class="toolbar">
    <div class="filter-group"><label for="f-side">主催</label>
      <select id="f-side"><option value="all">すべて</option><option value="home">ホーム</option><option value="away">ビジター</option></select>
    </div>
    <div class="filter-group"><label for="f-status">状態</label>
      <select id="f-status">
        <option value="all">すべて</option><option value="confirmed">確定</option><option value="forecast">予報</option>
        <option value="scheduled">予定</option><option value="postponed">順延</option><option value="suspended">中断</option><option value="cancelled">中止</option>
      </select>
    </div>
    <div class="filter-group"><label for="f-venue">球場</label>
      <select id="f-venue"><option value="all">すべて</option><option value="outdoor">屋外のみ</option><option value="dome">ドームのみ</option></select>
    </div>
    <div class="filter-group"><label for="f-opp">対戦相手</label>
      <select id="f-opp"><option value="all">すべて</option></select>
    </div>
  </div>

  <div class="stat-row">
    <div class="stat"><div class="n">{total}</div><div class="l">対象試合</div></div>
    <div class="stat"><div class="n">{confirmed}</div><div class="l">確定（実績あり）</div></div>
    <div class="stat"><div class="n">{forecast}</div><div class="l">予報のみ</div></div>
    <div class="stat"><div class="n">{trouble}</div><div class="l">順延・中断あり</div></div>
  </div>

  <div class="list" id="game-list"></div>
  <footer class="mock-note">阪神タイガース公式サイトの日程・結果を毎日自動取得。天気はOpenWeatherMapを利用（ドーム球場は対象外）。</footer>
</div>
<script>{js}</script>
</body>
</html>
"""


def main() -> None:
    from datetime import datetime, timezone
    init_db()
    conn = get_conn()
    records = build_game_records(conn)
    conn.close()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_html(records, generated_at)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"{len(records)}試合分を docs/index.html に書き出しました")


if __name__ == "__main__":
    main()
