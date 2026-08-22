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
    """HTMLタグ・文字列として埋め込まれたimgタグ・改行を完全に除去"""
    if not text_or_elem:
        return ""
    
    if hasattr(text_or_elem, 'get_text'):
        soup_copy = BeautifulSoup(str(text_or_elem), "html.parser")
        for img in soup_copy.find_all("img"):
            img.decompose()
        text = soup_copy.get_text(strip=True)
    else:
        text = str(text_or_elem)

    # 文字列として混入している <img ... > を強力に消去
    text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def test_scrape_and_print_titles():
    """商品一覧ページから正確に商品のみを取得してログ表示するテスト関数"""
    print("--- [商品名クレンジング確認テスト開始] ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TROUT_BASE_URL, wait_until="networkidle")
        soup = BeautifulSoup(page.content(), "html.parser")

        # 1. pid= を含む商品詳細リンクをすべて抽出
        all_pid_links = soup.find_all("a", href=lambda h: h and "pid=" in h)
        
        # 2. 親要素から商品枠を特定してカテゴリリンクを除外
        items_found = []
        for link in all_pid_links:
            title_text = clean_title_text(link)
            # 文字数が極端に短いものや画像のみのリンクをスキップ
            if not title_text or len(title_text) < 2:
                continue
            
            # 親要素を取得して重複防止
            parent = link.find_parent("li") or link.find_parent("div")
            if parent and parent not in items_found:
                items_found.append((link, parent))

        # 3. 取得した商品（先頭5件）を表示
        for idx, (a_tag, parent) in enumerate(items_found[:5], 1):
            raw_title = a_tag.get_text(strip=True)
            cleaned_title = clean_title_text(a_tag)
            print(f"商品{idx}:")
            print(f"  [修正前]: {raw_title[:60]}")
            print(f"  [修正後]: {cleaned_title}")
            print("-" * 40)

        browser.close()
    print("--- [テスト終了] ---")

def main():
    test_scrape_and_print_titles()

if __name__ == "__main__":
    main()
