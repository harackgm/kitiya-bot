import os
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

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# --- データベース処理 ---
def init_db():
    """データベースとテーブルの初期化"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blog_posts (
            url TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            is_sold_out INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_initial_run():
    """DBが空（初回実行）かどうかを判定"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    p_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM blog_posts")
    b_count = cursor.fetchone()[0]
    conn.close()
    return (p_count == 0 and b_count == 0)

# --- スクレイピング処理 ---
def check_blog_updates(initial_run):
    """ブログの更新チェック"""
    new_items = []
    try:
        response = requests.get(BLOG_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        articles = soup.select("article, .post-list-item, .entry")
        for article in articles[:10]:
            title_tag = article.select_one("h2 a, .entry-title a, a")
            if not title_tag or not title_tag.get("href"):
                continue

            title = title_tag.get_text(strip=True)
            url = urljoin(BLOG_URL, title_tag["href"])
            img_tag = article.select_one("img")
            img_url = urljoin(BLOG_URL, img_tag["src"]) if img_tag and img_tag.get("src") else ""

            cursor.execute("SELECT url FROM blog_posts WHERE url = ?", (url,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO blog_posts (url, title) VALUES (?, ?)", (url, title))
                if not initial_run:
                    new_items.append({
                        "title": title, "url": url, "img_url": img_url,
                        "category": "blog", "status_type": "new"
                    })

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ブログスクレイピングエラー: {e}")

    return new_items

def check_product_updates(initial_run):
    """商品ページの全ページ更新チェック（Playwright使用）"""
    new_items = []
    page_num = 1
    total_saved = 0
    all_seen_urls = set()  # 今回の実行で巡回した全商品URLの記録

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        while True:
            if page_num == 1:
                url = TROUT_BASE_URL
            else:
                url = f"{TROUT_BASE_URL}&page={page_num}"
                
            try:
                print(f"ページ {page_num} を巡回中... ({url})")
                page.goto(url, wait_until="networkidle")
                soup = BeautifulSoup(page.content(), "html.parser")

                # メインエリア優先で商品枠を取得
                main_area = soup.select_one("#main, .main_content, .product_list, .item_list") or soup
                product_list = main_area.select(".product_item, .item_box, li.item, .product_list li, .item_list li")

                if not product_list:
                    item_links = main_area.find_all("a", href=lambda h: h and "pid=" in h)
                    containers = []
                    for link in item_links:
                        parent = link.find_parent("li") or link.find_parent("div") or link.parent
                        if parent and parent not in containers:
                            containers.append(parent)
                    product_list = containers

                new_urls_in_this_page = 0
                items_in_page = 0

                for item in product_list:
                    a_tag = item.find("a", href=lambda h: h and "pid=" in h) or item.select_one("a")
                    if not a_tag or not a_tag.get("href"):
                        continue

                    item_url = urljoin(url, a_tag["href"])

                    # このページで未登録のURLかチェック
                    if item_url not in all_seen_urls:
                        all_seen_urls.add(item_url)
                        new_urls_in_this_page += 1

                    title = a_tag.get_text(strip=True)
                    if not title:
                        img_in_a = a_tag.select_one("img")
                        if img_in_a and img_in_a.get("alt"):
                            title = img_in_a["alt"]
                    if not title:
                        title_elem = item.select_one(".product_name, .name, h2, h3")
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                    if not title:
                        continue

                    price_match = re.search(r"[\d,]+\s*円", item.get_text())
                    price = price_match.group(0) if price_match else "価格不詳"

                    img_tag = item.select_one("img")
                    img_url = urljoin(url, img_tag["src"]) if img_tag and img_tag.get("src") else ""

                    item_text = item.get_text()
                    is_sold_out = 1 if ("SOLD OUT" in item_text.upper() or "売り切れ" in item_text) else 0

                    cursor.execute("SELECT is_sold_out FROM products WHERE url = ?", (item_url,))
                    row = cursor.fetchone()

                    if row is None:
                        cursor.execute("INSERT INTO products (url, title, price, is_sold_out) VALUES (?, ?, ?, ?)",
                                       (item_url, title, price, is_sold_out))
                        if not initial_run and not is_sold_out:
                            new_items.append({
                                "title": title, "url": item_url, "img_url": img_url,
                                "price": price, "category": "product", "status_type": "new"
                            })
                    else:
                        old_sold_out = row[0]
                        if old_sold_out == 1 and is_sold_out == 0:
                            if not initial_run:
                                new_items.append({
                                    "title": title, "url": item_url, "img_url": img_url,
                                    "price": price, "category": "product", "status_type": "restock"
                                })
                        cursor.execute("UPDATE products SET is_sold_out = ?, price = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                                       (is_sold_out, price, item_url))

                    items_in_page += 1

                print(f"   └ 検出: {items_in_page} 件（うち新規URL: {new_urls_in_this_page} 件）")

                # 新しい商品が1件も増えなかった場合（最終ページ超過）は巡回終了
                if new_urls_in_this_page == 0:
                    print(f"-> 新しい商品が見つからなくなったため、ページ {page_num} で巡回を終了します。")
                    break

                total_saved += items_in_page
                page_num += 1

                if page_num > 100:
                    break

            except Exception as e:
                print(f"商品スクレイピングエラー（ページ {page_num}）: {e}")
                break

        conn.commit()
        conn.close()
        browser.close()

    print(f"📊 累計登録商品数: {len(all_seen_urls)} 件")
    return new_items

# --- LINE通知処理 ---
def send_line_carousel(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return
    if not items:
        return

    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        bubbles = []

        for item in chunk:
            status_type = item.get("status_type", "new")
            if item.get("category") == "blog":
                category_name, btn_label = "【吉や】ブログ更新", "記事を読む"
                color_code = "#1DB446"
            elif status_type == "restock":
                category_name, btn_label = "【吉や】🔥再入荷情報！", "商品ページへ"
                color_code = "#E60012"
            else:
                category_name, btn_label = "【吉や】✨新入荷商品", "商品ページへ"
                color_code = "#1DB446"

            bubble = {"type": "bubble", "size": "kilo"}
            if item.get("img_url"):
                bubble["hero"] = {
                    "type": "image", "url": item["img_url"], "size": "full",
                    "aspectRatio": "4:3", "aspectMode": "cover"
                }

            bubble["body"] = {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": category_name, "weight": "bold", "color": color_code, "size": "xs"},
                    {"type": "text", "text": item["title"], "weight": "bold", "size": "sm", "wrap": True, "margin": "sm", "maxLines": 3}
                ]
            }

            if item.get("price"):
                bubble["body"]["contents"].append(
                    {"type": "text", "text": f"価格: {item['price']}", "size": "xs", "color": "#111111", "weight": "bold", "margin": "xs"}
                )

            bubble["footer"] = {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "button", "action": {"type": "uri", "label": btn_label, "uri": item["url"]}, "style": "primary", "color": color_code}
                ]
            }
            bubbles.append(bubble)

        payload = {
            "to": LINE_USER_ID,
            "messages": [{"type": "flex", "altText": f"【吉や】更新情報（{len(chunk)}件）", "contents": {"type": "carousel", "contents": bubbles}}]
        }

        try:
            res = requests.post("https://api.line.me/v2/bot/message/push", 
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}, 
                                json=payload, timeout=10)
            res.raise_for_status()
            print(f"LINE通知完了: {len(chunk)} 件")
        except Exception as e:
            print(f"LINE通知エラー: {e}")

# --- 実行エントリーポイント ---
def main():
    print("🚀 スクレイピング処理を開始します...")
    init_db()

    initial_run = is_initial_run()
    if initial_run:
        print("ℹ️ 初回実行を検知しました。データベースの構築のみ行い、LINE通知はスキップします。")

    blog_updates = check_blog_updates(initial_run)
    product_updates = check_product_updates(initial_run)

    all_updates = blog_updates + product_updates

    if initial_run:
        print("✅ 初回データベース構築が完了しました。")
    elif all_updates:
        print(f"📢 新しい更新を {len(all_updates)} 件検知しました。")
        send_line_carousel(all_updates)
    else:
        print("確実な新規・再入荷情報はありませんでした。")

if __name__ == "__main__":
    main()
