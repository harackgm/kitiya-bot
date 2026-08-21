name: Kitiya Monitor Bot

on:
  schedule:
    # 毎日 日本時間 8:00, 12:00, 18:00 の3回自動実行（UTC指定）
    - cron: '0 23,3,9 * * *'
  workflow_dispatch: # 手動実行ボタンを有効化

jobs:
  scrape-and-notify:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout Repository
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        playwright install chromium

    # 前回のSQLiteデータベースをキャッシュから復元
    - name: Restore SQLite DB Cache
      uses: actions/cache/restore@v4
      with:
        path: kitiya_data.db
        key: sqlite-db-${{ github.run_id }}
        restore-keys: |
          sqlite-db-

    # 本番実行コマンド
    - name: Run Monitor Script
      env:
        LINE_ACCESS_TOKEN: ${{ secrets.LINE_ACCESS_TOKEN }}
        LINE_USER_ID: ${{ secrets.LINE_USER_ID }}
      run: python kitiya_monitor.py

    # 更新されたSQLiteデータベースをキャッシュとして保存
    - name: Save SQLite DB Cache
      uses: actions/cache/save@v4
      if: always()
      with:
        path: kitiya_data.db
        key: sqlite-db-${{ github.run_id }}
