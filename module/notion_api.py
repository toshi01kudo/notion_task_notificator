# module/notion_api.py

import requests
import logging
import json
import datetime
import pandas as pd
from typing import List, Dict, Any, Optional

class BaseNotionDB:
    """
    Notion APIとの通信、生データの取得、共通ヘッダーを扱う基底クラス。

    Args:
        db_id: NotionデータベースID。
        token: Notionインテグレーションの認証トークン。
        version: Notion APIのバージョン。デフォルトは "2022-06-28"。
    """
    def __init__(self, db_id: str, token: str, version: str = "2022-06-28") -> None:
        self.db_id = db_id
        self.token = token
        self.pd_items: pd.DataFrame = pd.DataFrame()  # 最終的に格納されるDataFrame
        self.headers = {
            "Authorization": f'Bearer {token}',
            "Content-Type": "application/json",
            "Notion-Version": version,
        }
        self._load_and_process_data()

    def _get_raw_data(self) -> list:
        """
        Notionデータベースから生データを取得する。

        Returns:
            list: APIレスポンスの 'results' に含まれる生のデータリスト。

        Raises:
            Exception: APIリクエストが失敗した場合。
        """
        task_url = f"https://api.notion.com/v1/databases/{self.db_id}/query"
        res = requests.post(task_url, headers=self.headers)
        if res.status_code == 200:
            return json.loads(res.text)["results"]
        else:
            logging.error(f"Error getting DB {self.db_id}: {res.status_code}, message: {res.reason}")
            raise Exception(f"Notion API Error: {res.status_code}")

    def _process_raw_to_dict(self, raw_items: list) -> List[Dict[str, Any]]:
        """
        生データをシンプルな辞書リストに変換する抽象メソッド。

        Note:
            子クラスでDBのプロパティ構造に合わせて実装必須。

        Args:
            raw_items: APIから取得した生のデータリスト。
        
        Raises:
            NotImplementedError: 子クラスでの実装がない場合。
        """
        raise NotImplementedError("Subclasses must implement _process_raw_to_dict()")

    def _load_and_process_data(self) -> None:
        """生データを取得し、整形メソッドを呼び出してpd_itemsに格納する。"""
        try:
            raw_items = self._get_raw_data()
            items_dict = self._process_raw_to_dict(raw_items)
            self.pd_items = pd.json_normalize(items_dict)
        except Exception as e:
            logging.error(f"Failed to load or process data for DB {self.db_id}: {e}")

    def get_item_from_pd(self, in_cul: str, in_value: str, out_cul: str) -> str:
        """
        DataFrameから指定条件で単一アイテムの値を取得する。

        Args:
            in_cul: フィルタリングに使用するカラム名。
            in_value: in_culで探す値。
            out_cul: 取得したい値が格納されているカラム名。

        Returns:
            str: フィルタリングされた結果のout_culの値。

        Raises:
            ValueError: 指定されたカラムがDataFrameに存在しない場合。
            LookupError: 指定されたin_valueを持つ行が見つからない場合。
        """
        if in_cul not in self.pd_items.columns.values or out_cul not in self.pd_items.columns.values:
            logging.error(f"Error: Columns missing: {in_cul} or {out_cul}")
            raise ValueError("指定されたカラムがDataFrameに存在しません。")
        try:
            return self.pd_items[self.pd_items[in_cul] == in_value][out_cul].iat[0]
        except IndexError:
            logging.error(f"Error: Value not found for {in_cul}='{in_value}' in DB {self.db_id}")
            raise LookupError(f"値が見つかりません: {in_value}")


class RelatedDB(BaseNotionDB):
    """
    プロジェクトやスプリントなど、シンプルな構造の関連DBクラス。
    """
    def _process_raw_to_dict(self, raw_items: list) -> List[Dict[str, Any]]:
        """
        生のAPIデータをシンプルな辞書形式に変換する（関連DB特化）。

        Args:
            raw_items: APIから取得した生のデータリスト。

        Returns:
            list: 整形された辞書リスト (title, id, statusを含む)。
        """
        items = []
        if not raw_items: return []

        # DBの種別に応じて要素名を動的に判定
        prop_keys = raw_items[0]["properties"].keys()
        elem_name = None
        if "プロジェクト名" in prop_keys:
            elem_name = "プロジェクト名"
        elif "スプリント名" in prop_keys:
            elem_name = "スプリント名"

        if elem_name is None:
            logging.warning(f"関連DB {self.db_id} のタイトルプロパティが見つかりませんでした。")
            return []

        for raw_item in raw_items:
            try:
                item = {
                    "title": raw_item["properties"][elem_name]["title"][0]["plain_text"],
                    "id": raw_item["id"],
                    "status": raw_item["properties"]["ステータス"]["status"]["id"],
                }
                items.append(item)
            except Exception as e:
                logging.error(f"関連DBデータ変換エラー for item {raw_item.get('id', 'N/A')}: {e}")
        return items


