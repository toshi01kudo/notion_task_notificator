# notion_task_notificator

## 概要
Notion上に登録したタスクをLINEへ通知するもの。\
スプリントを設定しているタスクが対象。\
Notion のテンプレートは[課題管理](https://www.notion.so/gallery/templates/notion-issue-tracker?cr=ser%253A%25E3%2582%25B9%25E3%2583%2597%25E3%2583%25AA%25E3%2583%25B3%25E3%2583%2588)を活用した。

## 仕組み
* Notion
* LINE通知はMessaging APIを使用。

## 参考
* [Notion API を使用してデータベースを操作する](https://zenn.dev/kou_pg_0131/articles/notion-api-usage)
* [LINEのgroupIDを返してくれるbot](https://qiita.com/enbanbunbun123/items/2504687e4b6c13a289db)