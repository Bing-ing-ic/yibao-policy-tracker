# -*- coding: utf-8 -*-
"""把 SQLite 中的政策 / 解读 / 曝光数据导出为静态站点 JSON，供 GitHub Pages 纯前端读取。

用法（在 backend 目录下）：
    python -m app.export_static

产物写入 frontend/data/：
    policies.json        政策 + 解读全字段（列表与详情共用）
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
    for r in rows:
        d = dict(r)
        for f in ("topic_tags", "applicable_to", "keywords", "key_points", "core_elements",
                  "actions", "risks", "standards", "impact_matrix", "key_data"):
            d[f] = _j(d.get(f))
        policies.append(d)
    return policies


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
        policies = _export_policies(conn)
        exposures = _export_exposures(conn)
        stats = _export_stats(conn, policies)
        facets = _export_facets(conn)
        exposure_stats = _export_exposure_stats(conn)
    finally:
        conn.close()

    out_dir = os.path.join(config.BASE_DIR, "frontend", "data")
    os.makedirs(out_dir, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)

    dump("policies.json", policies)
    dump("exposures.json", exposures)
    dump("stats.json", stats)
    dump("facets.json", facets)
    dump("exposure_stats.json", exposure_stats)
    print(f"exported: policies={len(policies)} exposures={len(exposures)} -> {out_dir}")


if __name__ == "__main__":
    export()
