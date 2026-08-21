import os
import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
TARGET_URL = "https://www.kitiya.jp/"

# GitHub Secretsから安全に取得（無ければ空文字）
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def send_line_notify(message):
    """LINE Messaging APIを使ってメッセージを送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        print("LINEへの通知に成功しました。")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def init_db():
    conn = sqlite3.connect("kitiya_products.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            price TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def monitor_kitiya():
    init_db()
    print("ブラウザを起動して吉やHPをチェック中...")

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
    conn = sqlite3.connect("kitiya_products.db")
    cursor = conn.cursor()

    new_items = []

    for element in soup.find_all(
        ["div", "td", "p", "li"], string=lambda t: t and "円" in t
    ):
        parent = element.parent
        full_text = parent.get_text(separator=" ", strip=True)

        if len(full_text) < 150 and "カート" not in full_text:
            try:
                cursor.execute(
                    """
                    INSERT INTO products (title, price, status)
                    VALUES (?, ?, ?)
                """,
                    (full_text, "価格込み", "入荷情報"),
                )
                new_items.append(full_text)
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()

    if new_items:
        message = (
            f"【吉や 新着・再入荷通知】\n{len(new_items)}件の新しい更新があります！\n\n"
        )
        for item in new_items[:5]:
            message += f"・{item}\n"
        message += f"\n▼HPで確認\n{TARGET_URL}"

        send_line_notify(message)
        print(f"差分検知: {len(new_items)} 件の新着を通知しました。")
    else:
        print("新規の更新（差分）はありませんでした。")


if __name__ == "__main__":
    monitor_kitiya()
