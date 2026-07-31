"""阪神タイガース公式サイトから一軍試合日程・結果を取得してDBにupsertする。

対象ページ: https://hanshintigers.jp/game/schedule/{year}/{month:02d}l.html
このページはクライアントサイドJSでコンテンツが描画されるため、素のHTTP GETでは
データが取得できない（2026-07に確認済み）。Playwrightでheadless Chromiumを起動し、
実際にレンダリングされたテーブルを読み取る。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import find_stadium_id, get_conn, init_db  # noqa: E402
from teams import (  # noqa: E402
    HANSHIN_HOME_STADIUM_IDS,
    ICON_CODE_TO_SCORE_CODE,
    SCORE_CODE_TO_TEAM,
)

BASE_URL = "https://hanshintigers.jp/game/schedule"
SCORE_RE = re.compile(r"([一-龥ァ-ヶー]{1,3})\s*(\d+)\s*-\s*(\d+)\s*([一-龥ァ-ヶー]{1,3})")
ICON_RE = re.compile(r"icon_([a-z]+)_L\.gif")


def fetch_month_html(year: int, month: int) -> str:
    url = f"{BASE_URL}/{year}/{month:02d}l.html"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ))
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("table", timeout=10000)
        html = page.content()
        browser.close()
    return html


def _opponent_from_icon(img_src: str | None) -> str | None:
    if not img_src:
        return None
    m = ICON_RE.search(img_src)
    if not m:
        return None
    score_code = ICON_CODE_TO_SCORE_CODE.get(m.group(1))
    if not score_code:
        return None
    return SCORE_CODE_TO_TEAM.get(score_code)


def parse_month(html: str, year: int, month: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    games = []
    for tr in table.find_all("tr"):
        th = tr.find("th")
        match_info = tr.find("td", class_="match_info")
        if th is None or match_info is None:
            continue

        day_text = th.get_text(" ", strip=True)  # 例: "1日 (水)"
        day_m = re.match(r"(\d+)日", day_text)
        if not day_m:
            continue
        day = int(day_m.group(1))
        game_date = date(year, month, day).isoformat()

        time_li = match_info.find("li", class_="time")
        game_time = time_li.get_text(strip=True) if time_li else None

        place_li = match_info.find("li", class_="place")
        venue_raw = place_li.get_text(strip=True) if place_li else ""

        detail_li = match_info.find("li", class_="detail")
        detail_text = detail_li.get_text(" ", strip=True) if detail_li else ""

        card_img = match_info.find("li", class_="card")
        icon_src = card_img.find("img")["src"] if card_img and card_img.find("img") else None

        # 公式戦のみ対象（交流戦も公式戦扱い）。オープン戦・練習試合・オールスターはスコープ外
        is_official = ("公式戦" in detail_text) or ("交流戦" in detail_text)
        if not is_official:
            continue

        cancelled = "中止" in detail_text
        suspended = "サスペンデッド" in detail_text
        score_match = SCORE_RE.search(detail_text)

        opponent = None
        hanshin_score = opponent_score = None
        status = "scheduled"

        if score_match:
            code1, s1, s2, code2 = score_match.groups()
            team1 = SCORE_CODE_TO_TEAM.get(code1)
            team2 = SCORE_CODE_TO_TEAM.get(code2)
            # 表記は常に「開催側 score - score 相手側」の順
            # (例: 東京Dでの巨人主催戦は "巨 4 - 3 神" のように相手が阪神でも先頭は開催側)
            if team1 == "阪神":
                opponent = team2
                hanshin_score, opponent_score = int(s1), int(s2)
            elif team2 == "阪神":
                opponent = team1
                hanshin_score, opponent_score = int(s2), int(s1)
            status = "confirmed"
        elif cancelled:
            status = "cancelled"
        elif suspended:
            status = "suspended"

        if opponent is None:
            opponent = _opponent_from_icon(icon_src)

        if opponent is None:
            # 対戦相手を特定できない行はスキップ（要手動確認）
            print(f"[warn] {game_date}: 対戦相手を特定できず skip (venue={venue_raw!r} detail={detail_text!r})",
                  file=sys.stderr)
            continue

        games.append({
            "game_date": game_date,
            "game_time": game_time,
            "opponent": opponent,
            "venue_raw": venue_raw,
            "status": status,
            "hanshin_score": hanshin_score,
            "opponent_score": opponent_score,
        })
    return games


def upsert_games(games: list[dict]) -> None:
    conn = get_conn()
    for g in games:
        stadium_id = find_stadium_id(conn, g["venue_raw"]) if g["venue_raw"] else None
        if stadium_id is None:
            print(f"[warn] {g['game_date']}: 球場名 {g['venue_raw']!r} をマスタで解決できず skip",
                  file=sys.stderr)
            continue
        side = "home" if stadium_id in HANSHIN_HOME_STADIUM_IDS else "away"

        conn.execute(
            """
            INSERT INTO games (game_date, game_time, opponent, side, stadium_id, status, hanshin_score, opponent_score)
            VALUES (:game_date, :game_time, :opponent, :side, :stadium_id, :status, :hanshin_score, :opponent_score)
            ON CONFLICT(game_date, opponent, side) DO UPDATE SET
                game_time = excluded.game_time,
                stadium_id = excluded.stadium_id,
                status = excluded.status,
                hanshin_score = excluded.hanshin_score,
                opponent_score = excluded.opponent_score
            """,
            {
                "game_date": g["game_date"],
                "game_time": g["game_time"],
                "opponent": g["opponent"],
                "side": side,
                "stadium_id": stadium_id,
                "status": g["status"],
                "hanshin_score": g["hanshin_score"],
                "opponent_score": g["opponent_score"],
            },
        )
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="阪神戦 日程スクレイパー")
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--months", type=int, nargs="+",
                         default=[date.today().month, min(date.today().month + 1, 10)])
    args = parser.parse_args()

    init_db()

    all_games = []
    for month in sorted(set(args.months)):
        if not (2 <= month <= 10):
            continue
        html = fetch_month_html(args.year, month)
        games = parse_month(html, args.year, month)
        print(f"{args.year}-{month:02d}: {len(games)}試合を取得")
        all_games.extend(games)

    upsert_games(all_games)
    print(f"合計 {len(all_games)} 試合をDBに反映しました")


if __name__ == "__main__":
    main()
