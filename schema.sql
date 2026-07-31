-- 阪神戦 球場・天気トラッカー DBスキーマ

CREATE TABLE IF NOT EXISTS stadiums (
    id            TEXT PRIMARY KEY,      -- 例: "koshien"
    official_name TEXT NOT NULL,         -- "阪神甲子園球場"
    aliases       TEXT NOT NULL DEFAULT '[]', -- JSON配列文字列 例: ["甲子園","阪神甲子園"]
    is_dome       INTEGER NOT NULL DEFAULT 0, -- 0/1
    lat           REAL,
    lon           REAL
);

CREATE TABLE IF NOT EXISTS games (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    game_date          TEXT NOT NULL,       -- ISO8601 "2026-07-02"
    game_time          TEXT,                -- "18:00" (試合開始時刻、不明な場合NULL)
    opponent           TEXT NOT NULL,       -- "巨人"
    side               TEXT NOT NULL CHECK (side IN ('home','away')),
    stadium_id         TEXT NOT NULL REFERENCES stadiums(id),
    status             TEXT NOT NULL CHECK (
                           status IN ('scheduled','forecast','confirmed','postponed','suspended','cancelled')
                       ),
    hanshin_score      INTEGER,
    opponent_score     INTEGER,
    actual_sky         TEXT,
    actual_temp        REAL,
    actual_fetched_at  TEXT,
    linked_game_id     INTEGER REFERENCES games(id),
    note               TEXT,
    UNIQUE (game_date, opponent, side)
);

CREATE TABLE IF NOT EXISTS forecasts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id    INTEGER NOT NULL REFERENCES games(id),
    fetched_at TEXT NOT NULL,   -- ISO8601 timestamp
    sky        TEXT,
    temp       REAL,
    pop        REAL             -- 降水確率(%)、取得できない場合はNULL
);

CREATE INDEX IF NOT EXISTS idx_forecasts_game ON forecasts(game_id);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
