import os
import datetime
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from google import genai
from dotenv import load_dotenv

# 既存モジュールのインポート
from module.notion_api import TaskDB, ReviewDB
from module.google_cal_api import GoogleCalendarAPI

load_dotenv()

# --- 設定読み込み ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_TASK_ID = os.getenv("NOTION_TASK_ID")
NOTION_REVIEW_DB_ID = os.getenv("NOTION_REVIEW_DATABASE_ID")
# GoogleカレンダーID（カンマ区切りで複数指定可能）
CALENDAR_IDS = os.getenv("GOOGLE_CALENDAR_IDS", "primary").split(",")
# サービスアカウントキーパス
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")


# --- ダミークラス定義 ---
class DummyRelatedDB:
    """TaskDB初期化のためのダミークラス。

    TaskDBの__init__でrelated_dbsが要求されるが、
    今回はAPI経由での取得のみを行うため、実体は不要。
    """

    def get_item_from_pd(self, *args, **kwargs):
        return None


def get_target_quarter_range() -> tuple[datetime.date, datetime.date]:
    """現在の日付から「直前の四半期」の期間を算出します。

    実行日が属する四半期の前の四半期（3ヶ月間）の開始日と終了日を計算します。
    例: 5月実行 -> 1月1日〜3月31日

    Returns:
        tuple[datetime.date, datetime.date]: (開始日, 終了日) のタプル。
    """
    today = datetime.date.today()
    current_month = today.month
    # 現在の四半期の開始月を計算 (1, 4, 7, 10)
    quarter_start_month = 3 * ((current_month - 1) // 3) + 1
    current_quarter_start = datetime.date(today.year, quarter_start_month, 1)

    # 前の四半期の終了日 = 今期の開始日の前日
    end_date = current_quarter_start - datetime.timedelta(days=1)
    # 前の四半期の開始日 = 終了日の2ヶ月前
    start_date = end_date - relativedelta(months=2)
    start_date = start_date.replace(day=1)

    return start_date, end_date


# --- Notionブロック生成ヘルパー関数 ---


def create_heading_2(text: str) -> dict:
    """heading_2ブロックを作成します。

    Args:
        text (str): 見出しテキスト。

    Returns:
        dict: Notionブロックオブジェクト。
    """
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def create_heading_3(text: str) -> dict:
    """heading_3ブロックを作成します。

    Args:
        text (str): 見出しテキスト。

    Returns:
        dict: Notionブロックオブジェクト。
    """
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def create_bullet(text: str) -> dict:
    """bulleted_list_itemブロックを作成します。

    Args:
        text (str): リストアイテムのテキスト。

    Returns:
        dict: Notionブロックオブジェクト。
    """
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def format_calendar_blocks(events_by_cal: dict) -> list:
    """カレンダーごとの予定リストブロックを作成します。

    Args:
        events_by_cal (dict): カレンダーIDをキー、イベントリストを値とする辞書。

    Returns:
        list: Notionブロックオブジェクトのリスト。
    """
    # 合計件数を計算
    total_count = sum(len(events) for events in events_by_cal.values())

    # 大見出しに合計件数を表示
    blocks = [create_heading_2(f"📅 Googleカレンダー実績 (合計: {total_count}件)")]

    for cal_id, events in events_by_cal.items():
        count = len(events)
        # カレンダーIDごとの見出しに件数を追加
        blocks.append(create_heading_3(f"Calendar: {cal_id} ({count}件)"))
        if not events:
            blocks.append(create_bullet("(なし)"))
            continue

        # イベント列挙
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            summary = ev.get("summary", "タイトルなし")
            blocks.append(create_bullet(f"[{start}] {summary}"))

    return blocks


def format_task_blocks(tasks: list) -> list:
    """プロジェクトごとの完了タスクリストブロックを作成します。

    Notionのボードビューの代わりに、プロジェクト名を見出しとしたリスト形式で表現します。

    Args:
        tasks (list): Notionタスクオブジェクトのリスト。

    Returns:
        list: Notionブロックオブジェクトのリスト。
    """
    blocks = [create_heading_2("✅ 完了タスク実績 (プロジェクト別)")]

    # プロジェクトごとに分類
    tasks_by_project = defaultdict(list)
    for task in tasks:
        props = task.get("properties", {})
        project_obj = props.get("Project", {}).get("select") or props.get("プロジェクト", {}).get("select")
        project_name = project_obj["name"] if project_obj else "未分類"
        tasks_by_project[project_name].append(task)

    for project_name, task_list in tasks_by_project.items():
        blocks.append(create_heading_3(f"Project: {project_name}"))
        for task in task_list:
            props = task.get("properties", {})
            title_list = props.get("Name", {}).get("title", []) or props.get("タスク名", {}).get("title", [])
            title = title_list[0]["plain_text"] if title_list else "無題"
            blocks.append(create_bullet(title))

    return blocks


def format_ai_content_blocks(markdown_text: str) -> list:
    """Geminiの生成テキストをNotionブロックに変換します。

    Args:
        markdown_text (str): AIが生成したテキスト。

    Returns:
        list: Notionブロックオブジェクトのリスト。
    """
    blocks = [create_heading_2("🤖 四半期の振り返り (AI分析)")]

    # 長文対策として2000文字ごとに分割してParagraphブロックにする
    chunk_size = 2000
    for i in range(0, len(markdown_text), chunk_size):
        chunk = markdown_text[i : i + chunk_size]
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            }
        )
    return blocks


# --- Gemini関連処理 ---


