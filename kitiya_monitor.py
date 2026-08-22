import os
import requests
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
BLOG_URL = "https://www.kitiya.jp/apps/note/"
TROUT_BASE_URL = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
KITIYA_LOGO_URL = "https://www.kitiya.jp/apps/note/wp-content/uploads/2023/01/cropped-logo-192x192.png"

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# --- 画像クレンジング関数 ---
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

# --- 個別LINE送信（単発通知用） ---
def send_single_card(item):
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
            "text": item["category_name"],
            "weight": "bold",
            "color": item["color_code"],
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

    body_contents = [
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

    if item.get("price"):
        body_contents.append({
            "type": "text",
            "text": f"価格: {item['price']}",
            "size": "xs",
            "color": "#111111",
            "weight": "bold",
            "margin": "xs"
        })

    bubble["body"] = {
        "type": "box",
        "layout": "vertical",
        "contents": body_contents
    }

    bubble["footer"] = {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "button",
                "action": {
                    "type": "uri",
                    "label": item["btn_label"],
                    "uri": item["url"]
                },
                "style": "primary",
                "color": item["color_code"]
            }
        ]
    }

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": f"{item['category_name']} テスト通知",
                "contents": bubble
            }
        ]
    }

    try:
        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
            },
            json=payload,
            timeout=10
        )
        res.raise_for_status()
        print(f"送信成功: {item['category_name']}")
    except Exception as e:
        print(f"送信失敗 ({item['category_name']}): {e}")

# --- メインテスト処理 ---
def main():
    print("吉やサイトから本物のデータを取得して5パターンの通知テストを開始します...")

    # 1. ブログデータ取得
    blog_url = BLOG_URL
    blog_title = "ブログ最新記事"
    blog_img = ""
    try:
        res = requests.get(BLOG_URL, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        article = soup.select_one("article, .post, .entry")
        if article:
            a_tag = article.find("a", href=lambda h: h and "archives" in h)
            if a_tag:
                blog_url = urljoin(BLOG_URL, a_tag["href"])
                blog_title = a_tag.get_text(strip=True) or blog_title
            img_tag = article.select_one("img")
            blog_img = clean_image_url(img_tag, BLOG_URL)
    except Exception as e:
        print(f"ブログ取得エラー: {e}")

    # 2. 商品データ取得（Playwright使用）[cite: 1]
    products = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TROUT_BASE_URL, wait_until="networkidle")
        soup = BeautifulSoup(page.content(), "html.parser")
        
        main_area = soup.select_one("#main, .main_content, .product_list, .item_list") or soup
        item_links = main_area.find_all("a", href=lambda h: h and "pid=" in h)
        
        seen = set()
        for link in item_links:
            href = link.get("href")
            full_url = urljoin(TROUT_BASE_URL, href)
            if full_url not in seen:
                seen.add(full_url)
                parent = link.find_parent("li") or link.find_parent("div") or link.parent
                
                title = link.get_text(strip=True) or "テスト商品"
                price_match = re.search(r"[\d,]+\s*円", parent.get_text() if parent else "")
                price = price_match.group(0) if price_match else "525円(税込)"
                
                img_tag = parent.select_one("img") if parent else None
                img_url = clean_image_url(img_tag, TROUT_BASE_URL)
                
                products.append({"title": title, "url": full_url, "img_url": img_url, "price": price})
                if len(products) >= 4:
                    break
        browser.close()

    # ダミー補填用（商品が不足していた場合）
    def get_p(idx):
        if idx < len(products):
            return products[idx]
        return {"title": "【テスト商品】ロデオクラフト ノア", "url": TROUT_BASE_URL, "img_url": KITIYA_LOGO_URL, "price": "525円(税込)"}

    p0 = get_p(0)
    p1 = get_p(1)
    p2 = get_p(2)
    p3 = get_p(3)

    # 指定された5つの配色・タイトルパターンで1件ずつ構築
    test_cards = [
        # ① ブログ更新
        {
            "category_name": "【吉や】ブログ更新",
            "btn_label": "記事を読む",
            "color_code": "#00B900",  # LINEグリーン
            "title": blog_title,
            "price": None,
            "url": blog_url,
            "img_url": blog_img or KITIYA_LOGO_URL
        },
        # ② 新入荷
        {
            "category_name": "【吉や】✨新入荷商品",
            "btn_label": "商品ページへ",
            "color_code": "#E60012",  # ビビッドレッド
            "title": p0["title"],
            "price": p0["price"],
            "url": p0["url"],
            "img_url": p0["img_url"]
        },
        # ③ 新色入荷
        {
            "category_name": "【吉や】🎨新色入荷！",
            "btn_label": "商品ページへ",
            "color_code": "#007AFF",  # ディープブルー
            "title": p1["title"],
            "price": p1["price"],
            "url": p1["url"],
            "img_url": p1["img_url"]
        },
        # ④ 特価品
        {
            "category_name": "【吉や】🉐特価品入荷！",
            "btn_label": "商品ページへ",
            "color_code": "#FF007F",  # ネオンピンク
            "title": p2["title"],
            "price": p2["price"],
            "url": p2["url"],
            "img_url": p2["img_url"]
        },
        # ⑤ 再入荷
        {
            "category_name": "【吉や】🔥再入荷情報！",
            "btn_label": "商品ページへ",
            "color_code": "#E69D00",  # アンバーオレンジ
            "title": p3["title"],
            "price": p3["price"],
            "url": p3["url"],
            "img_url": p3["img_url"]
        }
    ]

    # 1件ずつ順番にLINEへ送信
    for card in test_cards:
        send_single_card(card)

if __name__ == "__main__":
    main()
