import requests
import logging
import datetime
import os
import json
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Main ---


def main() -> None:
    """
    Task notification system.
    Tasks must be resistered on Notion.
    This is main function to be executed.
    """
    # Logging
    logging.basicConfig(level=logging.INFO, format=" %(asctime)s - %(levelname)s - %(message)s")
    logging.info("#=== Start program ===#")

    # Get DB from Notion
    raw_tasks = get_notion_db(os.getenv("NOTION_TASK_ID"))
    raw_projects = get_notion_db(os.getenv("NOTION_PJ_ID"))
    raw_sprints = get_notion_db(os.getenv("NOTION_SPRINT_ID"))

    # Pandas class for projects & sprints
    Projects = RelatedDb(raw_projects)
    Sprints = RelatedDb(raw_sprints)

    # Tasks
    tasks = change_raw_task_to_dict(raw_tasks, Projects, Sprints)
    pd_tasks = pd.json_normalize(tasks)
    pd_hot_tasks = sort_filter(pd_tasks, Projects, Sprints)

    # Make sentense to be noted.
    sentense_list = make_sentense(pd_hot_tasks)

    # Notificate to LINE. Post to be separated with tag.
    for sentense in sentense_list:
        send_line_masageapi(sentense)

    logging.info("#=== Finish program ===#")


# Class ---


class RelatedDb:
    """
    Class for related DB, such as, projects and sprints
    If generic class functions cannot handle any specific case, please make specific child class.
    """

    def __init__(self, raw_items: list) -> None:
        """
        initial process
        Args:
            raw_items (list): raw API data from Notion.
        """
        # init process
        self.pd_items = self._change_dict_to_pandas(self._change_raw_to_dict(raw_items))

    def _change_raw_to_dict(self, raw_items: list) -> list:
        """
        Convert raw API data to simple dict format.
        Args:
            raw_items (list): raw API data from Notion.
        Returns:
            dict in list
        """
        items = []
        if "プロジェクト名" in raw_items[0]["properties"].keys():
            elem_name = "プロジェクト名"
        elif "スプリント名" in raw_items[0]["properties"].keys():
            elem_name = "スプリント名"
        else:
            elem_name = ""
        for raw_item in raw_items:
            item = {
                "title": raw_item["properties"][elem_name]["title"][0]["plain_text"],
                "id": raw_item["id"],
                "status": raw_item["properties"]["ステータス"]["status"]["id"],
            }
            items.append(item)
        return items

    def _change_dict_to_pandas(self, items_dict: list) -> pd.DataFrame:
        """
        Change dict to pandas.
        `_change_raw_to_dict` should be used first.
        Args:
            items_dict (list): dict data in list.
        """
        pd_items = pd.json_normalize(items_dict)
        return pd_items

    def get_item_from_pd(self, in_cul: str, in_value: str, out_cul: str) -> str:
        """
        get item from pandas DataFrame.
        Args:
            in_cul (str): filtering column name.
            in_value (str): filtering value in `in_cul`.
            out_cul (str): output value filtered by in_cul and in_value.
        """
        if in_cul not in self.pd_items.columns.values or out_cul not in self.pd_items.columns.values:
            logging.error(f"Error: in_cul and out_cul should be in columns: {in_cul} or {out_cul}")
            raise Exception
        try:
            return self.pd_items[self.pd_items[in_cul] == in_value][out_cul].iat[0]
        except Exception:
            logging.error(f"Error: Value is not found: {in_value}")
            raise Exception


# Function ---


def get_notion_db(db_id: str) -> dict:
    """
    get response via API from Notion database.
    Args:
        db_id (str): Notion database ID
    Return:
        response (dict)
    """
    task_url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f'Bearer {os.getenv("NOTION_TOKEN")}',
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",  # 最新のAPIバージョンを指定
    }
    res = requests.post(task_url, headers=headers)
    if res.status_code == 200:
        return json.loads(res.text)["results"]
    else:
        logging.error(f"Error: status_code: {res.status_code}, message: {res.reason}")
        raise Exception


