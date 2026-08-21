import os
import sqlite3
import requests
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_URL = "https://www.kitiya.jp/apps/note/"
# トラウトカテゴリー（新着順・全ページ巡回対象）
TROUT_CAT_URL = "https://www.kitiya.jp/?mode=cate&cbid=2590067&csid=0&sort=n"

DB_FILE = "kitiya_data.db"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notified_items (
            url TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def get_stored_urls(conn):
    """DBに保存済みのURLを取得"""
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM notified_items")
    return set(row[0] for row in cursor.fetchall())


def save_urls(conn, items):
    """新しく検知したURLをDBに保存"""
    cursor = conn.cursor()
    for item in items:
        cursor.execute(
            "INSERT OR IGNORE INTO notified_items (url, title, category) VALUES (?, ?, ?)",
            (item["url"], item["title"], item.get("category", "blog"))
        )
    conn.commit()


def send_line_carousel(items):
    """新着情報をLINEカルーセル形式で送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    bubbles = []
    for item in items:
        category_name = "【吉や】ブログ更新" if item.get("category") == "blog" else "【吉や】入荷・再入荷商品"
        btn_label = "記事を読む" if item.get("category") == "blog" else "商品ページへ"

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

        bubble["body"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": category_name,
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

        if item.get("price"):
            bubble["body"]["contents"].append({
                "type": "text",
                "text": f"価格: {item['price']}",
                "size": "xs",
                "color": "#e60012",
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
                "altText": f"【吉や】新着更新情報（{len(items)}件）",
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
        print(f"新着 {len(items)} 件の通知送信に成功しました！")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def scrape_blog(page):
    """ブログ一覧のスクレイピング"""
    items = []
    try:
        page.goto(BLOG_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        soup = BeautifulSoup(page.content(), "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/apps/note/archives/" in href and not "/tag/" in href:
                full_url = urljoin(BLOG_URL, href)
                text = a_tag.get_text(separator=" ", strip=True)
                if not text or len(text) < 5:
                    parent_text = a_tag.parent.get_text(separator=" ", strip=True) if a_tag.parent else ""
                    text = parent_text if parent_text else "最新入荷ブログ"

                clean_text = text.replace("SNS", "").strip()
                if len(clean_text) > 60:
                    clean_text = clean_text[:57] + "..."

                img_tag = a_tag.find("img") or (a_tag.parent.find("img") if a_tag.parent else None)
                img_url = ""
                if img_tag:
                    src = img_tag.get("src") or img_tag.get("data-src") or ""
                    if src:
                        img_url = urljoin(BLOG_URL, src).replace("http://", "https://")

                if not any(i["url"] == full_url for i in items):
                    items.append({
                        "title": clean_text,
                        "url": full_url,
                        "img_url": img_url,
                        "category": "blog"
                    })
    except Exception as e:
        print(f"ブログスクレイピングエラー: {e}")
    return items


def scrape_products_all_pages(page):
    """トラウトカテゴリーの全ページ（最大ページ数を自動判別）を巡回スクレイピング"""
    all_items = []
    
    # まず1ページ目にアクセスして最大ページ数を取得
    first_page_url = TROUT_CAT_URL
    print(f"商品一覧 1 ページ目にアクセス中: {first_page_url}")
    
    try:
        page.goto(first_page_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        soup = BeautifulSoup(page.content(), "html.parser")
        
        # ページネーションから最大ページ数を検出
        max_page = 1
        page_links = soup.find_all("a", href=re.compile(r"page=\d+"))
        for p_link in page_links:
            m = re.search(r"page=(\d+)", p_link["href"])
            if m:
                p_num = int(m.group(1))
                if p_num > max_page:
                    max_page = p_num

        print(f"検出された総ページ数: {max_page} ページ")

        # 1ページ目から順番に巡回
        for current_p in range(1, max_page + 1):
            if current_p == 1:
                p_soup = soup
            else:
                target_url = f"{TROUT_CAT_URL}&page={current_p}"
                print(f"商品一覧 {current_p}/{max_page} ページ目を処理中...")
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(1.5)  # サーバー負荷軽減のウェイト
                p_soup = BeautifulSoup(page.content(), "html.parser")

            # 商品要素の抽出
            for a_tag in p_soup.find_all("a", href=True):
                href = a_tag["href"]
                if "?pid=" in href:
                    full_url = urljoin("https://www.kitiya.jp/", href)

                    img_tag = a_tag.find("img")
                    title = img_tag.get("alt", "") if img_tag else ""
                    if not title:
                        title = a_tag.get_text(strip=True)

                    if not title or len(title) < 3:
                        continue

                    img_url = ""
                    if img_tag:
                        src = img_tag.get("src") or ""
                        if src:
                            img_url = urljoin("https://www.kitiya.jp/", src).replace("http://", "https://")

                    price = ""
                    parent = a_tag.find_parent("li") or a_tag.find_parent("div")
                    if parent:
                        price_text = parent.get_text()
                        if "円" in price_text:
                            m = re.search(r'[\d,]+円', price_text)
                            if m:
                                price = m.group(0)

                    if not any(i["url"] == full_url for i in all_items):
                        all_items.append({
                            "title": title[:60],
                            "url": full_url,
                            "img_url": img_url,
                            "price": price,
                            "category": "product"
                        })

    except Exception as e:
        print(f"商品全ページスクレイピングエラー: {e}")

    return all_items


def main():
    conn = init_db()
    stored_urls = get_stored_urls(conn)
    is_first_run = len(stored_urls) == 0

    if is_first_run:
        print("【初回実行】DBが空のため全商品・全ブログ記事の初回登録を行います（LINE通知はスキップ）。")

    print("ブラウザを起動して『入荷ブログ』および『トラウト全商品ページ』へアクセス中...")

    all_scraped_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja,ja-JP;q=0.9"}
        )
        page = context.new_page()

        # 1. ブログ記事取得
        blog_items = scrape_blog(page)
        print(f"ブログから {len(blog_items)} 件取得")
        all_scraped_items.extend(blog_items)

        # 2. トラウト全ページ取得
        product_items = scrape_products_all_pages(page)
        print(f"トラウト全ページから {len(product_items)} 件の商品を取得")
        all_scraped_items.extend(product_items)

        browser.close()

    print(f"合計 {len(all_scraped_items)} 件のデータをデータベースと照合します。")

    if is_first_run:
        save_urls(conn, all_scraped_items)
        print(f"初回処理完了: {len(all_scraped_items)} 件のURLをDBに一括保存しました（LINE通知はスキップ）。")
    else:
        new_items = [item for item in all_scraped_items if item["url"] not in stored_urls]

        if new_items:
            print(f"新着更新を {len(new_items)} 件検出しました！")
            send_line_carousel(new_items[:10])
            save_urls(conn, new_items)
        else:
            print("新着・再入荷の更新はありませんでした。")

    conn.close()


if __name__ == "__main__":
    main()
