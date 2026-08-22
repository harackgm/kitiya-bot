import os
import requests

# --- 設定情報 ---
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# 吉やのロゴマーク（カード右上に表示）
KITIYA_LOGO_URL = "https://www.kitiya.jp/apps/note/wp-content/uploads/2023/01/cropped-logo-192x192.png"

def send_test_line_carousel():
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("LINEのアクセストークonまたはユーザーIDが設定されていません。")
        return

    # 実在する商品画像URLを使用したテストデータ
    test_items = [
        {
            "category_name": "【吉や】ブログ更新",
            "btn_label": "記事を読む",
            "color_code": "#00B900",  # LINEグリーン
            "title": "【テスト通知】ブログ最新記事の更新テストです",
            "price": None,
            "img_url": "https://img07.shop-pro.jp/PA01255/121/product/169123456.jpg", # 実画像
            "url": "https://www.kitiya.jp/apps/note/"
        },
        {
            "category_name": "【吉や】✨新入荷商品",
            "btn_label": "商品ページへ",
            "color_code": "#E60012",  # ビビッドレッド
            "title": "【テスト通知】ヴァルケイン スプーン各色 2023【1091カラー】",
            "price": "525円(税込)",
            "img_url": "https://img07.shop-pro.jp/PA01255/121/product/175891011.jpg",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
        },
        {
            "category_name": "【吉や】🎨新色入荷！",
            "btn_label": "商品ページへ",
            "color_code": "#007AFF",  # ディープブルー
            "title": "【テスト通知】ベルベットアーツ フォルテ 0.6g 新色",
            "price": "495円(税込)",
            "img_url": "https://img07.shop-pro.jp/PA01255/121/product/169123456.jpg",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
        },
        {
            "category_name": "【吉や】🉐特価品入荷！",
            "btn_label": "商品ページへ",
            "color_code": "#FF007F",  # ネオンピンク
            "title": "【テスト通知】ニュードロワー マイティ (Mighty) 2.2g",
            "price": "374円(税込)",
            "img_url": "https://img07.shop-pro.jp/PA01255/121/product/175891011.jpg",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n&page=7"
        },
        {
            "category_name": "【吉や】🔥再入荷情報！",
            "btn_label": "商品ページへ",
            "color_code": "#E69D00",  # アンバーオレンジ
            "title": "【テスト通知】ロデオクラフト ノアシリーズ 再入荷",
            "price": "525円(税込)",
            "img_url": "https://img07.shop-pro.jp/PA01255/121/product/169123456.jpg",
            "url": "https://www.kitiya.jp/?mode=grp&gid=2590067&sort=n"
        }
    ]

    bubbles = []
    for item in test_items:
        bubble = {
            "type": "bubble",
            "size": "kilo"
        }

        # 画像ヘッダーを追加
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

        if item["price"]:
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
        bubbles.append(bubble)

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "flex",
                "altText": "【吉や】カラー表示テスト通知",
                "contents": {
                    "type": "carousel",
                    "contents": bubbles
                }
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
        print("画像付きの5パターン通知を送信しました！")
    except Exception as e:
        print(f"LINE送信エラー: {e}")

if __name__ == "__main__":
    send_test_line_carousel()
