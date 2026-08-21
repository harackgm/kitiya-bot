import os
import sqlite3
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_URL = "https://www.kitiya.jp/apps/note/"
PRODUCTS_URL_P1 = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
PRODUCTS_URL_P2 = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n&page=2"

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

        # 商品情報で価格がある場合は追加表示
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


def scrape_products(page, url):
    """商品新着一覧（1・2ページ目）のスクレイピング"""
    items = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        soup = BeautifulSoup(page.content(), "html.parser")

        # カラーズ（Colorme）標準の商品セル/リンクを取得
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "?pid=" in href:
                full_url = urljoin("https://www.kitiya.jp/", href)

                # 商品名と画像の抽出
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

                # 親要素から価格の取得を試みる
                price = ""
                parent = a_tag.find_parent("li") or a_tag.find_parent("div")
                if parent:
                    price_text = parent.get_text()
                    if "円" in price_text:
                        import re
                        m = re.search(r'[\d,]+円', price_text)
                        if m:
                            price = m.group(0)

                if not any(i["url"] == full_url for i in items):
                    items.append({
                        "title": title[:60],
                        "url": full_url,
                        "img_url": img_url,
                        "price": price,
                        "category": "product"
                    })
    except Exception as e:
        print(f"商品一覧スクレイピングエラー: {e}")
    return items


def main():
    conn = init_db()
    stored_urls = get_stored_urls(conn)
    is_first_run = len(stored_urls) == 0

    if is_first_run:
        print("【初回実行】DBが空のため全件登録のみ行います（通知なし）。")

    print("ブラウザを起動して『入荷ブログ』および『商品新着一覧（P1, P2）』へアクセス中...")

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

        # 2. 商品新着一覧 P1 取得
        p1_items = scrape_products(page, PRODUCTS_URL_P1)
        print(f"商品一覧(1ページ目)から {len(p1_items)} 件取得")
        all_scraped_items.extend(p1_items)

        # 3. 商品新着一覧 P2 取得
        p2_items = scrape_products(page, PRODUCTS_URL_P2)
        print(f"商品一覧(2ページ目)から {len(p2_items)} 件取得")
        all_scraped_items.extend(p2_items)

        browser.close()

    print(f"合計 {len(all_scraped_items)} 件のデータをチェックします。")

    if is_first_run:
        save_urls(conn, all_scraped_items)
        print(f"初回処理完了: {len(all_scraped_items)} 件のURLをDBに保存しました（LINE通知はスキップ）。")
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
