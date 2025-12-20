# Notion Task Sync & Notification System

Notion のタスクデータベースを中心に、LINE へのリマインド通知と Google カレンダーとの双方向同期を行う Python システムです。

## 概要

このプロジェクトは 2 つの主要な機能を提供します：

1.  **タスク通知 (`task_notifier.py`)**:
    - Notion のタスク DB から、期限が迫っているタスクや着手すべきタスクを抽出します。
    - LINE Messaging API を使用して、指定されたグループまたはユーザーに通知を送ります。
2.  **Google カレンダー同期 (`sync_main.py`)**:

    - Notion の「作業日」プロパティと Google カレンダーを双方向同期します。
    - 更新日時 (`last_edited_time`) を比較し、新しい方の情報を採用します。
    - Notion 側で「保留中」または「作業日なし」となった場合、カレンダーのタイトルを【中止】に変更します。

3.  **四半期振り返りレポート生成 (`quarterly_review.py`)**:
    - Notion の完了タスクと Google カレンダーのイベント実績を収集します。
    - Google Gemini (AI) を使用して、活動内容を分析し、振り返りレポートを自動生成します。
    - 結果を Notion の「振り返りデータベース」に新規ページとして保存します。

## ディレクトリ構成

```text
.
├── task_notifier.py     # LINE通知用スクリプト (Main)
├── sync_main.py         # Googleカレンダー同期用スクリプト (Main)
├── quarterly_review.py  # 四半期振り返り生成スクリプト (Main)
├── service_account.json # Googleサービスアカウントキー (GCPからダウンロード)
├── .env                 # 環境変数設定ファイル
├── requirements.txt     # 依存ライブラリリスト
└── module/              # 共通モジュール
    ├── __init__.py
    ├── notion_api.py    # Notion API操作・データ整形クラス
    ├── google_cal_api.py# Google Calendar API操作クラス
    ├── line_notifier.py # LINE通知関数
    └── util.py          # ユーティリティ関数 (ソート・フィルタリング等)
```

## 前提条件

- Python 3.10 以上推奨
- Google Cloud Platform (GCP) アカウント（Service Account の作成権限）
- Notion API トークンと対象データベースへの権限
- LINE Developers アカウント（Messaging API）

## セットアップ手順

### 1\. ライブラリのインストール

```bash
pip install pandas requests python-dotenv google-api-python-client google-auth google-genai
```

※ 必要に応じて `requirements.txt` を作成して管理してください。

### 2\. Google Cloud Platform (GCP) の設定

1.  GCP コンソールでプロジェクトを作成し、**Google Calendar API** を有効化します。
2.  **サービスアカウント**を作成し、JSON キーを発行します。
3.  発行された JSON ファイルを `service_account.json` にリネームしてプロジェクトルートに配置します。
4.  同期したい Google カレンダーの「設定と共有」を開き、サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）を\*\*「変更および共有の管理権限」\*\*で追加します。

### 3\. Notion データベースの準備

タスク管理用データベースには、Notion のテンプレートは[課題管理](https://www.notion.so/gallery/templates/notion-issue-tracker?cr=ser%253A%25E3%2582%25B9%25E3%2583%2597%25E3%2583%25AA%25E3%2583%25B3%25E3%2583%2588)を活用しています。
タスクのデータベースに以下のプロパティが存在することを確認、もしくは、追加してください。

| プロパティ名      | 種類           | 用途                                      |
| :---------------- | :------------- | :---------------------------------------- |
| **タスク名**      | タイトル       | タスクのタイトル                          |
| **作業日**        | 日付           | Google カレンダー同期用の日付             |
| **期限**          | 日付           | 締め切り管理用                            |
| **ステータス**    | ステータス     | 進行状況 (未着手/進行中/完了/保留中 など) |
| **プロジェクト**  | リレーション   | プロジェクト DB との紐付け                |
| **スプリント**    | リレーション   | スプリント DB との紐付け                  |
| **タグ**          | マルチセレクト | タスクの分類                              |
| **GCal_Event_ID** | **テキスト**   | GCal イベント ID の保存用 (同期に必須)    |

### 4\. 環境変数の設定

プロジェクトルートに `.env` ファイルを作成し、以下の内容を記述してください。

```ini
# --- Notion API ---
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_TASK_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # タスクDBのID
NOTION_PJ_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx    # プロジェクトDBのID
NOTION_SPRINT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx # スプリントDBのID
NOTION_REVIEW_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx # 振り返りページ作成先のDB ID

# --- LINE Messaging API ---
LINE_CHANNEL_ACCESS_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LINE_MESSAGE_API_GROUP_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx # 通知先のユーザーIDまたはグループID

# --- Google Calendar ---
# 同期対象のカレンダーID (メインカレンダーの場合はGmailアドレス、別カレンダーの場合は固有ID)
GOOGLE_CALENDAR_ID=xxxxxxxx@group.calendar.google.com
GOOGLE_CALENDAR_IDS=primary, ..., ...
# サービスアカウントキーのパス (デフォルトは service_account.json)
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json

# --- Google Gemini API ---
GOOGLE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # AIスタジオで発行したAPIキー
```

## 使用方法

### LINE 通知の実行

期限が近いタスクを通知します。朝の定時実行などが推奨されます。

```bash
python task_notifier.py
```

### Google カレンダー同期の実行

Notion と Google カレンダーを同期します。短期間（例：15 分ごと）の定期実行が推奨されます。

```bash
python sync_main.py
```

## 定期実行の設定例 (crontab)

Ubuntu/Linux 環境での `crontab -e` 設定例です。

```bash
# 毎日 朝 8:00 にLINE通知を実行
0 8 * * * cd /path/to/project && /usr/bin/python3 task_notifier.py >> notifier.log 2>&1

# 15分ごとにGoogleカレンダー同期を実行
*/15 * * * * cd /path/to/project && /usr/bin/python3 sync_main.py >> sync.log 2>&1
```

### 四半期振り返りの生成

直前の四半期（1〜3 月、4〜6 月...）のデータを収集し、Notion にレポートを作成します。
四半期が終わったタイミング（4 月、7 月...の初旬）での実行を想定しています。

```bash
python quarterly_review.py
```

## 仕様詳細

### カレンダー同期ルール

- **タイトル形式:** `タスク名【プロジェクト名】`
- **同期判定:**
  - タイトルと日付が完全一致する場合はスキップ。
  - Notion と GCal の最終更新日時を比較し、新しい方を正として上書きします。
- **中止/保留の扱い:**
  - Notion の「作業日」が空、またはステータスが「保留中」の場合、GCal 側のタイトル先頭に `【中止】` を付与します。
  - GCal 側からイベントを削除する処理は行いません（ログ保全のため）。

## ライセンス

This project is for personal use.

```

```