class TaskDB(BaseNotionDB):
    """
    タスクDBに特化したクラス。リレーションシップの解決も行う。

    Args:
        db_id: NotionデータベースID。
        token: Notionインテグレーションの認証トークン。
        related_dbs: 関連する RelatedDB インスタンスをキーにDB名を持つ辞書。
        version: Notion APIのバージョン。
    """
    def __init__(self, db_id: str, token: str, related_dbs: Dict[str, RelatedDB], version: str = "2022-06-28") -> None:
        self.related_dbs = related_dbs
        super().__init__(db_id, token, version)

    def _parse_date_property(self, date_prop: Optional[Dict[str, Any]]) -> tuple[Optional[datetime.date], Optional[datetime.date]]:
        """
        日付プロパティ（期限）を datetime.date に変換するヘルパー関数。

        Args:
            date_prop: Notionのdateプロパティの辞書。

        Returns:
            tuple: (開始日, 終了日) のタプル。日付がない場合は None。
        """
        start_date = None
        end_date = None
        if date_prop is not None:
            # 日付部分のみを取得（タイムスタンプを無視）
            if date_prop.get("start") is not None:
                start_time = datetime.datetime.strptime(date_prop["start"].split("T")[0], "%Y-%m-%d")
                start_date = start_time.date()
            if date_prop.get("end") is not None:
                end_time = datetime.datetime.strptime(date_prop["end"].split("T")[0], "%Y-%m-%d")
                end_date = end_time.date()
        return start_date, end_date

    def _process_raw_to_dict(self, raw_tasks: list) -> List[Dict[str, Any]]:
        """
        生のAPIタスクデータを整形された辞書形式に変換する（タスクDB特化）。
        リレーションシップ（プロジェクト、スプリント）を解決する。

        Args:
            raw_tasks: APIから取得した生のタスクデータリスト。

        Returns:
            list: 整形されたタスクの辞書リスト (title, status, project, sprint, start, end, tagを含む)。
        """
        tasks = []
        Projects: RelatedDB = self.related_dbs["Projects"]
        Sprints: RelatedDB = self.related_dbs["Sprints"]

        for raw_task in raw_tasks:
            try:
                task_name = raw_task["properties"]["タスク名"]["title"][0]["plain_text"]

                # プロジェクト名 (リレーション解決)
                pj_id = raw_task["properties"]["プロジェクト"]["relation"][0]["id"]
                pj_name = Projects.get_item_from_pd("id", pj_id, "title")

                # スプリント名 (リレーション解決)
                sprint_relation = raw_task["properties"]["スプリント"]["relation"]
                sprint_name = None
                if len(sprint_relation) > 0:
                    sprint_id = sprint_relation[0]["id"]
                    sprint_name = Sprints.get_item_from_pd("id", sprint_id, "title")
                else:
                    logging.warning(f"{task_name}: Sprint is missing.")

                # 期限日の処理
                start_date, end_date = self._parse_date_property(raw_task["properties"]["期限"]["date"])

                # タグ
                tag_select = raw_task["properties"]["タグ"]["multi_select"]
                tag = tag_select[0]["name"] if len(tag_select) > 0 else "その他"
                if len(tag_select) == 0:
                     logging.warning(f"{task_name}: Tag is missing. Defaulting to 'その他'.")

                task = {
                    "title": task_name,
                    "status": raw_task["properties"]["ステータス"]["status"]["name"],
                    "project": pj_name,
                    "start": start_date,
                    "end": end_date,
                    "sprint": sprint_name,
                    "tag": tag,
                }
                tasks.append(task)
            except Exception as e:
                logging.error(f"タスク変換エラー ({raw_task.get('id', 'N/A')}, Name: {task_name if 'task_name' in locals() else 'N/A'}): {e}")
                continue
        return tasks
