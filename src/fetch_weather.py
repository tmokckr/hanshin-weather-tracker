"""OpenWeatherMap から天気を取得し、forecasts履歴とgames.actual_*を更新する。

- ドーム球場（stadiums.is_dome=1）は天気取得の対象外（第一級のNULL/対象外として扱う）
- 予定(scheduled)の試合: 5日/3時間ごとの予報から試合時刻に最も近い枠を取得し、
  forecastsに追記（既存行は上書きしない＝予報の変化を全部残す）。取得できたら
  games.status を 'scheduled' -> 'forecast' に進める。
- 確定(confirmed)の試合でまだ実績天気(actual_fetched_at)が無いもの: 現在天気を取得して
  actual_sky/actual_tempに記録する。無料APIには過去日時の実況値が無いため、試合当日中に
  このスクリプトを実行できなかった場合は「現在天気で代用」である旨をnoteに残す。

APIキーは環境変数 OWM_API_KEY から読む。未設定の場合は何もせず終了する
（スケジュール取得だけ先に動かしたい場合のため）。
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_conn, init_db  # noqa: E402

CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
FORECAST_HORIZON_DAYS = 5  # OpenWeatherMap無料枠の予報範囲


def _game_datetime(game_date: str, game_time: str | None) -> datetime:
    hh, mm = (game_time or "12:00").split(":")
    d = date.fromisoformat(game_date)
    return datetime(d.year, d.month, d.day, int(hh), int(mm))


def fetch_forecast_for_game(api_key: str, lat: float, lon: float, target_dt: datetime) -> dict | None:
    resp = requests.get(FORECAST_URL, params={
        "lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "ja",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    entries = data.get("list", [])
    if not entries:
        return None
    best = min(entries, key=lambda e: abs(datetime.utcfromtimestamp(e["dt"]) - target_dt))
    return {
        "sky": best["weather"][0]["description"] if best.get("weather") else None,
        "temp": best.get("main", {}).get("temp"),
        "pop": best.get("pop"),
    }


def fetch_current_weather(api_key: str, lat: float, lon: float) -> dict | None:
    resp = requests.get(CURRENT_URL, params={
        "lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "ja",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {
        "sky": data["weather"][0]["description"] if data.get("weather") else None,
        "temp": data.get("main", {}).get("temp"),
    }


def update_forecasts(conn, api_key: str) -> int:
    today = date.today()
    horizon = today + timedelta(days=FORECAST_HORIZON_DAYS)
    rows = conn.execute(
        """
        SELECT g.id, g.game_date, g.game_time, s.lat, s.lon
        FROM games g JOIN stadiums s ON g.stadium_id = s.id
        WHERE g.status = 'scheduled' AND s.is_dome = 0
          AND g.game_date >= ? AND g.game_date <= ?
        """,
        (today.isoformat(), horizon.isoformat()),
    ).fetchall()

    count = 0
    for row in rows:
        target_dt = _game_datetime(row["game_date"], row["game_time"])
        try:
            result = fetch_forecast_for_game(api_key, row["lat"], row["lon"], target_dt)
        except requests.RequestException as e:
            print(f"[error] game {row['id']} 予報取得失敗: {e}", file=sys.stderr)
            continue
        if result is None:
            continue
        conn.execute(
            "INSERT INTO forecasts (game_id, fetched_at, sky, temp, pop) VALUES (?, ?, ?, ?, ?)",
            (row["id"], datetime.utcnow().isoformat(timespec="seconds") + "Z",
             result["sky"], result["temp"], result["pop"]),
        )
        conn.execute("UPDATE games SET status = 'forecast' WHERE id = ? AND status = 'scheduled'", (row["id"],))
        count += 1
    return count


def update_actuals(conn, api_key: str) -> int:
    today_iso = date.today().isoformat()
    rows = conn.execute(
        """
        SELECT g.id, g.game_date, s.lat, s.lon
        FROM games g JOIN stadiums s ON g.stadium_id = s.id
        WHERE g.status = 'confirmed' AND s.is_dome = 0 AND g.actual_fetched_at IS NULL
        """
    ).fetchall()

    count = 0
    for row in rows:
        try:
            result = fetch_current_weather(api_key, row["lat"], row["lon"])
        except requests.RequestException as e:
            print(f"[error] game {row['id']} 実況天気取得失敗: {e}", file=sys.stderr)
            continue
        if result is None:
            continue
        note = None
        if row["game_date"] != today_iso:
            note = "実況値ではなく取得時点の現在天気で代用（無料APIには過去日時の実況値がないため）"
        conn.execute(
            "UPDATE games SET actual_sky = ?, actual_temp = ?, actual_fetched_at = ?, note = COALESCE(note, ?) "
            "WHERE id = ?",
            (result["sky"], result["temp"], datetime.utcnow().isoformat(timespec="seconds") + "Z", note, row["id"]),
        )
        count += 1
    return count


def main() -> None:
    api_key = os.environ.get("OWM_API_KEY")
    if not api_key:
        print("[warn] OWM_API_KEY が未設定のため天気取得をスキップします", file=sys.stderr)
        return

    init_db()
    conn = get_conn()
    n_forecast = update_forecasts(conn, api_key)
    n_actual = update_actuals(conn, api_key)
    conn.commit()
    conn.close()
    print(f"予報 {n_forecast} 件、実績 {n_actual} 件を更新しました")


if __name__ == "__main__":
    main()
