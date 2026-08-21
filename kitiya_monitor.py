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


def send_line_flex(items):
    """LINE Messaging APIを使って見やすいFlex Message（単一バブル）を送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    # 各記事の要素を作成
    item_contents = []
    for i, item in enumerate(items[:3], 1):
        item_contents.extend([
            {
                "type": "text",
                "text": f"■ {item['title']}",
                "weight": "bold",
                "size": "sm",
                "wrap": True,
                "color": "#111111"
            },
            {
                "type": "button",
                "action": {
                    "type": "uri",
                    "label": "👉 記事を開く",
                    "uri": item["url"]
                },
                "style": "link",
                "height": "sm",
                "margin": "xs"
            },
            {
                "type": "separator",
                "margin": "md"
            }
        ])

    # 最後の区切り線を削除
    if item_contents:
        item_contents.pop()

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": "【吉や】最新の入荷情報（3件）",
                "contents": {
                    "type": "bubble",
                    "header": {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": "#00B900",
                        "contents": [
                            {
                                "type": "text",
                                "text": "【吉や】最新入荷情報 (上位3件)",
                                "weight": "bold",
                                "color": "#FFFFFF",
                                "size": "sm"
                            }
                        ]
                    },
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": item_contents,
                        "spacing": "sm"
                    }
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
        print("LINEへの通知送信に成功しました！")
    except Exception as e:
        print(f"LINE通知エラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"詳細レスポンス: {e.response.text}")


def main():
    print("ブラウザを起動して吉や入荷ブログ一覧へアクセス中...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 日本語環境を指定してアクセス（英文表示を防止）
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja,ja-JP;q=0.9"}
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
        
        if "/apps/note/archives/" in href and not "/tag/" in href:
            full_url = urljoin(TARGET_URL, href)
            
            # テキスト情報を取得
            text = a_tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 5:
                parent_text = a_tag.parent.get_text(separator=" ", strip=True)
                text = parent_text if parent_text else "最新入荷情報"

            # 「SNS」などの余分な文字列を取り除き、長すぎる文章をカット
            clean_text = text.replace("SNS", "").strip()
            if len(clean_text) > 80:
                clean_text = clean_text[:77] + "..."

            # 重複を排除して追加
            if not any(item["url"] == full_url for item in current_items):
                current_items.append({
                    "title": clean_text,
                    "url": full_url
                })

    print(f"ブログ一覧から {len(current_items)} 件の記事を取得しました。")

    if current_items:
        # 上位3件をきれいなカード形式で送信
        send_line_flex(current_items[:3])
    else:
        print("表示できる入荷情報が見つかりませんでした。")


if __name__ == "__main__":
    main()
