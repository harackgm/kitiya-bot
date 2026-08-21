import os
import sqlite3
import requests
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_URL = "https://www.kitiya.jp/apps/note/"
TROUT_BASE_URL = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"

DB_FILE = "kitiya_data.db"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def send_line_carousel(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    bubbles = []
    for item in items:
        status_type = item.get("status_type", "new")
        
        if item.get("category") == "blog":
            category_name = "【吉や】ブログ更新"
            btn_label = "記事を読む"
        elif status_type == "restock":
            category_name = "【吉や】🔥再入荷情報！"
            btn_label = "商品ページへ"
        else:
            category_name = "【吉や】✨新入荷商品"
            btn_label = "商品ページへ"

        bubble = {
            "type": "bubble",
            "size": "kilo"
        }

        if item.get("img_url"):
            bubble["hero"] = {
                "type": "image",
                "url": item["img_url"],
                "size": "full",
                "aspectRatio": "4:3",
                "aspectMode": "cover"
            }

        bubble["body"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": category_name,
                    "weight": "bold",
                    "color": "#1DB446" if status_type != "restock" else "#E60012",
                    "size": "xs"
                },
                {
                    "type": "text",
                    "text": item["title"],
                    "weight": "bold",
                    "size": "sm",
                    "wrap": True,
                    "margin": "sm",
                    "maxLines": 3
                }
            ]
        }

        if item.get("price"):
            bubble["body"]["contents"].append({
                "type": "text",
                "text": f"価格: {item['price']}",
                "size": "xs",
                "color": "#111111",
                "weight": "bold",
                "margin": "xs"
            })

        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": btn_label,
                        "uri": item["url"]
                    },
                    "style": "primary",
                    "color": "#00B900" if status_type != "restock" else "#E60012"
                }
            ]
        }

        bubbles.append(bubble)

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": f"【吉や】更新情報（{len(items)}件）",
                "contents": {
                    "type": "carousel",
                    "contents": bubbles
                }
            }
        ]
    }

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        print(f"テストLINE通知完了: {len(items)} 件")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def main():
    print("📱 テスト通知をLINEに送信します...")

    # テスト用のサンプルデータ
    test_items = [
        {
            "title": "【テスト表示】ロデオクラフト モカ DR-SS（オリジナルカラー）",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n",
            "img_url": "https://img07.shop-pro.jp/PA01429/015/product/163821033.jpg",
            "price": "1,650円",
            "category": "product",
            "status_type": "new"
        },
        {
            "title": "【テスト表示】ヴァルケイン ハイバースト 1.6g 【人気色再入荷！】",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n",
            "img_url": "https://img07.shop-pro.jp/PA01429/015/product/163821033.jpg",
            "price": "528円",
            "category": "product",
            "status_type": "restock"
        },
        {
            "title": "【テスト表示】最新トラウトルアー入荷のお知らせ（ブログ）",
            "url": "https://www.kitiya.jp/apps/note/",
            "img_url": "https://www.kitiya.jp/apps/note/wp-content/uploads/2023/01/sample.jpg",
            "category": "blog",
            "status_type": "new"
        }
    ]

    send_line_carousel(test_items)


if __name__ == "__main__":
    main()
