import os
import requests
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
TARGET_URL = "https://www.kitiya.jp/"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def send_line_text(message):
    """LINE Messaging APIを使ってテキストメッセージを送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message
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
        print("LINEへのテキスト送信に成功しました。")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def main():
    print("ブラウザを起動して吉やHPへアクセス中...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            html = page.content()
        except Exception as e:
            print(f"アクセスエラーが発生しました: {e}")
            browser.close()
            return

        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    current_items = []

    # HP上で現在掲載されている商品要素を取得
    for element in soup.find_all(["div", "td", "p", "li"], string=lambda t: t and "円" in t):
        parent = element.parent
        full_text = parent.get_text(separator=" ", strip=True)

        if len(full_text) < 150 and "カート" not in full_text:
            if full_text not in current_items:
                current_items.append(full_text)

    print(f"現在HPから {len(current_items)} 件を取得しました。")

    if current_items:
        # 最新10件を1つのテキストメッセージに整形
        msg = "【吉や】現在掲載中の最新10件\n"
        msg += "------------------------\n"
        for i, item in enumerate(current_items[:10], 1):
            msg += f"{i}. {item}\n"
        msg += "------------------------\n"
        msg += f"▼HPで確認\n{TARGET_URL}"

        send_line_text(msg)
    else:
        print("表示できる商品要素が見つかりませんでした。")


if __name__ == "__main__":
    main()
