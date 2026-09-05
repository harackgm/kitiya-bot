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

# 大量通知連投を防ぐ安全装置の上限値
MAX_NOTIFY_LIMIT = 10

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# --- データベース処理 ---
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
    
    # ダミー画像や作成中のNo Image（now_printing等）を除外するリスト
    exclude_keywords = ["blank.gif", "spacer.gif", "transparent", "noimage", "now_printing", "no_image", "nowprinting"]
    if not src or any(keyword in src.lower() for keyword in exclude_keywords):
        return ""
    
    full_url = urljoin(base_url, src)
    if full_url.startswith("http://"):
        full_url = full_url.replace("http://", "https://", 1)
    return full_url

def clean_title_text(text_or_elem):
    if not text_or_elem:
        return ""
    
    if hasattr(text_or_elem, 'get_text'):
        soup_copy = BeautifulSoup(str(text_or_elem), "html.parser")
        for img in soup_copy.find_all("img"):
            img.decompose()
        text = soup_copy.get_text(strip=True)
    else:
        text = str(text_or_elem)

    text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'^(New\s*Arrivals|Re\s*Arrivals|新入荷|再入荷|SALE|新色|SNS)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}', '', text)
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

    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        bubbles = []

        for item in chunk:
            image_url = item['image_url'] if item['image_url'] else KITIYA_LOGO_URL
            item_type = item.get('type', 'new')
            
            if "blog_" in item['id']:
                badge_color = "#00B900"
                tag_text = "【吉や】 ブログ更新"
                btn_color = "#00B900"
            elif item_type == "restock":
                badge_color = "#D97706"
                tag_text = "【吉や】 🔥再入荷情報！"
                btn_color = "#E69900"
            else:
                badge_color = "#E61B23"
                tag_text = "【吉や】 ✨新入荷"
                btn_color = "#E61B23"

            bubble = {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": image_url,
                    "size": "full",
                    "aspectRatio": "20:13",
                    "aspectMode": "cover"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": tag_text,
                            "weight": "bold",
                            "size": "xs",
                            "color": badge_color
                        },
                        {
                            "type": "text",
                            "text": item['title'],
                            "weight": "bold",
                            "size": "md",
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
                                "label": "商品ページへ" if "trout_" in item['id'] else "記事を読む",
                                "uri": item['url']
                            },
                            "style": "primary",
                            "color": btn_color,
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
        
        if res.status_code == 429 or (res.status_code != 200 and "limit" in res.text.lower()):
            print("[ERROR] 今月分のLINE通知上限（200通）に到達しました。")
        else:
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
        context = browser.new_context(
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja,ja-JP;q=0.9,en-US;q=0.8,en;q=0.7"}
        )
        page = context.new_page()

        # 1. ブログ更新の監視
        try:
            page.goto(BLOG_URL, wait_until="domcontentloaded", timeout=30000)
            soup = BeautifulSoup(page.content(), "html.parser")
            
            blog_links = soup.find_all("a", href=re.compile(r"/apps/note/archives/\d+"))
            seen_urls = set()
            for a_tag in blog_links:
                original_href = a_tag.get("href")
                url = urljoin(BLOG_URL, original_href).rstrip("/")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                related_a_tags = soup.find_all("a", href=original_href)
                title = ""
                img_tag = None
                
                for rel_a in related_a_tags:
                    if not title:
                        text = clean_title_text(rel_a.get_text(strip=True))
                        if text and len(text) >= 2:
                            title = text
                    if not img_tag:
                        img = rel_a.find("img")
                        if img:
                            img_tag = img

                if not img_tag:
                    parent = a_tag.find_parent("article")
                    if parent:
                        img_tag = parent.find("img")
                
                if not title or len(title) < 2:
                    parent = a_tag.find_parent("article")
                    if parent:
                        title = clean_title_text(parent.get_text(strip=True))

                if not title or len(title) < 2:
                    continue

                item_id = f"blog_{url}"
                image_url = clean_image_url(img_tag, BLOG_URL)

                if not is_already_notified(item_id):
                    new_items_to_notify.append({
                        "id": item_id, "type": "blog", "title": title, "url": url,
                        "price": "", "image_url": image_url
                    })
                
                if len(seen_urls) >= 5:
                    break
        except Exception as e:
            print(f"ブログ取得エラー: {e}")

        # 2. トラウト商品の監視
        try:
            page.goto(TROUT_BASE_URL, wait_until="domcontentloaded", timeout=30000)
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
                title = clean_title_text(link)

                parent_html = str(parent) if parent else ""
                is_restock = "再入荷" in parent_html or "Re Arrivals" in parent_html or "icons4.gif" in parent_html
                item_type = "restock" if is_restock else "new"

                item_id = f"trout_{url}"

                price_elem = parent.select_one(".c-item-list__price, .price, .product_price, .item_price") if parent else None
                price = price_elem.get_text(strip=True) if price_elem else ""

                img_tag = parent.select_one("img") if parent else None
                image_url = clean_image_url(img_tag, TROUT_BASE_URL)

                # ▼ページ作成中（No Imageなど）の商品の場合は通知を保留（DBに保存しない）
                if not image_url:
                    continue

                if not is_already_notified(item_id):
                    new_items_to_notify.append({
                        "id": item_id, "type": item_type, "title": title, "url": url,
                        "price": price, "image_url": image_url
                    })
        except Exception as e:
            print(f"商品取得エラー: {e}")

        context.close()
        browser.close()

    # 通知・既読処理（ガードレール適用）
    if new_items_to_notify:
        if first_run:
            print(f"初回実行のため、検知された {len(new_items_to_notify)} 件をDB登録のみ実行します。")
            for item in new_items_to_notify:
                save_notified_item(item['id'], item['title'], item['url'])
        elif len(new_items_to_notify) > MAX_NOTIFY_LIMIT:
            print(f"[WARN] 未通知件数が上限({MAX_NOTIFY_LIMIT}件)を超える {len(new_items_to_notify)} 件検知されました。")
            print("大量通知防止のため、LINE送信をスキップし全件既読化処理（DB更新）のみ実行します。")
            for item in new_items_to_notify:
                save_notified_item(item['id'], item['title'], item['url'])
        else:
            print(f"新規アイテム {len(new_items_to_notify)} 件をLINEに通知します。")
            send_line_flex_messages(new_items_to_notify)
            for item in new_items_to_notify:
                save_notified_item(item['id'], item['title'], item['url'])
    else:
        print("通知対象の新しいアイテムはありませんでした。")

def main():
    scrape_kitiya()

if __name__ == "__main__":
    main()
