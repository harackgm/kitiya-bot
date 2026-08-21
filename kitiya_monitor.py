import os
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
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

    # 商品リンクを含む要素を探して商品名・価格・URLを取得
    for a_tag in soup.find_all("a", href=True):
        text = a_tag.get_text(separator=" ", strip=True)
        
        # 金額（円）が含まれるリンク要素を抽出
        if "円" in text and len(text) > 5 and len(text) < 200:
            link_url = urljoin(TARGET_URL, a_tag["href"])
            
            # 重複防止
            if not any(item["url"] == link_url for item in current_items):
                current_items.append({
                    "info": text,
                    "url": link_url
                })

    print(f"現在HPから {len(current_items)} 件の商品情報を取得しました。")

    if current_items:
        # 件数を3件に変更
        msg = "【吉や】現在掲載中の最新3件\n"
        msg += "========================\n\n"
        
        for i, item in enumerate(current_items[:3], 1):
            msg += f"■ {i}. {item['info']}\n"
            msg += f"🔗 {item['url']}\n\n"
            
        msg += "========================"

        send_line_text(msg)
    else:
        print("表示できる商品要素が見つかりませんでした。")


if __name__ == "__main__":
    main()
