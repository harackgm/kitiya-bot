import os
import sys
import sqlite3
import requests
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_BASE_URL = "https://www.kitiya.jp/apps/note/"
TROUT_BASE_URL = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
DB_FILE = "kitiya_data.db"

# 吉やのロゴマーク（カード右上に表示）
KITIYA_LOGO_URL = "https://www.kitiya.jp/apps/note/wp-content/uploads/2023/01/cropped-logo-192x192.png"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# --- ヘルパー関数 ---
def clean_image_url(img_tag, base_url):
    """遅延読み込み(Lazy Load)に対応して正しい画像URLを取得"""
    if not img_tag:
        return ""
    src = img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src") or ""
    if not src or "blank.gif" in src or "spacer.gif" in src or "transparent" in src:
        return ""
    
    full_url = urljoin(base_url, src)
    if full_url.startswith("http://"):
        full_url = full_url.replace("http://", "https://", 1)
    return full_url

def fetch_blog_og_image(article_url):
    """個別記事ページからOGP画像(アイキャッチ画像)を取得"""
    try:
        res = requests.get(article_url, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_image and og_image.get("content"):
            img_url = og_image["content"]
            if img_url.startswith("http://"):
                img_url = img_url.replace("http://", "https://", 1)
            return img_url
        
        content_area = soup.select_one(".entry-content, article, .post-content, #main") or soup
        for img in content_area.select("img"):
            src = clean_image_url(img, article_url)
            if src and "avatar" not in src and "logo" not in src:
                return src
    except Exception as e:
        print(f"ブログ画像取得エラー ({article_url}): {e}")
    return ""

# --- データベース処理 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blog_posts (
            url TEXT PRIMARY KEY, title TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY, title TEXT, price TEXT, is_sold_out INTEGER, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_initial_run():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    p_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM blog_posts")
    b_count = cursor.fetchone()[0]
    conn.close()
    return (p_count == 0 and b_count == 0)

# --- ブログスクレイピング処理 ---
def check_blog_updates(initial_run=False):
    new_items = []
    
    now = datetime.now()
    current_month_url = f"{BLOG_BASE_URL}archives/date/{now.strftime('%Y/%m')}"
    urls_to_check = [current_month_url, BLOG_BASE_URL]
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    seen_urls = set()

    for target_url in urls_to_check:
        try:
            print(f"ブログ確認中: {target_url}")
            response = requests.get(target_url, timeout=10)
            if response.status_code != 200:
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            a_tags = soup.find_all("a", href=lambda h: h and re.search(r'/archives/\d+', h))
            
            for a in a_tags:
                href = a.get("href", "")
                full_url = urljoin(BLOG_BASE_URL, href)

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                title = a.get_text(strip=True)
                if not title or len(title) < 3 or "続きを読む" in title:
                    parent = a.find_parent(["article", "div", "li", "h2", "h3"])
                    if parent:
                        title_elem = parent.select_one("h1, h2, h3, .entry-title")
                        if title_elem:
                            title = title_elem.get_text(strip=True)

                if not title:
                    title = "【吉や】ブログ最新記事"

                cursor.execute("SELECT url FROM blog_posts WHERE url = ?", (full_url,))
                if not cursor.fetchone():
                    img_url = fetch_blog_og_image(full_url)
                    cursor.execute("INSERT INTO blog_posts (url, title) VALUES (?, ?)", (full_url, title))
                    
                    if not initial_run:
                        new_items.append({
                            "title": title,
                            "url": full_url,
                            "img_url": img_url,
                            "category": "blog",
                            "status_type": "blog"
                        })

        except Exception as e:
            print(f"ブログスクレイピングエラー ({target_url}): {e}")

    conn.commit()
    conn.close()
    return new_items

# --- 商品スクレイピング処理 ---
def check_product_updates(initial_run=False):
    new_items = []
    page_num = 1
    all_seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        while True:
            url = TROUT_BASE_URL if page_num == 1 else f"{TROUT_BASE_URL}&page={page_num}"
                
            try:
                print(f"商品ページ {page_num} を巡回中...")
                page.goto(url, wait_until="networkidle")
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)

                soup = BeautifulSoup(page.content(), "html.parser")

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

                for item in product_list:
                    a_tag = item.find("a", href=lambda h: h and "pid=" in h) or item.select_one("a")
                    if not a_tag or not a_tag.get("href"):
                        continue

                    item_url = urljoin(url, a_tag["href"])

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
                    img_url = clean_image_url(img_tag, url)

                    # 売り切れ判定（完売バッジのみを検知）
                    is_sold_out = 0
                    sold_out_elem = item.select_one(".sold_out, .soldout, .is-soldout")
                    sold_out_img = item.select_one("img[src*='sold'], img[alt*='SOLD'], img[alt*='売り切れ']")
                    if sold_out_elem or sold_out_img:
                        is_sold_out = 1

                    # バッジ（新色・特価・新入荷）の判定
                    item_text = item.get_text()
                    status_type = "new"
                    if "新色" in item_text:
                        status_type = "new_color"
                    elif "特価" in item_text:
                        status_type = "bargain"

                    cursor.execute("SELECT is_sold_out FROM products WHERE url = ?", (item_url,))
                    row = cursor.fetchone()

                    if row is None:
                        cursor.execute("INSERT INTO products (url, title, price, is_sold_out) VALUES (?, ?, ?, ?)",
                                       (item_url, title, price, is_sold_out))
                        if not initial_run and not is_sold_out:
                            new_items.append({
                                "title": title, "url": item_url, "img_url": img_url,
                                "price": price, "category": "product", "status_type": status_type
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

                if new_urls_in_this_page == 0:
                    break

                page_num += 1
                if page_num > 100:
                    break

            except Exception as e:
                print(f"商品スクレイピングエラー（ページ {page_num}）: {e}")
                break

        conn.commit()
        conn.close()
        browser.close()

    return new_items

# --- LINE通知処理 ---
def send_line_carousel(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報が見つかりません。")
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
                category_name = "【吉や】ブログ更新"
                btn_label = "記事を読む"
                color_code = "#00B900" # LINEグリーン
            elif status_type == "new_color":
                category_name = "【吉や】🎨新色入荷！"
                btn_label = "商品ページへ"
                color_code = "#007AFF" # ブルー（新色）
            elif status_type == "bargain":
                category_name = "【吉や】🉐特価品入荷！"
                btn_label = "商品ページへ"
                color_code = "#FF007F" # ネオンピンク（特価）
            elif status_type == "restock":
                category_name = "【吉や】🔥再入荷情報！"
                btn_label = "商品ページへ"
                color_code = "#E69D00" # オレンジ（再入荷）
            else:
                category_name = "【吉や】✨新入荷商品"
                btn_label = "商品ページへ"
                color_code = "#E60012" # レッド（新入荷）

            bubble = {
                "type": "bubble",
                "size": "kilo"
            }
            
            if item.get("img_url"):
                bubble["hero"] = {
                    "type": "image",
                    "url": item["img_url"],
                    "size": "full",
                    "aspectRatio": "4:3",
                    "aspectMode": "cover"
                }

            header_contents = [
                {
                    "type": "text",
                    "text": category_name,
                    "weight": "bold",
                    "color": color_code,
                    "size": "xs",
                    "flex": 1
                }
            ]
            if KITIYA_LOGO_URL:
                header_contents.append({
                    "type": "image",
                    "url": KITIYA_LOGO_URL,
                    "size": "xxs",
                    "aspectMode": "fit",
                    "flex": 0,
                    "margin": "sm"
                })

            bubble["body"] = {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": header_contents,
                        "alignItems": "center"
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

            if item.get("price"):
                bubble["body"]["contents"].append({
                    "type": "text",
                    "text": f"価格: {item['price']}",
                    "size": "xs",
                    "color": "#111111",
                    "weight": "bold",
                    "margin": "xs"
                })

            bubble["footer"] = {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": btn_label,
                            "uri": item["url"]
                        },
                        "style": "primary",
                        "color": color_code
                    }
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
    print("スクレイピング処理を開始します...")
    init_db()

    initial_run = is_initial_run()
    if initial_run:
        print("初回実行を検知しました。データベースの構築のみ行い、LINE通知はスキップします。")

    blog_updates = check_blog_updates(initial_run)
    product_updates = check_product_updates(initial_run)

    all_updates = blog_updates + product_updates

    if initial_run:
        print("初回データベース構築が完了しました。")
    elif all_updates:
        print(f"新しい更新を {len(all_updates)} 件検知しました。")
        send_line_carousel(all_updates)
    else:
        print("確実な新規・再入荷情報はありませんでした。")

if __name__ == "__main__":
    main()
