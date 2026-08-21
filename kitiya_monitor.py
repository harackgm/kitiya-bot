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
TROUT_CAT_URL = "https://www.kitiya.jp/?mode=cate&cbid=2590067&csid=0&sort=n"

DB_FILE = "kitiya_data.db"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notified_items (
            url TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            is_soldout INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def get_stored_items(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT url, is_soldout FROM notified_items")
    return {row[0]: row[1] for row in cursor.fetchall()}


def save_or_update_item(conn, item):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO notified_items (url, title, category, is_soldout)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            is_soldout=excluded.is_soldout
    """, (item["url"], item["title"], item.get("category", "blog"), 1 if item.get("is_soldout") else 0))
    conn.commit()


def send_line_carousel(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    bubbles = []
    for item in items:
        status_type = item.get("status_type", "new")
        
        if item.get("category") == "blog":
            category_name = "【吉や】ブログ更新"
            btn_label = "記事を読む"
        elif status_type == "restock":
            category_name = "【吉や】🔥再入荷情報！"
            btn_label = "商品ページへ"
        else:
            category_name = "【吉や】✨新入荷商品"
            btn_label = "商品ページへ"

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
                    "color": "#1DB446" if status_type != "restock" else "#E60012",
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
                    "color": "#00B900" if status_type != "restock" else "#E60012"
                }
            ]
        }

        bubbles.append(bubble)

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": f"【吉や】更新情報（{len(items)}件）",
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
        print(f"LINE通知完了: {len(items)} 件")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


def scrape_blog(page):
    items = []
    try:
        page.goto(BLOG_URL, wait_until="networkidle", timeout=60000)
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
                        "category": "blog",
                        "is_soldout": False
                    })
    except Exception as e:
        print(f"ブログ取得エラー: {e}")
    return items


def scrape_products_all_pages(page):
    all_items = []
    first_page_url = TROUT_CAT_URL
    print(f"商品一覧 1 ページ目にアクセス中...")
    
    try:
        # 完全読み込み（networkidle）を指定して待ち時間を確保
        page.goto(first_page_url, wait_until="networkidle", timeout=60000)
        time.sleep(3)
        soup = BeautifulSoup(page.content(), "html.parser")
        
        # デバッグ用情報（抽出失敗時にリンク傾向を調査）
        all_links = [a["href"] for a in soup.find_all("a", href=True)]
        print(f"[DEBUG] 検出された総リンク数: {len(all_links)}")
        sample_links = [l for l in all_links if "kitiya" in l or "mode=" in l or "pid=" in l or "page=" in l][:10]
        print(f"[DEBUG] サンプルリンク: {sample_links}")

        # 総ページ数の判別
        max_page = 1
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"page=(\d+)", href)
            if m:
                p_num = int(m.group(1))
                if p_num > max_page:
                    max_page = p_num

        print(f"検出された総ページ数: {max_page} ページ")

        for current_p in range(1, max_page + 1):
            if current_p == 1:
                p_soup = soup
            else:
                target_url = f"{TROUT_CAT_URL}&page={current_p}"
                print(f"商品一覧 {current_p}/{max_page} ページ目を処理中...")
                page.goto(target_url, wait_until="networkidle", timeout=60000)
                time.sleep(2)
                p_soup = BeautifulSoup(page.content(), "html.parser")

            # 全てのリンクから商品っぽいリンクを抽出
            for a_tag in p_soup.find_all("a", href=True):
                href = a_tag["href"]
                # ドメイン直下の別ページや問い合わせ等の除外
                if href in ["#", "/"] or "javascript:" in href or "mode=cate" in href or "mode=sk" in href or "apps/note" in href:
                    continue

                full_url = urljoin("https://www.kitiya.jp/", href)

                parent = a_tag.find_parent("li") or a_tag.find_parent("div") or a_tag.find_parent("td")
                
                img_tag = a_tag.find("img") or (parent.find("img") if parent else None)
                title = img_tag.get("alt", "") if img_tag else ""
                if not title and parent:
                    title = parent.get_text(separator=" ", strip=True)

                if not title or len(title) < 2 or "カート" in title or "詳細" in title or "マイアカウント" in title:
                    continue

                clean_title = title.split("円")[0].strip() if "円" in title else title
                clean_title = clean_title[:60]

                img_url = ""
                if img_tag:
                    src = img_tag.get("src") or img_tag.get("data-src") or ""
                    if src:
                        img_url = urljoin("https://www.kitiya.jp/", src).replace("http://", "https://")

                price = ""
                is_soldout = False
                if parent:
                    parent_text = parent.get_text()
                    if "円" in parent_text:
                        m = re.search(r'[\d,]+円', parent_text)
                        if m:
                            price = m.group(0)
                    
                    if "SOLDOUT" in parent_text.upper() or "売り切れ" in parent_text or "SOLD OUT" in parent_text.upper():
                        is_soldout = True

                if not any(i["url"] == full_url for i in all_items):
                    all_items.append({
                        "title": clean_title,
                        "url": full_url,
                        "img_url": img_url,
                        "price": price,
                        "category": "product",
                        "is_soldout": is_soldout
                    })

    except Exception as e:
        print(f"商品スクレイピングエラー: {e}")

    return all_items


def main():
    conn = init_db()
    stored_items = get_stored_items(conn)
    is_first_run = len(stored_items) == 0

    if is_first_run:
        print("【初回実行】DBが空のため全登録を行います（通知はスキップ）。")

    print("ブラウザを起動して処理を開始します...")

    all_scraped_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja,ja-JP;q=0.9"}
        )
        page = context.new_page()

        # 1. ブログ取得
        blog_items = scrape_blog(page)
        print(f"ブログ: {len(blog_items)} 件")
        all_scraped_items.extend(blog_items)

        # 2. 商品全ページ取得
        product_items = scrape_products_all_pages(page)
        print(f"商品全ページ: {len(product_items)} 件")
        all_scraped_items.extend(product_items)

        browser.close()

    print(f"合計 {len(all_scraped_items)} 件のデータをデータベースと照合します。")

    if is_first_run:
        for item in all_scraped_items:
            save_or_update_item(conn, item)
        print(f"初回登録完了: {len(all_scraped_items)} 件をDBに保存しました（LINE通知はスキップ）。")
    else:
        notify_items = []

        for item in all_scraped_items:
            url = item["url"]
            is_soldout = item["is_soldout"]

            if url not in stored_items:
                if not is_soldout:
                    item["status_type"] = "new"
                    notify_items.append(item)
                save_or_update_item(conn, item)
            else:
                prev_soldout = stored_items[url]
                if prev_soldout == 1 and not is_soldout:
                    print(f"🔥 再入荷検知: {item['title']}")
                    item["status_type"] = "restock"
                    notify_items.append(item)
                    save_or_update_item(conn, item)
                elif prev_soldout != (1 if is_soldout else 0):
                    save_or_update_item(conn, item)

        if notify_items:
            print(f"新着・再入荷通知対象: {len(notify_items)} 件")
            send_line_carousel(notify_items[:10])
        else:
            print("新着・再入荷の更新はありませんでした。")

    conn.close()


if __name__ == "__main__":
    main()