def change_raw_task_to_dict(raw_tasks: list, Projects: RelatedDb, Sprints: RelatedDb) -> list:
    """
    Function for Task.
    change simple dict format from raw data
    Args:
        raw_tasks (list): list of dict format of raw date from Notion
        Projects, Sprints (RelatedDb): projects and sprints class
    Returns:
        tasks (list of dict)
    """
    tasks = []
    for raw_task in raw_tasks:
        # Task name
        task_name = raw_task["properties"]["タスク名"]["title"][0]["plain_text"]
        # プロジェクト名
        pj_name = Projects.get_item_from_pd("id", raw_task["properties"]["プロジェクト"]["relation"][0]["id"], "title")
        # スプリント名
        if len(raw_task["properties"]["スプリント"]["relation"]) > 0:
            sprint_name = Sprints.get_item_from_pd(
                "id", raw_task["properties"]["スプリント"]["relation"][0]["id"], "title"
            )
        else:
            logging.warning(f"{task_name}: Sprint is missing.")
            sprint_name = None
        # Start date
        start_date = None
        end_date = None
        if raw_task["properties"]["期限"]["date"] is not None:
            if raw_task["properties"]["期限"]["date"]["start"] is not None:
                start_time = datetime.datetime.strptime(raw_task["properties"]["期限"]["date"]["start"], "%Y-%m-%d")
                start_date = start_time.date()
            if raw_task["properties"]["期限"]["date"]["end"] is not None:
                end_time = datetime.datetime.strptime(raw_task["properties"]["期限"]["date"]["end"], "%Y-%m-%d")
                end_date = end_time.date()
        # tag default value
        if len(raw_task["properties"]["タグ"]["multi_select"]) > 0:
            tag = raw_task["properties"]["タグ"]["multi_select"][0]["name"]
        else:
            logging.warning(f"{task_name}: Tag is missing.")
            tag = "その他"
        task = {
            "title": raw_task["properties"]["タスク名"]["title"][0]["plain_text"],
            "status": raw_task["properties"]["ステータス"]["status"]["name"],
            "project": pj_name,
            "start": start_date,
            "end": end_date,
            "sprint": sprint_name,
            "tag": tag,
        }
        tasks.append(task)
    return tasks


def sort_filter(pd_tasks: pd.DataFrame, Projects: RelatedDb, Sprints: RelatedDb) -> pd.DataFrame:
    """
    Before notification, sort and filter pandas tasks
    Filtering condition:
        - It is during or over the task period today.
            - start: equal or more than today.
            - end: equal or less than tomorrow.
        - the current sprint
        - status is "not-started", "in-progress" or "in-review".
    Sorting condition:
        - tag -> project
    Args:
        pd_tasks (pd.DataFrame):
    Returns:
        filtered and sorted tasks (pd.DataFrame)
    """
    # Fliter: remove missing end date or sprint tasks
    active_tasks = pd_tasks[(pd_tasks["end"].notnull()) & (pd_tasks["sprint"].notnull())]

    # Flitering
    current_sprint = Sprints.get_item_from_pd("status", "current", "title")
    today = datetime.date.today()
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    hot_tasks = active_tasks[
        (
            (active_tasks["end"] - tomorrow < datetime.timedelta(days=2))
            | (today - active_tasks["start"] >= datetime.timedelta(days=0))
        )
        & (active_tasks["sprint"] == current_sprint)
        & (
            (active_tasks["status"] == "未着手")
            | (active_tasks["status"] == "進行中")
            | (active_tasks["status"] == "反応待ち")
        )
    ]

    # Sort: tag -> project
    return hot_tasks.sort_values(["project", "tag"])


def make_sentense(pd_tasks: pd.DataFrame) -> list:
    """
    Make sentense function to be notified.
    Args:
        pd_tasks (pd.DataFrame): filtered and sorted tasks.
    Returns:
        notifing sentense (list of str)
    """
    sentense_list = []
    sentense = datetime.date.today().strftime("%Y-%m-%d")  # 最初に日付を入れる
    saved_tag = ""
    saved_pj = ""
    # プロジェクトを先頭に各タスクを並べる
    for row in pd_tasks.itertuples():
        if saved_tag != row.tag:
            saved_tag = row.tag
            sentense_list.append(sentense)
            sentense = "■■" + row.tag + "■■\n"
        if saved_pj != row.project:
            saved_pj = row.project
            sentense += f"{row.project}\n"
        sentense += f" - {row.title}\n"
    sentense_list.append(sentense)

    return sentense_list


def send_line_masageapi(notification_message: str) -> None:
    """
    Notificate to LINE
    """
    line_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    line_group_id = os.getenv('LINE_MESSAGE_API_GROUP_ID')
    line_api_url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {line_token}',
    }
    data = {
        'to': line_group_id,
        'messages': [
            {
                'type': 'text',
                'text': notification_message,
            },
        ],
    }
    requests.post(line_api_url, headers=headers, data=json.dumps(data))


if __name__ == "__main__":
    main()
