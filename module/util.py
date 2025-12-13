# module/util.py

import logging
import pandas as pd
import datetime
from typing import List, TYPE_CHECKING, Optional

# RelatedDB クラスを型ヒントとしてのみインポートするための記述
# 実行時の循環参照を防ぎ、静的解析ツールでの型チェックを可能にする
if TYPE_CHECKING:
    from .notion_api import RelatedDB
else:
    # 実行時に参照する際はダミーまたは実行可能オブジェクトを定義
    class RelatedDB:
        """実行時のダミー定義。実際には notion_api.py からインポートされる。"""
        def get_item_from_pd(self, in_cul: str, in_value: str, out_cul: str) -> str:
            raise NotImplementedError("This is a placeholder class.")


def sort_filter(pd_tasks: pd.DataFrame, Projects: 'RelatedDB', Sprints: 'RelatedDB') -> pd.DataFrame:
    """
    通知前にタスクをフィルタリング・ソートする。

    フィルタリング条件:
        - 終了日が設定されている
        - スプリントが設定されている
        - 現在進行中のスプリントに属している
        - 期限が明日まで、または開始日が今日以前である
        - ステータスが「未着手」「進行中」「反応待ち」のいずれかである

    Args:
        pd_tasks: タスクの全データを含むDataFrame。
        Projects: プロジェクトDBの RelatedDB インスタンス。
        Sprints: スプリントDBの RelatedDB インスタンス。

    Returns:
        pd.DataFrame: フィルタリングおよびソートされたタスクのDataFrame。
    """
    # Fliter: 必須項目が欠けているタスクを除外
    active_tasks = pd_tasks[(pd_tasks["end"].notnull()) & (pd_tasks["sprint"].notnull())]

    # 現在のスプリント名を取得
    try:
        current_sprint = Sprints.get_item_from_pd("status", "current", "title")
    except LookupError:
        logging.warning("現在のスプリント(status='current')が見つかりませんでした。タスク通知を行いません。")
        return pd.DataFrame()

    today = datetime.date.today()
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)

    # フィルタリング条件
    is_due_soon = active_tasks["end"] <= tomorrow  # 期限が明日以前
    is_overdue = active_tasks["start"] <= today    # 開始日が今日以前

    hot_tasks = active_tasks[
        (is_due_soon | is_overdue)
        & (active_tasks["sprint"] == current_sprint)
        & (
            (active_tasks["status"] == "未着手")
            | (active_tasks["status"] == "進行中")
            | (active_tasks["status"] == "反応待ち")
        )
    ]

    # Sort: プロジェクト名 -> タグの順でソート
    return hot_tasks.sort_values(["project", "tag"])


def make_sentence(pd_tasks: pd.DataFrame) -> List[str]:
    """
    通知する文章を作成する関数。

    タスクのタグごとにメッセージを区切り、プロジェクトごとにグループ化する。

    Args:
        pd_tasks: フィルタリングおよびソートされたタスクのDataFrame。

    Returns:
        List[str]: 通知用の文章（タグごとに分割されたリスト）。
    """
    sentence_list = []

    if pd_tasks.empty:
        sentence_list.append(f"{datetime.date.today().strftime('%Y-%m-%d')}\n通知対象のタスクはありませんでした。")
        return sentence_list

    # 最初の行に日付を含める
    sentence = datetime.date.today().strftime("%Y-%m-%d") + "\n"
    saved_tag = ""
    saved_pj = ""

    # タグとプロジェクトを基準に文章を作成
    for row in pd_tasks.itertuples():
        if saved_tag != row.tag:
            # タグが変わった場合、前の文章をリストに追加
            if saved_tag != "":
                sentence_list.append(sentence)

            # 新しいタグで文章をリセット
            sentence = "■■" + row.tag + "■■\n"
            saved_tag = row.tag
            saved_pj = ""

        if saved_pj != row.project:
            saved_pj = row.project
            sentence += f"【{row.project}】\n"

        # タスク詳細（タイトル、ステータス、期限）
        end_date_str = row.end.strftime('%Y-%m-%d') if pd.notna(row.end) else '期限なし'
        sentence += f" - [{row.status}] {row.title} (期限: {end_date_str})\n"

    # 最後に残った文章をリストに追加
    sentence_list.append(sentence)

    return sentence_list
