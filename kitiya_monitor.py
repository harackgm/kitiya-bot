import os
import sys
import sqlite3
import requests
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_URL = "https://www.kitiya.jp/apps/note/"
TROUT_BASE_URL = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
DB_FILE = "kitiya_data.db"
KITIYA_LOGO_URL = "https://www.kitiya.jp/apps/note/wp-content/uploads/2023/01/cropped-logo-192x192.png"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# --- データベース初期化 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notified_items (
            item_id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_first_run():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notified_items")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0

def is_already_notified(item_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM notified_items WHERE item_id = ?", (item_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_notified_item(item_id, title, url):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO notified_items (item_id, title, url)
        VALUES (?, ?, ?)
    """, (item_id, title, url))
    conn.commit()
    conn.close()

# --- クレンジング処理 ---
def clean_image_url(img_tag, base_url):
    if not img_tag:
        return ""
    src = img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src") or ""
    if not src or "blank.gif" in src or "spacer.gif" in src or "transparent" in src:
        return ""
    
    full_url = urljoin(base_url, src)
    if full_url.startswith("http://"):
        full_url = full_url.replace("http://", "https://", 1)
    return full_url

def clean_title_text(text_or_elem):
    """HTMLタグ、New Arrivalsなどのマーク文字、改行を完全に除去"""
    if not text_or_elem:
        return ""
    
    if hasattr(text_or_elem, 'get_text'):
        soup_copy = BeautifulSoup(str(text_or_elem), "html.parser")
        for img in soup_copy.find_all("img"):
            img.decompose()
        text = soup_copy.get_text(strip=True)
    else:
        text = str(text_or_elem)

    # HTMLタグ・文字列消去
    text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    
    # New Arrivals / Re Arrivals などの余計なマーク文言を消去
    text = re.sub(r'^(New\s*Arrivals|Re\s*Arrivals|新入荷|再入荷|SALE|新色)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- LINE Flex Message 送信処理 ---
def send_line_flex_messages(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID or not items:
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }

    # 10件ずつバブルメッセージを束ねて送信
    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        bubbles = []

        for item in chunk:
            image_url = item['image_url'] if item['image_url'] else KITIYA_LOGO_URL
            
            # カテゴリ別の色分け
            badge_color = "#E61B23"
            tag_text = "新入荷"
            if "blog_" in item['id']:
                badge_color = "#00B900"
                tag_text = "ブログ更新"

            bubble = {
                "type": "bubble",
                "size": "micro",
                "hero": {
                    "type": "image",
                    "url": image_url,
                    "size": "full",
                    "aspectRatio": "4:3",
                    "aspectMode": "cover"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"【吉や】{tag_text}",
                            "weight": "bold",
                            "size": "xs",
                            "color": badge_color
                        },
                        {
                            "type": "text",
                            "text": item['title'],
                            "weight": "bold",
                            "size": "sm",
                            "margin": "xs",
                            "wrap": True
                        },
                        {
                            "type": "text",
                            "text": f"価格: {item['price']}" if item['price'] else " ",
                            "size": "xs",
                            "color": "#666666",
                            "margin": "xs"
                        }
                    ]
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "button",
                            "action": {
                                "type": "uri",
                                "label": "ページへ",
                                "uri": item['url']
                            },
                            "style": "primary",
                            "color": badge_color,
                            "height": "sm"
                        }
                    ]
                }
            }
            bubbles.append(bubble)

        flex_payload = {
            "to": LINE_USER_ID,
            "messages": [
                {
                    "type": "flex",
                    "altText": f"【吉や】新着情報が{len(chunk)}件あります",
                    "contents": {
                        "type": "carousel",
                        "contents": bubbles
                    }
                }
            ]
        }
        
        res = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=flex_payload)
        print(f"LINE送信結果: {res.status_code}")

# --- メイン監視処理 ---
def scrape_kitiya():
    init_db()
    first_run = is_first_run()
    if first_run:
        print("【初回実行】DB構築のため全件登録のみ（LINE通知なし）を実行します。")

    new_items_to_notify = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. ブログ更新の監視
        try:
            page.goto(BLOG_URL, wait_until="networkidle")
            soup = BeautifulSoup(page.content(), "html.parser")
            articles = soup.select("article, .post, .entry")
            for article in articles[:3]:
                a_tag = article.select_one("a")
                if a_tag and a_tag.get("href"):
                    url = a_tag.get("href")
                    item_id = f"blog_{url}"
                    title = clean_title_text(a_tag.get_text(strip=True))
                    img_tag = article.select_one("img")
                    image_url = clean_image_url(img_tag, BLOG_URL)

                    if not is_already_notified(item_id):
                        if not first_run:
                            new_items_to_notify.append({
                                "id": item_id, "title": title, "url": url,
                                "price": "", "image_url": image_url
                            })
                        save_notified_item(item_id, title, url)
        except Exception as e:
            print(f"ブログ取得エラー: {e}")

        # 2. トラウト商品の監視
        try:
            page.goto(TROUT_BASE_URL, wait_until="networkidle")
            soup = BeautifulSoup(page.content(), "html.parser")
            
            all_pid_links = soup.find_all("a", href=lambda h: h and "pid=" in h)
            items_found = []
            for link in all_pid_links:
                title_text = clean_title_text(link)
                if not title_text or len(title_text) < 2:
                    continue
                parent = link.find_parent("li") or link.find_parent("div")
                if parent and parent not in items_found:
                    items_found.append((link, parent))

            for link, parent in items_found:
                url = urljoin(TROUT_BASE_URL, link.get("href"))
                item_id = f"trout_{url}"
                title = clean_title_text(link)

                # 価格の取得
                price_elem = parent.select_one(".price, .product_price, .item_price")
                price = price_elem.get_text(strip=True) if price_elem else ""

                # 画像の取得
                img_tag = parent.select_one("img")
                image_url = clean_image_url(img_tag, TROUT_BASE_URL)

                if not is_already_notified(item_id):
                    if not first_run:
                        new_items_to_notify.append({
                            "id": item_id, "title": title, "url": url,
                            "price": price, "image_url": image_url
                        })
                    save_notified_item(item_id, title, url)
        except Exception as e:
            print(f"商品取得エラー: {e}")

        browser.close()

    # 通知処理（初回以外で差分があれば送信）
    if new_items_to_notify:
        print(f"新規アイテム {len(new_items_to_notify)} 件をLINEに通知します。")
        send_line_flex_messages(new_items_to_notify)
    else:
        print("通知対象の新しいアイテムはありませんでした。")

def main():
    scrape_kitiya()

if __name__ == "__main__":
    main()
