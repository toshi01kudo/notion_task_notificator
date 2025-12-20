# module/notion_api.py

import requests
import logging
import datetime
import pandas as pd
from typing import List, Dict, Any, Optional, Union, Tuple


class BaseNotionDB:
    """
    Notion APIとの通信、生データの取得、共通ヘッダーを扱う基底クラス。

    Args:
        db_id (str): NotionデータベースID。
        token (str): Notionインテグレーションの認証トークン。
        version (str, optional): Notion APIのバージョン。デフォルトは "2022-06-28"。
    """

    def __init__(self, db_id: str, token: str, version: str = "2022-06-28") -> None:
        self.db_id = db_id
        self.token = token
        self.pd_items: pd.DataFrame = pd.DataFrame()  # 最終的に格納されるDataFrame
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": version,
        }
        self._load_and_process_data()

    def _get_raw_data(self) -> list:
        """
        Notionデータベースから生データを取得する。
        ページネーションに対応し、100件を超えるデータも全件取得する。

        Returns:
            list: APIレスポンスの 'results' に含まれる生のデータリスト（全件）。

        Raises:
            Exception: APIリクエストが失敗した場合。
        """
        task_url = f"https://api.notion.com/v1/databases/{self.db_id}/query"
        all_results = []
        has_more = True
        start_cursor = None

        while has_more:
            # ペイロード（リクエストボディ）の作成
            payload = {"page_size": 100}  # 最大値の100を指定
            if start_cursor:
                payload["start_cursor"] = start_cursor

            # リクエスト送信
            res = requests.post(task_url, headers=self.headers, json=payload)
            if res.status_code != 200:
                logging.error(f"Error getting DB {self.db_id}: {res.status_code}, message: {res.reason}")
                raise Exception(f"Notion API Error: {res.status_code}")

            data = res.json()
            results = data.get("results", [])
            all_results.extend(results)

            # 次のページがあるか確認
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        logging.info(f"Fetched {len(all_results)} items from DB {self.db_id}")
        return all_results

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

    # Notionページを更新
    def update_page(self, page_id: str, properties: Dict[str, Any]) -> None:
        """
        指定したページのプロパティを更新する。

        Args:
            page_id (str): 更新対象のNotionページID。
            properties (Dict[str, Any]): 更新するプロパティの内容 (API仕様に基づく辞書構造)。

        Raises:
            Exception: 更新リクエストが失敗した場合。
        """
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"properties": properties}

        res = requests.patch(update_url, headers=self.headers, json=payload)
        if res.status_code != 200:
            logging.error(f"Failed to update page {page_id}: {res.status_code} {res.text}")
            raise Exception(f"Notion Update Error: {res.status_code}")
        logging.info(f"Updated Notion Page: {page_id}")

    def query(self, filter_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """条件を指定してデータベースを検索し、結果を取得します。

        requestsライブラリを使用して直接APIを叩きます。

        Args:
            filter_payload (Dict[str, Any]): Notion APIのフィルターオブジェクト。
                例: {"property": "Status", "status": {"equals": "Done"}}

        Returns:
            List[Dict[str, Any]]: 取得したページのリスト（辞書形式）。
            エラー時は空リストを返し、ログにエラーを出力します。
        """
        url = f"https://api.notion.com/v1/databases/{self.db_id}/query"
        payload = {"filter": filter_payload} if filter_payload else {}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json().get("results", [])
        except requests.exceptions.RequestException as e:
            logging.error(f"Notion API query error: {e}")
            return []

    def create_page(
        self, properties: Dict[str, Any], children: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """このデータベース(親)配下に新規ページを作成します。

        Args:
            properties (Dict[str, Any]): ページのプロパティ（タイトルなど）。
            children (Optional[List[Dict[str, Any]]]): ページ内のブロックコンテンツ。

        Returns:
            Optional[Dict[str, Any]]: 作成されたページオブジェクト。失敗時はNone。
        """
        url = "https://api.notion.com/v1/pages"

        body = {"parent": {"database_id": self.db_id}, "properties": properties}
        if children:
            body["children"] = children

        try:
            response = requests.post(url, headers=self.headers, json=body)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Notion create page error: {e}")
            return None

    def append_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        """指定したブロック（ページ）の子要素としてブロックを追加します。

        Notion APIの制限（1回あたり100ブロック）を考慮し、分割して送信します。

        Args:
            block_id (str): 追加先のブロックIDまたはページID。
            children (List[Dict[str, Any]]): 追加するブロックオブジェクトのリスト。

        Returns:
            Dict[str, Any]: 最後のバッチ処理のレスポンスJSON。エラー時は例外を送出します。

        Raises:
            requests.exceptions.RequestException: APIリクエストが失敗した場合。
        """
        url = f"https://api.notion.com/v1/blocks/{block_id}/children"

        batch_size = 100
        last_response = {}

        for i in range(0, len(children), batch_size):
            batch = children[i: i + batch_size]
            payload = {"children": batch}

            try:
                # Notion APIでは既存ブロックへの子ブロック追加は
                # /v1/blocks/{block_id}/children に対する PATCH で行う
                # （新規ページ作成は /v1/pages への POST を使用）
                response = requests.patch(url, headers=self.headers, json=payload)
                response.raise_for_status()
                last_response = response.json()
                logging.info(f"Appended blocks batch {i//batch_size + 1}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Append children error at batch {i}: {e}")
                raise e

        return last_response


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
        if not raw_items:
            return []

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

    def __init__(
        self, db_id: str, token: str, related_dbs: Dict[str, "RelatedDB"], version: str = "2022-06-28"
    ) -> None:
        self.related_dbs = related_dbs
        super().__init__(db_id, token, version)

    def _date_string_to_date(self, date_string: str) -> datetime.date:
        """
        日付文字列を datetime.date オブジェクトに変換するヘルパー関数。

        Args:
            date_string: NotionのISO 8601形式の日付文字列 (例: "2025-12-31" or "2025-12-31T09:00:00.000+09:00")

        Returns:
            datetime.date: 変換された日付オブジェクト。
        """
        # タイムスタンプ部分を無視し、日付部分のみを取得してパース
        return datetime.datetime.strptime(date_string.split("T")[0], "%Y-%m-%d").date()

    def _parse_date_property(
        self, date_prop: Optional[Dict[str, Any]], field: str = "start", return_range: bool = False
    ) -> Union[Optional[datetime.date], Tuple[Optional[datetime.date], Optional[datetime.date]]]:
        """
        Notionの日付プロパティを解析し、指定されたフィールドまたは日付範囲を返す汎用関数。

        Args:
            date_prop: Notionのdateプロパティの辞書 ({"start": ..., "end": ...})。
            field: 取得したい日付フィールド ("start" または "end")。
            return_range: Trueの場合、(開始日, 終了日) のタプルを返す。Falseの場合、fieldで指定された単一の日付を返す。

        Returns:
            datetime.date or tuple:
                - return_range=False: 指定されたフィールドの日付 (Optional[datetime.date])
                - return_range=True: (開始日, 終了日) のタプル (tuple[Optional[datetime.date], Optional[datetime.date]])
        """
        if date_prop is None:
            if return_range:
                return None, None
            return None

        start_date = None
        end_date = None

        if date_prop.get("start") is not None:
            start_date = self._date_string_to_date(date_prop["start"])

        if return_range:
            # 日付範囲が必要な場合
            if date_prop.get("end") is not None:
                end_date = self._date_string_to_date(date_prop["end"])
            return start_date, end_date

        else:
            # 単一の日付が必要な場合
            if field == "start":
                return start_date
            elif field == "end" and date_prop.get("end") is not None:
                return self._date_string_to_date(date_prop["end"])

            return None  # 指定されたフィールドがない、またはendでendが空の場合

    def _process_raw_to_dict(self, raw_tasks: list) -> List[Dict[str, Any]]:
        """
        生のAPIタスクデータを整形された辞書形式に変換する（タスクDB特化）。
        """
        tasks = []
        Projects: "RelatedDB" = self.related_dbs["Projects"]
        Sprints: "RelatedDB" = self.related_dbs["Sprints"]

        for raw_task in raw_tasks:
            task_name = "N/A"
            try:
                task_name = raw_task["properties"]["タスク名"]["title"][0]["plain_text"]

                # プロジェクト名
                pj_relation = raw_task["properties"]["プロジェクト"]["relation"]
                pj_name = ""
                if len(pj_relation) > 0:
                    pj_id = pj_relation[0]["id"]
                    pj_name = Projects.get_item_from_pd("id", pj_id, "title")

                # スプリント名解決
                sprint_relation = raw_task["properties"]["スプリント"]["relation"]
                sprint_name = None
                if len(sprint_relation) > 0:
                    sprint_id = sprint_relation[0]["id"]
                    sprint_name = Sprints.get_item_from_pd("id", sprint_id, "title")
                else:
                    logging.warning(f"{task_name}: Sprint is missing.")

                # 期限日の処理 (日付範囲として取得)
                start_date, end_date = self._parse_date_property(
                    raw_task["properties"]["期限"]["date"], return_range=True
                )

                # ステータス
                status = raw_task["properties"]["ステータス"]["status"]["name"]

                # タグ
                tag_select = raw_task["properties"]["タグ"]["multi_select"]
                tag = tag_select[0]["name"] if len(tag_select) > 0 else "その他"
                if len(tag_select) == 0:
                    logging.warning(f"{task_name}: Tag is missing. Defaulting to 'その他'.")

                # IDと最終更新日時
                task_id = raw_task["id"]
                last_edited = raw_task["last_edited_time"]

                # 作業日の処理 (開始日のみ取得)
                work_date = self._parse_date_property(
                    raw_task["properties"]["作業日"]["date"], field="start", return_range=False
                )

                # GCal Event ID
                gcal_id_prop = raw_task["properties"].get("GCal_Event_ID", {}).get("rich_text", [])
                gcal_event_id = gcal_id_prop[0]["plain_text"] if gcal_id_prop else None

                task = {
                    "title": task_name,
                    "status": status,
                    "project": pj_name,
                    "start": start_date,
                    "end": end_date,
                    "work_date": work_date,
                    "sprint": sprint_name,
                    "tag": tag,
                    "id": task_id,
                    "gcal_event_id": gcal_event_id,
                    "last_edited_time": last_edited,
                }
                tasks.append(task)
            except Exception as e:
                logging.error(f"タスク変換エラー ({raw_task.get('id', 'N/A')}, Name: {task_name}): {e}")
                continue
        return tasks

    def get_done_tasks(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """指定期間内に完了したタスクを取得します。

        Args:
            start_date (str): 期間開始日 (ISO 8601形式: YYYY-MM-DD)。
            end_date (str): 期間終了日 (ISO 8601形式: YYYY-MM-DD)。

        Returns:
            List[Dict[str, Any]]: 検索条件に合致したタスクページのリスト。
        """
        # ※プロパティ名は既存のCSV設定に合わせて「ステータス」「作業日」としています
        filter_condition = {
            "and": [
                {"property": "ステータス", "status": {"equals": "完了"}},
                {"property": "作業日", "date": {"on_or_after": start_date}},
                {"property": "作業日", "date": {"on_or_before": end_date}},
            ]
        }
        return self.query(filter_condition)


class ReviewDB(BaseNotionDB):
    """振り返りページ保存用のデータベースクラス。BaseNotionDBを継承。"""

    def _load_and_process_data(self) -> None:
        """データロード処理のオーバーライド。

        書き込み専用のため、初期化時の全件取得処理（重い処理）をスキップします。
        """
        pass

    def create_review_page(self, title: str, content: str) -> Optional[Dict[str, Any]]:
        """タイトルと本文を指定して振り返りページを作成します。

        Args:
            title (str): ページのタイトル（期間など）。
            content (str): 本文（Geminiなどの生成結果）。

        Returns:
            Optional[Dict[str, Any]]: 作成されたページオブジェクト。失敗時はNone。
        """
        # 長文対策（Notion APIのブロック制限対策として簡易的にカット）
        truncated_content = content[:2000]

        properties = {"Name": {"title": [{"text": {"content": title}}]}}  # ※振り返りDBのタイトル列名に合わせてください

        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": truncated_content}}]},
            }
        ]

        return self.create_page(properties, children)
