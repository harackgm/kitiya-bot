import os
import requests
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
TARGET_URL = "https://www.kitiya.jp/"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def send_line_flex_carousel(items):
    """LINE Messaging APIを使ってカルーセル（Flex Message）を送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    bubbles = []
    for item in items[:10]:  # 最新10件を取得
        bubble = {
            "type": "bubble",
            "size": "micro",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "現在の掲載商品",
                        "weight": "bold",
                        "color": "#1DB446",
                        "size": "xs",
                    },
                    {
                        "type": "text",
                        "text": item["title"],
                        "weight": "bold",
                        "size": "sm",
                        "wrap": True,
                        "margin": "xs",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "商品ページヘ",
                            "uri": TARGET_URL,
                        },
                        "style": "primary",
                        "color": "#00B900",
                        "size": "sm",
                    }
                ],
            },
        }
        bubbles.append(bubble)

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": "【吉や】現在掲載されている最新10件",
                "contents": {"type": "carousel", "contents": bubbles},
            }
        ],
    }

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        print("LINEへのカルーセル送信に成功しました。")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def main():
    print("ブラウザを起動して吉やHPへアクセス中...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)
            html = page.content()
        except Exception as e:
            print(f"アクセスエラーが発生しました: {e}")
            browser.close()
            return

        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    current_items = []

    # HP上で現在掲載されている商品要素を取得
    for element in soup.find_all(
        ["div", "td", "p", "li"], string=lambda t: t and "円" in t
    ):
        parent = element.parent
        full_text = parent.get_text(separator=" ", strip=True)

        if len(full_text) < 150 and "カート" not in full_text:
            # 重複を防ぎつつ追加
            if not any(item["title"] == full_text for item in current_items):
                current_items.append({"title": full_text})

    print(f"現在HPから {len(current_items)} 件を取得しました。")

    # 上から順（現在あるものの中での最新10件）をカルーセル送信
    if current_items:
        send_line_flex_carousel(current_items[:10])
    else:
        print("表示できる商品要素が見つかりませんでした。")


if __name__ == "__main__":
    main()
