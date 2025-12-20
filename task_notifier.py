# task_notifier.py

import logging
import os
from dotenv import load_dotenv

from module.notion_api import RelatedDB, TaskDB
from module.line_notifier import send_line_messageapi
from module.util import sort_filter, make_sentence

load_dotenv()

# Main ---


def main() -> None:
    """
    タスク通知システムのメイン実行関数。

    Notionのタスク、プロジェクト、スプリントDBからデータを取得し、
    期限が近いまたは過ぎたアクティブなタスクをフィルタリング・整形して、
    LINEに通知する。
    """
    # Logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("#=== Start program ===#")

    try:
        # 1. 関連DBのインスタンス化とデータ取得 (初期化時にAPIアクセスとDataFrame生成を行う)
        logging.info("Initializing Related Databases (Projects & Sprints)...")
        token = os.getenv("NOTION_TOKEN")

        Projects = RelatedDB(os.getenv("NOTION_PJ_ID"), token)
        Sprints = RelatedDB(os.getenv("NOTION_SPRINT_ID"), token)

        # 2. タスクDBのインスタンス化とデータ取得
        logging.info("Initializing Task Database...")
        Tasks = TaskDB(
            db_id=os.getenv("NOTION_TASK_ID"), token=token, related_dbs={"Projects": Projects, "Sprints": Sprints}
        )

        # 3. フィルタリングとソート
        pd_hot_tasks = sort_filter(Tasks.pd_items, Projects, Sprints)

        if pd_hot_tasks.empty:
            logging.info("No hot tasks found for notification.")
        else:
            # 4. 通知文章の作成
            sentence_list = make_sentence(pd_hot_tasks)

            # 5. LINEに通知
            logging.info(f"Sending {len(sentence_list)} notification message(s) to LINE.")
            for sentence in sentence_list:
                send_line_messageapi(sentence)

    except Exception as e:
        logging.error(f"An unexpected error occurred in main execution: {e}", exc_info=True)

    logging.info("#=== Finish program ===#")


if __name__ == "__main__":
    main()
