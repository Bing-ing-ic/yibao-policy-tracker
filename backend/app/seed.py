# -*- coding: utf-8 -*-
"""人工补录种子合并。

背景：GitHub Actions runner 在云端网络，个别国内医保站点当轮超时 / 解析失败，
导致部分人工确认有效的条目没有被自动抓回。这类条目随仓库以种子文件形式保留，
每轮流水线在自动抓取之后、导出之前按 URL 补缺合并：

- 自动抓取结果优先：库中已存在的条目，种子不覆盖、不更新；
- 种子只补缺：库中缺失的条目才插入（政策 + 其规则解读，曝光记录）；
- 种子文件：backend/data/manual_seed.json（随 git 入库，不依赖本机数据库）。

新增需要长期保留的漏抓条目时，向种子文件 policies / exposures 数组追加即可，
字段与数据表列保持一致。
"""
import json
import os

from . import config, analyzer

SEED_PATH = os.path.join(config.BACKEND_DIR, "data", "manual_seed.json")

# 写入 policies 表的基础列（解读信息走 analysis 表）。
_POLICY_COLS = ("level", "source_name", "column_key", "column_name", "title", "doc_no",
                "url", "publish_date", "summary", "content")
# 写入 exposures 表的列。
_EXPOSURE_COLS = ("level", "source_name", "kind", "org_name", "org_type", "region",
                  "problem", "penalty", "exit_status", "exit_type", "amount",
                  "publish_date", "title", "url", "summary")


def _load_seed():
    if not os.path.exists(SEED_PATH):
        return {"policies": [], "exposures": []}
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # 种子损坏不应阻断主流水线
        print(f"[SEED] 读取种子文件失败，跳过补录: {e!r}")
        return {"policies": [], "exposures": []}
    if not isinstance(data, dict):
        return {"policies": [], "exposures": []}
    return {
        "policies": data.get("policies") or [],
        "exposures": data.get("exposures") or [],
    }


def _upsert_policy(conn, item):
    url = (item.get("url") or "").strip()
    if not url:
        return False
    exists = conn.execute("SELECT id FROM policies WHERE url=?", (url,)).fetchone()
    if exists:
        return False  # 自动抓取已有，不覆盖

    cols = [c for c in _POLICY_COLS if item.get(c) is not None]
    vals = [item.get(c) for c in cols]
    placeholders = ",".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO policies ({','.join(cols)}) VALUES ({placeholders})", vals
    )
    policy_id = cur.lastrowid

    analysis = item.get("analysis") or {}
    if analysis:
        analyzer.save_analysis(conn, policy_id, analysis)
    return True


def _upsert_exposure(conn, item):
    url = (item.get("url") or "").strip()
    if not url:
        return False
    org_name = item.get("org_name")
    exists = conn.execute(
        "SELECT id FROM exposures WHERE url=? AND org_name=?", (url, org_name)
    ).fetchone()
    if exists:
        return False  # 自动抓取已有，不覆盖

    cols = [c for c in _EXPOSURE_COLS if item.get(c) is not None]
    vals = [item.get(c) for c in cols]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO exposures ({','.join(cols)}) VALUES ({placeholders})", vals
    )
    return True


def apply_seed(conn):
    """把种子条目并入数据库，返回补录条数。幂等：重复执行不会重复插入。"""
    seed = _load_seed()
    added_p = added_e = 0

    for item in seed["policies"]:
        try:
            if _upsert_policy(conn, item):
                added_p += 1
        except Exception as e:
            print(f"[SEED] 政策补录失败《{item.get('title')}》: {e!r}")

    for item in seed["exposures"]:
        try:
            if _upsert_exposure(conn, item):
                added_e += 1
        except Exception as e:
            print(f"[SEED] 曝光补录失败《{item.get('title')}》: {e!r}")

    conn.commit()
    if added_p or added_e:
        print(f"[SEED] 种子补录：政策 {added_p} 条、曝光 {added_e} 条")
    else:
        print("[SEED] 种子条目均已存在，无需补录")
    return {"policies": added_p, "exposures": added_e}
