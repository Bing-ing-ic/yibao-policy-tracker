# -*- coding: utf-8 -*-
"""抓取调度：列表 → 去重入库 → 详情 → AI/规则解读。"""
import hashlib
import threading
import time

from . import config, database, sources, analyzer, progress, exposure_crawler

# 防止手动触发与定时任务重叠并发抓取
_crawl_lock = threading.Lock()


def _min_date() -> str:
    return database.get_setting("min_policy_date", config.MIN_POLICY_DATE)


def _hash(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def run_crawl(only_level=None):
    """执行一轮抓取。only_level: national/provincial/municipal 或 None（全部）。"""
    if not _crawl_lock.acquire(blocking=False):
        return {"found": 0, "added": 0, "updated": 0, "logs": [], "skipped": "running"}
    try:
        fetcher = sources.Fetcher()
        conn = database.get_conn()
        overall = {"found": 0, "added": 0, "updated": 0, "new_ids": [], "logs": []}

        scope = [s for s in config.SOURCES if not only_level or s["level"] == only_level]
        progress.reset()
        progress.update(phase="policy", source_total=len(scope),
                        stage="准备抓取政策…", percent=0)

        for idx, source in enumerate(scope, 1):
            t0 = time.time()
            progress.update(phase="policy", source_total=len(scope), source_idx=idx,
                            stage=f"正在抓取政策：{source['source_name']}",
                            percent=round(25 * (idx - 1) / max(1, len(scope)), 1))
            found = added = updated = failures = 0
            new_ids = []
            page_errors = []
            message = "成功"
            try:
                for column in source["columns"]:
                    for page_url in sources.list_page_urls(source, column):
                        # 单个列表页失败不影响其余栏目 / 分页
                        try:
                            r = fetcher.get(page_url, soft_status=(403, 404))
                            if r.status_code in (403, 404):
                                continue  # 空分页 / 无权限页，静默跳过
                            items = sources.parse_list(source, column, r.text, page_url)
                        except Exception as e:
                            page_errors.append(f"{column['name']}（{type(e).__name__}）")
                            print(f"[CRAWL] 列表页失败 {page_url}: {e!r}")
                            continue

                        for item in items:
                            if not item["title"] or not item["url"]:
                                continue
                            # 仅保留 2024 年至今；日期缺失的暂留，详情日期补全后再由前端排序
                            if item["publish_date"] and item["publish_date"] < _min_date():
                                continue
                            found += 1
                            progress.bump_count()
                            row = conn.execute("SELECT id, content FROM policies WHERE url=?", (item["url"],)).fetchone()
                            if row:
                                updated += 1
                                if not row["content"]:
                                    try:
                                        _fill_detail(conn, fetcher, source["level"], source["home"], row["id"], item)
                                    except Exception as e:
                                        failures += 1
                                        print(f"[CRAWL] 补抓详情失败 {item['url']}: {e!r}")
                                continue
                            # 新条目
                            cur = conn.execute(
                                """INSERT INTO policies(level, source_name, column_key, column_name, title,
                                       doc_no, url, publish_date, summary, content, content_hash)
                                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    source["level"], source["source_name"], item["column_key"], item["column_name"],
                                    item["title"], item["doc_no"], item["url"], item["publish_date"],
                                    None, None, None,
                                ),
                            )
                            policy_id = cur.lastrowid
                            added += 1
                            new_ids.append(policy_id)
                            # 单条详情失败保留空条目，待下一轮补抓，不中断整源
                            try:
                                kept = _fill_detail(conn, fetcher, source["level"], source["home"], policy_id, item)
                                if kept is False:
                                    new_ids.remove(policy_id)
                            except Exception as e:
                                failures += 1
                                print(f"[CRAWL] 详情失败 {item['url']}: {e!r}")
                conn.commit()
            except Exception as e:
                conn.rollback()
                message = f"异常：{e!r}"
                print(f"[CRAWL] {source['source_name']} {message}")

            if message == "成功":
                message = f"成功：新增 {added}，更新 {updated}"
                if failures:
                    message += f"，详情失败 {failures}"
                if page_errors:
                    message += "；列表页异常：" + "、".join(page_errors[:3])
            status = "ok" if message.startswith("成功") else "error"

            duration = int((time.time() - t0) * 1000)
            conn.execute(
                """INSERT INTO crawl_log(level, source_name, found, added, status, message, duration_ms)
                   VALUES(?,?,?,?,?,?,?)""",
                (source["level"], source["source_name"], found, added, status, message, duration),
            )
            conn.commit()
            overall["found"] += found
            overall["added"] += added
            overall["updated"] += updated
            overall["new_ids"].extend(new_ids)
            overall["logs"].append({"level": source["level"], "source_name": source["source_name"],
                                    "found": found, "added": added, "status": message, "duration_ms": duration})

        conn.close()
        return overall
    finally:
        _crawl_lock.release()


def _fill_detail(conn, fetcher, level, home, policy_id, item):
    title, doc_no, pub_date_detail, content = sources.fetch_detail(fetcher, level, item["url"], referer=home)
    title = title or item["title"]
    doc_no = doc_no or item.get("doc_no")
    pub_date = item.get("publish_date") or pub_date_detail
    # 详情日期确认早于 2024 年的条目剔除（列表日期缺失时的兜底）
    if pub_date and pub_date < _min_date():
        conn.execute("DELETE FROM analysis WHERE policy_id=?", (policy_id,))
        conn.execute("DELETE FROM policies WHERE id=?", (policy_id,))
        return False
    content = content or ""
    summary = content[:160]
    chash = _hash(content)

    # 同稿二次去重：正文有实质内容时，若库内已存在相同正文（转载 / 同一篇在不同栏目挂稿，URL 不同），
    # 视为同一篇，丢弃当前新条目，避免同稿多条抬高计数。
    # 豁免退化正文：图解/表格/标题回填导致正文退化成标题、或实质内容过少（去标题后不足 30 字），
    # 这类条目往往只是标题相同、不同期次名单/正文不同，并非同稿，不参与哈希比对，避免误删。
    body = content.strip()
    rest = body.replace(title or "", "")
    real_len = len(rest.replace("\n", "").replace("\r", "").replace(" ", "").replace("\t", ""))
    if body and real_len >= 30:
        dup = conn.execute(
            "SELECT id FROM policies WHERE content_hash=? AND id<>?", (chash, policy_id)
        ).fetchone()
        if dup:
            conn.execute("DELETE FROM analysis WHERE policy_id=?", (policy_id,))
            conn.execute("DELETE FROM policies WHERE id=?", (policy_id,))
            return False

    conn.execute(
        """UPDATE policies SET title=?, doc_no=?, publish_date=?, summary=?, content=?, content_hash=?,
               updated_at=datetime('now','localtime') WHERE id=?""",
        (title, doc_no, pub_date, summary, content, chash, policy_id),
    )

    analysis = analyzer.analyze(title, doc_no, pub_date, content, level)
    analyzer.save_analysis(conn, policy_id, analysis)
    return True


def json_dumps(obj):
    import json
    return json.dumps(obj or [], ensure_ascii=False)


def run_all():
    """定时/手动触发的组合任务：政策抓取 + 曝光台抓取。"""
    policy = run_crawl()
    try:
        exposure = exposure_crawler.run_exposure_crawl()
    except Exception as e:
        exposure = {"error": repr(e)}
    return {"policy": policy, "exposure": exposure}
