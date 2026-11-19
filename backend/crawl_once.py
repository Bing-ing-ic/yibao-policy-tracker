# -*- coding: utf-8 -*-
"""命令行一次性全量抓取（也可由后端定时任务 / 网页按钮触发）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import database, crawler

if __name__ == "__main__":
    database.init_db()
    result = crawler.run_all()
    print("抓取完成：", result)
