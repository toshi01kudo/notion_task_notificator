# module/util.py

import logging
import pandas as pd
import datetime
from typing import List, TYPE_CHECKING

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


def sort_filter(pd_tasks: pd.DataFrame, Projects: "RelatedDB", Sprints: "RelatedDB") -> pd.DataFrame:
    """
    通知前にタスクをフィルタリング・ソートする。

    フィルタリング条件:
        1. 必須条件:
           - スプリントが設定されていること
           - 「期限(start)」または「作業日(work_date)」のいずれかが設定されていること
             (※単一日付設定の場合、startに日付が入るためこちらをチェックする)
        2. 抽出条件 (いずれかに合致):
           - 期限(end)が設定されており、明日まで (is_due_soon)
           - 開始日(start)が設定されており、今日以前 (is_overdue)
           - 作業日(work_date)が設定されており、今日 (is_work_today)
        3. ステータス条件:
           - 「未着手」「進行中」「反応待ち」のいずれか

    Args:
        pd_tasks: タスクの全データを含むDataFrame。
        Projects: プロジェクトDBの RelatedDB インスタンス。
        Sprints: スプリントDBの RelatedDB インスタンス。

    Returns:
        pd.DataFrame: フィルタリングおよびソートされたタスクのDataFrame。
    """
    # 1. Pre-Filter: スプリントがあり、かつ「期限(start) または 作業日」が設定されているタスクのみ残す
    # 修正: end ではなく start の有無を確認するように変更
    active_tasks = pd_tasks[
        (pd_tasks["sprint"].notnull()) & ((pd_tasks["start"].notnull()) | (pd_tasks["work_date"].notnull()))
    ]

    # 現在のスプリント名を取得
    try:
        current_sprint = Sprints.get_item_from_pd("status", "current", "title")
    except LookupError:
        logging.warning("現在のスプリント(status='current')が見つかりませんでした。タスク通知を行いません。")
        return pd.DataFrame()

    today = datetime.date.today()
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)

    # 2. Filtering Logic (Hot判定)

    # A: 期限(終了日)があり、明日まで
    is_due_soon = (active_tasks["end"].notnull()) & (active_tasks["end"] <= tomorrow)

    # B: 開始日があり、今日以前 (単一日付の期限切れもここで拾う)
    is_overdue = (active_tasks["start"].notnull()) & (active_tasks["start"] <= today)

    # C: 作業日があり、今日
    is_work_today = (active_tasks["work_date"].notnull()) & (active_tasks["work_date"] == today)

    # フィルタ適用
    hot_tasks = active_tasks[
        (is_due_soon | is_overdue | is_work_today)  # A or B or C
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

        # 日付情報の表示ロジック
        # 1. 終了日(end)があればそれを表示
        # 2. なければ開始日(start)を表示
        # 3. それもなければ作業日(work_date)を表示
        if pd.notna(row.end):
            date_info = f"期限: {row.end.strftime('%Y-%m-%d')}"
        elif pd.notna(row.start):
            date_info = f"期限: {row.start.strftime('%Y-%m-%d')}"
        elif pd.notna(row.work_date):
            date_info = f"作業日: {row.work_date.strftime('%Y-%m-%d')}"
        else:
            date_info = "日付未定"

        sentence += f" - [{row.status}] {row.title} ({date_info})\n"

    # 最後に残った文章をリストに追加
    sentence_list.append(sentence)

    return sentence_list
