# -*- coding: utf-8 -*-
"""把 SQLite 中的政策 / 解读 / 曝光数据导出为静态站点 JSON，供 GitHub Pages 纯前端读取。

用法（在 backend 目录下）：
    python -m app.export_static

产物写入 frontend/data/：
    policies.json        政策列表轻字段 + 解读摘要（首屏加载）
    policy_details.json  正文/落地动作/标准/关键数据（按 id 索引，抽屉按需加载）
    exposures.json       曝光台记录
    stats.json          层级统计与最新条目
    facets.json         栏目 / 主题标签分布
    exposure_stats.json 曝光台统计
"""
import json
import os

from . import config, database


def _j(v):
    try:
        return json.loads(v or "[]")
    except Exception:
        return []


# 详情包字段：仅在打开政策抽屉（原文 / 落地动作 / 待遇标准 / 关键数据）时按需加载，
# 不进入首屏列表包，以减小首屏下载体积。
_DETAIL_FIELDS = ("content", "actions", "standards", "key_data")
# 详情/对比/问答专用字段：首屏卡片、筛选、排序、KPI 与图表均不读取，
# 随详情包按 id 索引、按需懒加载，避免混入首屏列表包造成不必要的下载与解析。
_DETAIL_ONLY_FIELDS = (
    "impact_matrix", "key_points", "risks", "relevance_note", "parent_basis",
    "applicable_to", "policy_type", "core_elements", "city_impact", "impact_level",
)
# 前端未使用的冗余字段，导出时直接剔除，避免随包下发。
_DROP_FIELDS = ("content_hash", "status", "updated_at", "keywords")
# 需 JSON 解析的数组字段
_ARRAY_FIELDS = ("topic_tags", "applicable_to", "keywords", "key_points", "core_elements",
                 "actions", "risks", "standards", "impact_matrix", "key_data")


def _export_policies(conn):
    rows = conn.execute(
        """
        SELECT p.*,
               a.effective_date, a.relevance, a.relevance_note, a.key_points,
               a.ai_summary, a.ai_type, a.policy_type, a.validity, a.topic_tags,
               a.applicable_to, a.keywords, a.core_elements, a.actions, a.risks,
               a.standards, a.impact_level, a.impact_matrix, a.parent_basis,
               a.city_impact, a.key_data
        FROM policies p LEFT JOIN analysis a ON a.policy_id = p.id
        ORDER BY p.publish_date DESC, p.id DESC
        """
    ).fetchall()
    policies = []
    details = {}
    for r in rows:
        d = dict(r)
        for f in _ARRAY_FIELDS:
            d[f] = _j(d.get(f))
        # 抽出详情字段（数组已解析），单独入详情包
        detail = {f: d.get(f) for f in _DETAIL_FIELDS + _DETAIL_ONLY_FIELDS}
        details[str(d["id"])] = detail
        for f in _DETAIL_FIELDS + _DETAIL_ONLY_FIELDS:
            d.pop(f, None)
        for f in _DROP_FIELDS:
            d.pop(f, None)
        policies.append(d)
    return policies, details


def _export_exposures(conn):
    rows = conn.execute(
        "SELECT * FROM exposures ORDER BY publish_date DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _export_stats(conn, policies):
    by_level = {}
    for lv, name in [("national", "国家医保局"), ("provincial", "云南省医保局"), ("municipal", "玉溪市医保局")]:
        r = conn.execute("SELECT COUNT(*) c, MAX(publish_date) d FROM policies WHERE level=?", (lv,)).fetchone()
        by_level[lv] = {"name": name, "count": r["c"], "latest": r["d"]}
    latest = conn.execute(
        "SELECT title, level, publish_date FROM policies ORDER BY publish_date DESC LIMIT 1"
    ).fetchone()
    last_log = conn.execute("SELECT MAX(run_at) t FROM crawl_log").fetchone()
    return {
        "total": len(policies),
        "by_level": by_level,
        "latest": dict(latest) if latest else None,
        "last_run_at": last_log["t"] if last_log and last_log["t"] else None,
    }


def _export_facets(conn):
    cols = conn.execute(
        """SELECT p.level lv, p.column_key k, p.column_name n, COUNT(*) c
           FROM policies p GROUP BY p.level, p.column_key, p.column_name
           ORDER BY p.level, c DESC"""
    ).fetchall()
    by_column = [
        {"level": r["lv"], "key": r["k"] or "", "name": r["n"] or "其他", "count": r["c"]}
        for r in cols if r["k"]
    ]
    tag = {}
    trows = conn.execute(
        "SELECT a.topic_tags FROM analysis a JOIN policies p ON p.id = a.policy_id"
    ).fetchall()
    for r in trows:
        for t in _j(r["topic_tags"]):
            if t:
                tag[t] = tag.get(t, 0) + 1
    by_tag = [{"tag": k, "count": v} for k, v in sorted(tag.items(), key=lambda x: -x[1])]
    return {"by_column": by_column, "by_tag": by_tag}


def _export_exposure_stats(conn):
    es = {"case_total": 0, "exit_total": 0, "passive_exit": 0, "active_exit": 0,
          "by_level": {}, "org_type": {}}
    for r in conn.execute("SELECT kind, COUNT(*) n FROM exposures GROUP BY kind").fetchall():
        if r["kind"] == "case":
            es["case_total"] = r["n"]
        else:
            es["exit_total"] = r["n"]
    for r in conn.execute(
        "SELECT exit_type, COUNT(*) n FROM exposures WHERE kind='exit' GROUP BY exit_type"
    ).fetchall():
        if r["exit_type"] == "被动":
            es["passive_exit"] = r["n"]
        elif r["exit_type"] == "主动":
            es["active_exit"] = r["n"]
    for lv in ("national", "provincial", "municipal"):
        es["by_level"][lv] = conn.execute(
            "SELECT COUNT(*) n FROM exposures WHERE level=?", (lv,)
        ).fetchone()["n"]
    for r in conn.execute(
        "SELECT org_type, COUNT(*) n FROM exposures GROUP BY org_type"
    ).fetchall():
        es["org_type"][r["org_type"]] = r["n"]
    return es


def export():
    conn = database.get_conn()
    try:
        policies, details = _export_policies(conn)
        exposures = _export_exposures(conn)
        stats = _export_stats(conn, policies)
        facets = _export_facets(conn)
        exposure_stats = _export_exposure_stats(conn)
    finally:
        conn.close()

    out_dir = os.path.join(config.BASE_DIR, "frontend", "data")
    os.makedirs(out_dir, exist_ok=True)

    def dump(name, obj):
        # 紧凑序列化：去掉缩进空白，减小静态包体积（中文不转义）
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

    dump("policies.json", policies)
    dump("policy_details.json", details)
    dump("exposures.json", exposures)
    dump("stats.json", stats)
    dump("facets.json", facets)
    dump("exposure_stats.json", exposure_stats)
    print(f"exported: policies={len(policies)} details={len(details)} exposures={len(exposures)} -> {out_dir}")


if __name__ == "__main__":
    export()
