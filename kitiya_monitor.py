import os
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
TARGET_URL = "https://www.kitiya.jp/apps/note/"

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
    print("ブラウザを起動して吉や入荷ブログ一覧へアクセス中...")

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

    # 入荷ブログ記事のリンク（/apps/note/archives/数字）を抽出
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        
        # /archives/数字 の形式になっている記事詳細リンクを抽出
        if "/apps/note/archives/" in href and not "/tag/" in href:
            full_url = urljoin(TARGET_URL, href)
            
            # テキスト情報を取得
            text = a_tag.get_text(separator=" ", strip=True)
            
            # テキストが空の場合は親要素からテキストを取得
            if not text or len(text) < 5:
                parent_text = a_tag.parent.get_text(separator=" ", strip=True)
                text = parent_text if parent_text else "最新入荷情報"

            # 重複防止（同じ記事URLは1回だけ登録）
            if not any(item["url"] == full_url for item in current_items):
                current_items.append({
                    "title": text,
                    "url": full_url
                })

    print(f"ブログ一覧から {len(current_items)} 件の記事を取得しました。")

    if current_items:
        msg = "【吉や】最新の入荷情報（上位3件）\n"
        msg += "========================\n\n"
        
        for i, item in enumerate(current_items[:3], 1):
            msg += f"■ {i}. {item['title']}\n"
            msg += f"🔗 {item['url']}\n\n"
            
        msg += "========================"

        send_line_text(msg)
    else:
        print("表示できる入荷情報が見つかりませんでした。")


if __name__ == "__main__":
    main()
