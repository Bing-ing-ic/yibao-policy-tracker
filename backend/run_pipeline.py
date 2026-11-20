# -*- coding: utf-8 -*-
"""一键流水线：初始化库 → 抓取政策与曝光 → 规则解读 → 导出静态 JSON。

供 GitHub Actions 定时任务与本机手动复跑使用：
    在 backend/ 目录下：python run_pipeline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import database, crawler, export_static, seed


def main():
    database.init_db()
    result = crawler.run_all()
    print("抓取完成：", result)
    # 自动抓取之后并入人工确认有效的种子条目（只补缺、不覆盖已有）
    conn = database.get_conn()
    try:
        seed.apply_seed(conn)
    finally:
        conn.close()
    export_static.export()


if __name__ == "__main__":
    main()
