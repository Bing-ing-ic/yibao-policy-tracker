# -*- coding: utf-8 -*-
"""曝光台抓取调度：案例通报 + 退出协议公告，写入 exposures 表。"""
import re

from . import config, database, sources, exposure, progress


def _list_items(fetcher, source, list_url):
    r = fetcher.get(list_url)
    col = {"key": "exposure", "name": "曝光台"}
    return sources.parse_list(source, col, r.text, list_url)


def _list_page_urls(list_url):
    """jspx 栏目按 pageNo 翻页；其余静态栏目只取首页。空页由调用方提前停。"""
    if "pageNo=" in list_url:
        return [re.sub(r"pageNo=\d+", f"pageNo={p}", list_url) for p in range(1, sources._list_pages() + 1)]
    return [list_url]


def _save(conn, records):
    n = 0
    for rec in records:
        # 跨通报按机构名+类型+协议状态去重；同机构不同解除/中止状态分别保留
        exists = conn.execute(
            "SELECT 1 FROM exposures WHERE org_name=? AND kind=? AND exit_status=?",
            (rec["org_name"], rec["kind"], rec["exit_status"]),
        ).fetchone()
        if exists:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO exposures(level, source_name, kind, org_name, org_type, region,
                   problem, penalty, exit_status, exit_type, amount, publish_date, title, url, summary)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["level"], rec["source_name"], rec["kind"], rec["org_name"], rec["org_type"],
                rec["region"], rec["problem"], rec["penalty"], rec["exit_status"], rec["exit_type"],
                rec["amount"], rec["publish_date"], rec["title"], rec["url"], rec["summary"],
            ),
        )
        n += cur.rowcount
    return n


def run_exposure_crawl():
    fetcher = sources.Fetcher()
    conn = database.get_conn()
    stats = {"case_found": 0, "exit_found": 0, "case_added": 0, "exit_added": 0}
    total = len(config.EXPOSURE_SOURCES)
    progress.update(phase="exposure", source_total=total, count=0,
                    stage="准备抓取曝光台…", percent=25)

    for idx, source in enumerate(config.EXPOSURE_SOURCES, 1):
        level, name = source["level"], source["source_name"]
        progress.update(phase="exposure", source_total=total, source_idx=idx,
                        stage=f"正在抓取曝光台：{name}",
                        percent=round(25 + 75 * (idx - 1) / max(1, total), 1))

        # ---- 违规案例
        for list_url in source["case_lists"]:
            for page_url in _list_page_urls(list_url):
                try:
                    items = _list_items(fetcher, source, page_url)
                    if not items:
                        break
                    for it in items:
                        if not any(k in it["title"] for k in source["case_keywords"]):
                            continue
                        stats["case_found"] += 1
                        progress.bump_count()
                        title, _, pub_date, content = sources.fetch_detail(fetcher, level, it["url"])
                        title = title or it["title"]
                        records = exposure.extract_cases(title, content, level, it["url"], pub_date or it["publish_date"], name)
                        stats["case_added"] += _save(conn, records)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[EXPOSURE-CASE] {name} {page_url} {e!r}")

        # ---- 退出协议公告
        for list_url in source["exit_lists"]:
            for page_url in _list_page_urls(list_url):
                try:
                    items = _list_items(fetcher, source, page_url)
                    if not items:
                        break
                    for it in items:
                        if not any(k in it["title"] for k in source["exit_keywords"]):
                            continue
                        if "协议" not in it["title"]:
                            continue
                        stats["exit_found"] += 1
                        progress.bump_count()
                        title, _, pub_date, content = sources.fetch_detail(fetcher, level, it["url"])
                        html = fetcher.get(it["url"]).text
                        title = title or it["title"]
                        records = exposure.extract_exit_notice(
                            title, content, level, it["url"], pub_date or it["publish_date"], name, html=html
                        )
                        stats["exit_added"] += _save(conn, records)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[EXPOSURE-EXIT] {name} {page_url} {e!r}")

    conn.close()
    return stats
