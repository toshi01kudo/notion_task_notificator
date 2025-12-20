# sync_main.py

import logging
import os
import datetime
import dateutil.parser
from dotenv import load_dotenv

from module.notion_api import RelatedDB, TaskDB
from module.google_cal_api import GoogleCalendarAPI

load_dotenv()

# 設定
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
G_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
# 環境変数からキーファイルパスを取得（デフォルトは同階層のservice_account.json）
G_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")


def main() -> None:
    """
    NotionとGoogleカレンダーの同期を実行するメイン関数。

    NotionのタスクDBから全件を取得し、Googleカレンダーの状態と比較して
    必要な作成・更新処理を行う。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("#=== Start Synchronization ===#")

    # 必須変数のチェック
    if not G_CALENDAR_ID:
        logging.error("Error: GOOGLE_CALENDAR_ID is not set in .env")
        return
    if not os.path.exists(G_SERVICE_ACCOUNT_FILE):
        logging.error(f"Error: Service account key file not found at: {G_SERVICE_ACCOUNT_FILE}")
        return

    try:
        # 1. APIクライアントの初期化
        gcal = GoogleCalendarAPI(G_SERVICE_ACCOUNT_FILE, G_CALENDAR_ID)

        projects_db = RelatedDB(os.getenv("NOTION_PJ_ID"), NOTION_TOKEN)
        sprints_db = RelatedDB(os.getenv("NOTION_SPRINT_ID"), NOTION_TOKEN)

        tasks_db = TaskDB(os.getenv("NOTION_TASK_ID"), NOTION_TOKEN, {"Projects": projects_db, "Sprints": sprints_db})

        # 2. 同期処理の実行
        if not tasks_db.pd_items.empty:
            for row in tasks_db.pd_items.itertuples():
                process_sync_row(row, tasks_db, gcal)
        else:
            logging.info("No tasks found in Notion DB.")

    except Exception as e:
        logging.error(f"Sync execution failed: {e}", exc_info=True)

    logging.info("#=== Finish Synchronization ===#")


def process_sync_row(row: object, tasks_db: TaskDB, gcal: GoogleCalendarAPI) -> None:
    """
    単一のタスク行に対して同期ロジックを適用する。

    同期ルール:
    1. Notionの「作業日」がない、またはStatusが「保留中」の場合 -> GCalタイトルを【中止】にする。
    2. 新規タスクの場合 -> GCalイベントを作成し、NotionにIDを書き込む。
    3. 既存タスクの場合 ->
        - タイトルと日付が完全一致すれば何もしない。
        - 最終更新日時(Last Edited)を比較し、新しい方の情報を他方に上書きする。

    Args:
        row (object): Pandasのitertuples()で取得したタスク行オブジェクト。
        tasks_db (TaskDB): NotionタスクDB操作用インスタンス。
        gcal (GoogleCalendarAPI): Googleカレンダー操作用インスタンス。
    """
    # 必要な情報の取り出し
    task_id = row.id
    task_title = row.title
    work_date: datetime.date = row.work_date
    status = row.status
    gcal_event_id = row.gcal_event_id
    notion_last_edited = dateutil.parser.isoparse(row.last_edited_time)

    # プロジェクト名をタイトルに付与する場合
    display_title = f"{task_title}【{row.project}】" if row.project else task_title

    # --- Case A: 中止/保留の判定 ---
    is_canceled = (work_date is None) or (status == "保留中")

    if is_canceled:
        target_title = f"【中止】{display_title}"
    else:
        target_title = display_title

    # --- Case B: NotionにGCal IDがない場合 (新規作成) ---
    if not gcal_event_id:
        if is_canceled:
            return  # 作業日がない、または保留中の新規タスクはGCalに作らない

        try:
            new_event_id = gcal.create_event(target_title, work_date)
            # NotionにIDを書き戻す
            tasks_db.update_page(task_id, {"GCal_Event_ID": {"rich_text": [{"text": {"content": new_event_id}}]}})
        except Exception as e:
            logging.error(f"Failed to create event for {task_title}: {e}")
        return

    # --- Case C: GCal IDがある場合 (同期チェック) ---
    gcal_event = gcal.get_event(gcal_event_id)

    if not gcal_event:
        logging.warning(f"Event not found in GCal (ID: {gcal_event_id}). Skipping.")
        return

    # GCal情報の取得
    gcal_title = gcal_event.get("summary", "")
    gcal_start_str = gcal_event.get("start", {}).get("date")  # 終日イベント前提
    gcal_updated_str = gcal_event.get("updated")

    if gcal_updated_str:
        gcal_updated = dateutil.parser.isoparse(gcal_updated_str)
    else:
        gcal_updated = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    # GCalの日付パース
    gcal_date = None
    if gcal_start_str:
        gcal_date = datetime.datetime.strptime(gcal_start_str, "%Y-%m-%d").date()

    # --- 比較ロジック ---

    # 1. 完全一致なら何もしない
    if gcal_title == target_title and gcal_date == work_date:
        return  # 同期済み

    logging.info(f"Conflict detected for '{task_title}'. Syncing...")

    # 2. 中止条件に合致する場合 (強制更新)
    if is_canceled:
        # 日付は既存のGCalの日付を維持（なければ今日）
        update_date = gcal_date if gcal_date else datetime.date.today()

        if not gcal_title.startswith("【中止】") or gcal_title != target_title:
            gcal.update_event(gcal_event_id, target_title, update_date)
        return

    # 3. 通常更新 (更新日時比較)
    # Notionの方が新しい -> GCalを更新
    if notion_last_edited > gcal_updated:
        gcal.update_event(gcal_event_id, target_title, work_date)

    # GCalの方が新しい -> Notionを更新
    elif gcal_updated > notion_last_edited:
        # GCalで日付が変更されていた場合、Notionに反映
        if gcal_date and gcal_date != work_date:
            tasks_db.update_page(task_id, {"作業日": {"date": {"start": gcal_date.isoformat()}}})
        else:
            logging.info("GCal is newer but date is same. Updating title only in GCal (prefer Notion title structure).")
            gcal.update_event(gcal_event_id, target_title, work_date)


if __name__ == "__main__":
    main()
