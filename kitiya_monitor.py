import os
import sqlite3
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
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

    # ブログ記事テーブル
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_posts (
            url TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # 商品テーブル（在庫状態も管理）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT,
            price TEXT,
            is_sold_out INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()


# --- スクレイピング処理 ---
def check_blog_updates():
    """ブログの更新チェック"""
    new_items = []
    try:
        response = requests.get(BLOG_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # 記事要素の抽出（サイト構造に合わせ調整）
        articles = soup.select("article, .post-list-item, .entry")
        for article in articles[:5]:  # 最新5件をチェック
            title_tag = article.select_one("h2 a, .entry-title a, a")
            if not title_tag or not title_tag.get("href"):
                continue

            title = title_tag.get_text(strip=True)
            url = urljoin(BLOG_URL, title_tag["href"])

            img_tag = article.select_one("img")
            img_url = (
                urljoin(BLOG_URL, img_tag["src"])
                if img_tag and img_tag.get("src")
                else ""
            )

            # DB存在確認
            cursor.execute(
                "SELECT url FROM blog_posts WHERE url = ?", (url,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO blog_posts (url, title) VALUES (?, ?)",
                    (url, title),
                )
                new_items.append(
                    {
                        "title": title,
                        "url": url,
                        "img_url": img_url,
                        "category": "blog",
                        "status_type": "new",
                    }
                )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ブログスクレイピングエラー: {e}")

    return new_items


def check_product_updates():
    """商品ページの更新チェック（Playwright使用）"""
    new_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(TROUT_BASE_URL, wait_until="networkidle")
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # 商品要素の抽出
            product_list = soup.select(
                ".product_item, .product-list-item, li.item"
            )

            for item in product_list:
                title_tag = item.select_one(".product_name, .name a, a")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = urljoin(
                    TROUT_BASE_URL,
                    title_tag.get("href") if title_tag.name == "a" else "",
                )
                if not url or url == TROUT_BASE_URL:
                    a_tag = item.select_one("a")
                    if a_tag and a_tag.get("href"):
                        url = urljoin(TROUT_BASE_URL, a_tag["href"])

                price_tag = item.select_one(".product_price, .price")
                price = (
                    price_tag.get_text(strip=True) if price_tag else "価格不詳"
                )

                img_tag = item.select_one("img")
                img_url = (
                    urljoin(TROUT_BASE_URL, img_tag["src"])
                    if img_tag and img_tag.get("src")
                    else ""
                )

                # 売り切れ判定
                item_text = item.get_text()
                is_sold_out = 1 if "SOLD OUT" in item_text.upper() else 0

                cursor.execute(
                    "SELECT is_sold_out FROM products WHERE url = ?", (url,)
                )
                row = cursor.fetchone()

                if row is None:
                    # 完全新規商品（在庫ありの場合のみ通知）
                    cursor.execute(
                        "INSERT INTO products (url, title, price, is_sold_out) VALUES (?, ?, ?, ?)",
                        (url, title, price, is_sold_out),
                    )
                    if not is_sold_out:
                        new_items.append(
                            {
                                "title": title,
                                "url": url,
                                "img_url": img_url,
                                "price": price,
                                "category": "product",
                                "status_type": "new",
                            }
                        )
                else:
                    # 状態更新（SOLDOUT -> 在庫あり への再入荷判定）
                    old_sold_out = row[0]
                    if old_sold_out == 1 and is_sold_out == 0:
                        new_items.append(
                            {
                                "title": title,
                                "url": url,
                                "img_url": img_url,
                                "price": price,
                                "category": "product",
                                "status_type": "restock",
                            }
                        )
                    cursor.execute(
                        "UPDATE products SET is_sold_out = ?, price = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?",
                        (is_sold_out, price, url),
                    )

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"商品スクレイピングエラー: {e}")
        finally:
            browser.close()

    return new_items


# --- LINE通知処理 ---
def send_line_carousel(items):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEの設定情報（トークン/ID）が見つかりません。")
        return

    if not items:
        return

    # LINE Flex Carouselの制限（最大10件）ごとに分割送信
    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        bubbles = []

        for item in chunk:
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

            bubble = {"type": "bubble", "size": "kilo"}

            if item.get("img_url"):
                bubble["hero"] = {
                    "type": "image",
                    "url": item["img_url"],
                    "size": "full",
                    "aspectRatio": "4:3",
                    "aspectMode": "cover",
                }

            bubble["body"] = {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": category_name,
                        "weight": "bold",
                        "color": (
                            "#1DB446"
                            if status_type != "restock"
                            else "#E60012"
                        ),
                        "size": "xs",
                    },
                    {
                        "type": "text",
                        "text": item["title"],
                        "weight": "bold",
                        "size": "sm",
                        "wrap": True,
                        "margin": "sm",
                        "maxLines": 3,
                    },
                ],
            }

            if item.get("price"):
                bubble["body"]["contents"].append(
                    {
                        "type": "text",
                        "text": f"価格: {item['price']}",
                        "size": "xs",
                        "color": "#111111",
                        "weight": "bold",
                        "margin": "xs",
                    }
                )

            bubble["footer"] = {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": btn_label,
                            "uri": item["url"],
                        },
                        "style": "primary",
                        "color": (
                            "#00B900"
                            if status_type != "restock"
                            else "#E60012"
                        ),
                    }
                ],
            }

            bubbles.append(bubble)

        payload = {
            "to": LINE_USER_ID,
            "messages": [
                {
                    "type": "flex",
                    "altText": f"【吉や】更新情報（{len(chunk)}件）",
                    "contents": {"type": "carousel", "contents": bubbles},
                }
            ],
        }

        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        }

        try:
            res = requests.post(
                url, headers=headers, json=payload, timeout=10
            )
            res.raise_for_status()
            print(f"LINE通知完了: {len(chunk)} 件")
        except Exception as e:
            print(f"LINE通知エラー: {e}")


# --- 実行エントリーポイント ---
def main():
    print("🚀 スクレイピング処理を開始します...")
    init_db()

    blog_updates = check_blog_updates()
    product_updates = check_product_updates()

    all_updates = blog_updates + product_updates

    if all_updates:
        print(f"📢 新しい更新を {len(all_updates)} 件検知しました。")
        send_line_carousel(all_updates)
    else:
        print("確実な新規・再入荷情報はありませんでした。")


if __name__ == "__main__":
    main()
