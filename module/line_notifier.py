# module/line_notifier.py

import requests
import json
import os
import logging

def send_line_messageapi(notification_message: str) -> None:
    """
    LINE Message APIを使用してメッセージを通知する。

    Args:
        notification_message: 送信するメッセージ内容。
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

    try:
        res = requests.post(line_api_url, headers=headers, data=json.dumps(data))
        res.raise_for_status() # HTTPステータスコードが4xxまたは5xxの場合は例外を発生
        logging.info("LINE message sent successfully.")
    except requests.exceptions.RequestException as e:
        logging.error(f"LINE通知APIエラーが発生しました: {e}")
