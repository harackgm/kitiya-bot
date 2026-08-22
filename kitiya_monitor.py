import os
import sys
import sqlite3
import requests
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定情報 ---
TROUT_BASE_URL = "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"

# --- クレンジング処理 ---
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
    
    # New Arrivals / Re Arrivals などの余計なマーク文言を強力に消去
    text = re.sub(r'^(New\s*Arrivals|Re\s*Arrivals|新入荷|再入荷|SALE|新色)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def test_scrape_and_print_titles():
    """最終確認用テスト関数"""
    print("\n==========================================")
    print("【最終クレンジングテスト実行】")
    print("==========================================\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
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

        for idx, (a_tag, parent) in enumerate(items_found[:5], 1):
            raw_title = a_tag.get_text(strip=True)
            cleaned_title = clean_title_text(a_tag)
            print(f"商品 {idx}:")
            print(f"  [修正前]: {raw_title[:60]}")
            print(f"  [修正後（完成形）]: {cleaned_title}")
            print("-" * 50)

        browser.close()
    print("\n==========================================")
    print("テスト完了。ログをご確認ください。")
    print("==========================================\n")

def main():
    test_scrape_and_print_titles()

if __name__ == "__main__":
    main()