def format_data_for_ai(tasks: list, events_by_cal: dict) -> str:
    """収集したタスクとイベントデータを、AIへのプロンプト用にテキスト整形します。

    Args:
        tasks (list): Notionから取得したタスクオブジェクト(辞書)のリスト。
        events_by_cal (dict): カレンダーごとのイベントリスト辞書。

    Returns:
        str: AIへの入力として利用する整形済みテキスト文字列。
    """
    text = "【完了タスク】\n"
    for task in tasks:
        props = task.get("properties", {})
        # タイトルの取得
        title_list = props.get("Name", {}).get("title", []) or props.get("タスク名", {}).get("title", [])
        title = title_list[0]["plain_text"] if title_list else "無題"

        # プロジェクトの取得
        project_obj = props.get("Project", {}).get("select") or props.get("プロジェクト", {}).get("select")
        project = project_obj["name"] if project_obj else "未分類"

        text += f"- {title} (Project: {project})\n"

    text += "\n【カレンダー予定】\n"
    for cal_id, events in events_by_cal.items():
        text += f"Source: {cal_id}\n"
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            summary = ev.get("summary", "タイトルなし")
            text += f"- [{start}] {summary}\n"
    return text


def generate_review(text_data: str, period_str: str) -> str:
    """Gemini APIを使用して、活動記録から振り返りレポートを生成します。

    Args:
        text_data (str): タスクとイベント情報を含む整形済みテキスト。
        period_str (str): 振り返り対象の期間を表す文字列。

    Returns:
        str | None: 生成された振り返りテキスト。エラー時はNoneを返す。
    """
    if not GOOGLE_API_KEY:
        print("Gemini API Key is missing.")
        return None

    client = genai.Client(api_key=GOOGLE_API_KEY)

    prompt = f"""
あなたは客観的なデータ分析官です。
以下のデータは、{period_str}の活動記録（完了タスクとカレンダーのイベント）です。
このデータを元に、四半期の活動報告レポートを作成してください。

## 指示
- **トーン&マナー:** 冷静、客観的、簡潔、ビジネスライク。感情的な表現やキャラクター性は不要です。事実を淡々と記述してください。
- **構成:** 以下の3つの観点で事実に基づいた分析を行ってください。
    1. **TRPG活動:** 実施回数、傾向、特筆すべきセッション。
    2. **サークル活動 (Luxy/T4):** 運営タスクの進捗、イベント実績。
    3. **全体総括:** その他プライベートや技術学習を含めた四半期の総評。

## 入力データ
{text_data}
    """
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return None


def main():
    """四半期ごとの振り返り生成プロセスのメイン実行関数。"""
    print("--- 四半期振り返り自動生成を開始します ---")

    start_date, end_date = get_target_quarter_range()
    period_str = f"{start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
    print(f"対象期間: {period_str}")

    # 1. Notion完了タスク取得
    done_tasks = []
    try:
        # TaskDBは初期化時にrelated_dbsを要求するため、ダミーを渡してエラーを回避
        dummy_db = DummyRelatedDB()
        tasks_db = TaskDB(
            db_id=NOTION_TASK_ID, token=NOTION_TOKEN, related_dbs={"Projects": dummy_db, "Sprints": dummy_db}
        )

        # DataFrameを使わず、直接APIを叩くメソッドを使用
        done_tasks = tasks_db.get_done_tasks(start_date.isoformat(), end_date.isoformat())
        print(f"Notion完了タスク: {len(done_tasks)}件取得")
    except Exception as e:
        print(f"TaskDB Init/Fetch Error: {e}")

    # 2. Googleカレンダーイベント取得
    events_by_cal = {}
    for cal_id in CALENDAR_IDS:
        cid = cal_id.strip()
        if not cid:
            continue
        try:
            gcal = GoogleCalendarAPI(key_file_path=SERVICE_ACCOUNT_FILE, calendar_id=cid)
            cal_events = gcal.list_events(start_date, end_date)
            events_by_cal[cid] = cal_events
            print(f"Calendar({cid}): {len(cal_events)}件")
        except Exception as e:
            print(f"Calendar({cid}) Skip: {e}")

    # 3. Gemini分析
    if not done_tasks and not events_by_cal:
        print("データが存在しないため終了します。")
        return

    input_text = format_data_for_ai(done_tasks, events_by_cal)
    print("Geminiによる分析を実行中...")
    ai_review_text = generate_review(input_text, period_str)

    if not ai_review_text:
        print("AI生成失敗のため終了")
        return

    print("\n--- 生成完了。Notionに書き込みます ---")

    # 4. Notionページ作成とブロック追加
    if NOTION_REVIEW_DB_ID:
        try:
            review_db = ReviewDB(db_id=NOTION_REVIEW_DB_ID, token=NOTION_TOKEN)

            # 4-1. まず空のページを作成 (タイトルのみ)
            new_page = review_db.create_review_page(title=f"{period_str} 振り返りレポート", content="")

            if not new_page:
                print("ページ作成に失敗しました")
                return

            page_id = new_page["id"]
            print(f"ページ作成成功 (ID: {page_id})。詳細ブロックを追加します...")

            # 4-2. ブロックリストの構築
            #  ① Googleカレンダー実績
            cal_blocks = format_calendar_blocks(events_by_cal)
            #  ② 完了タスク実績
            task_blocks = format_task_blocks(done_tasks)
            #  ③ AI振り返り
            ai_blocks = format_ai_content_blocks(ai_review_text)

            # 全ブロックを結合
            all_blocks = cal_blocks + task_blocks + ai_blocks

            # 4-3. ブロックを追加 (append_childrenを使用)
            review_db.append_children(page_id, all_blocks)
            print("✅ 全ブロックの追加が完了しました！")

        except Exception as e:
            print(f"Notion Write Error: {e}")
    else:
        print("DB ID未設定のためスキップ")


if __name__ == "__main__":
    main()
