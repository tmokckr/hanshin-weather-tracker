# 阪神＊天気トラッカー

阪神タイガース一軍公式戦（ホーム＋ビジター）の球場と、試合開始時点の天気（予報→確定）を
自動収集し、静的サイトとして公開するツール。

## 仕組み

1. `src/scrape_schedule.py` — 阪神タイガース公式サイトの日程ページを Playwright(headless Chromium) で
   レンダリングして取得（素のHTTP GETではJS描画前のデータが空の殻しか返らないため）。
2. `src/fetch_weather.py` — OpenWeatherMap で天気を取得。
   - 未来の試合: 5日/3時間ごとの予報から試合時刻に最も近い枠を `forecasts` テーブルに**追記**（上書きしない＝予報の変化を全部残す）
   - 終了済みの試合: 現在天気を取得して `games.actual_*` に記録
   - ドーム球場（京セラドーム/東京ドーム/バンテリン/ベルーナ/PayPay/エスコン）は天気取得の対象外
3. `src/build_site.py` — SQLite の内容から `docs/index.html` を生成（GitHub Pages公開用）
4. `.github/workflows/update.yml` — 上記を6時間ごとに自動実行し、変更をコミット

## セットアップ（あなたが行う手順）

### 1. OpenWeatherMap APIキーを取得

https://openweathermap.org/api で無料アカウントを作成し、APIキーを発行してください
（このツール自体はキーの取得・アカウント作成を代行できません）。

### 2. GitHubリポジトリを作成してpush

```bash
cd hanshin-weather-tracker
git init
git add .
git commit -m "init"
gh repo create hanshin-weather-tracker --public --source=. --push
```

### 3. GitHub Secretsに登録

リポジトリの Settings > Secrets and variables > Actions で
`OWM_API_KEY` という名前でAPIキーを登録してください。

### 4. GitHub Pagesを有効化

Settings > Pages で Source を「Deploy from a branch」、Branch を `main` / `/docs` に設定してください。

## ローカルでの動作確認

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python3 src/scrape_schedule.py --year 2026 --months 7 8   # 日程取得
OWM_API_KEY=xxxx python3 src/fetch_weather.py              # 天気取得
python3 src/build_site.py                                  # サイト生成 -> docs/index.html
```

## 既知の制約

- **交流戦の対戦相手アイコン**: パ・リーグ球団（西武/日本ハム/オリックス/ソフトバンク/楽天/ロッテ）の
  スコア表記コードは実データで確認済みだが、対戦カード欄のアイコンファイル名からの推測コード
  (`src/teams.py` の `ICON_CODE_TO_SCORE_CODE`) は一部未検証。スコアが確定していない将来の交流戦で
  対戦相手が正しく取れない場合、`[warn]` ログが出るのでその球団のコードを確認・追記してください。
- **実績天気は近似値**: OpenWeatherMap無料枠には過去日時の実況天気APIが無いため、「確定」試合の
  実績天気は取得実行時点の現在天気で代用しています（同日中に実行できれば概ね近い値になりますが、
  数日後に初めて取得する場合は不正確になります）。この場合は `games.note` に注記が入ります。
- **順延・サスペンデッドの試合の紐付け（linked_game_id）**: 公式サイトの日程ページには
  「中止試合がどの日に順延されたか」を示す情報が無いため、自動では紐付けられません。
  手動で紐付ける場合は以下のようにSQLiteを直接更新してください。

  ```sql
  UPDATE games SET linked_game_id = <振替試合のid> WHERE id = <中止試合のid>;
  ```

- **サスペンデッドゲームの検出は未検証**: `詳細` 欄に「サスペンデッド」という文言が出た場合のみ
  `status='suspended'` にする実装だが、実際の表記を確認できていない。該当試合が出た際は
  `src/scrape_schedule.py` の判定文言を実データに合わせて調整してください。
