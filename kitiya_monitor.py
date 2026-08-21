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


def send_line_carousel(items):
    """サムネイル画像付きのカルーセル（Flex Message）をLINEに送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    bubbles = []
    for item in items[:3]:
        bubble = {
            "type": "bubble",
            "size": "kilo"
        }

        # サムネイル画像が存在する場合は上部画像エリアを追加
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
                    "text": "【吉や】入荷情報",
                    "weight": "bold",
                    "color": "#1DB446",
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

        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "記事を開く",
                        "uri": item["url"]
                    },
                    "style": "primary",
                    "color": "#00B900"
                }
            ]
        }

        bubbles.append(bubble)

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": "【吉や】最新の入荷情報（3件）",
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
        print("サムネイル付きカルーセルの送信に成功しました！")
    except Exception as e:
        print(f"LINE通知エラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"詳細レスポンス: {e.response.text}")


def main():
    print("ブラウザを起動して吉や入荷ブログ一覧へアクセス中...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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

            # 余分な文字列を取り除き、文字数を適切に制限
            clean_text = text.replace("SNS", "").strip()
            if len(clean_text) > 60:
                clean_text = clean_text[:57] + "..."

            # サムネイル画像（imgタグ）のURLを取得
            img_tag = a_tag.find("img")
            if not img_tag and a_tag.parent:
                img_tag = a_tag.parent.find("img")

            img_url = ""
            if img_tag:
                src = img_tag.get("src") or img_tag.get("data-src") or ""
                if src:
                    img_url = urljoin(TARGET_URL, src)
                    # LINEのFlex Messageはhttps必須
                    if img_url.startswith("http://"):
                        img_url = img_url.replace("http://", "https://")

            # 重複防止で追加
            if not any(item["url"] == full_url for item in current_items):
                current_items.append({
                    "title": clean_text,
                    "url": full_url,
                    "img_url": img_url
                })

    print(f"ブログ一覧から {len(current_items)} 件の記事を取得しました。")

    if current_items:
        # 上位3件を画像付きカルーセルで送信
        send_line_carousel(current_items[:3])
    else:
        print("表示できる入荷情報が見つかりませんでした。")


if __name__ == "__main__":
    main()
