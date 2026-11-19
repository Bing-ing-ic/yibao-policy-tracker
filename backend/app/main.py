# -*- coding: utf-8 -*-
"""FastAPI 入口：政策数据 API + 静态前端托管。"""
import json
import re
import threading
import time
import hashlib
import secrets
from datetime import date, datetime

from fastapi import FastAPI, Query, Header, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, database, crawler, scheduler, exposure_crawler, analyzer, progress, export_static

app = FastAPI(title="医保政策捕获与AI解读平台", version="1.0")

# ------------------------------------------------------------ 管理鉴权
TOKEN_TTL = 12 * 3600
_tokens: dict[str, float] = {}
# 允许通过设置页写入的配置白名单
SETTING_KEYS = {
    "schedule", "daily_hour", "weekly_weekday", "weekly_hour",
    "llm_enabled", "llm_base_url", "llm_model", "llm_api_key",
    "site_org", "new_days", "min_policy_date", "list_pages",
}


def _hash_pwd(pwd: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 200_000).hex()


def _ensure_password():
    """首次启动初始化默认密码 admin123（哈希存储，登录后建议修改）。"""
    salt = database.get_setting("admin_salt")
    if not salt:
        salt = secrets.token_hex(16)
        database.set_setting("admin_salt", salt)
        database.set_setting("admin_password_hash", _hash_pwd("admin123", salt))
        database.set_setting("must_change_password", "1")
    return salt


def _verify_pwd(pwd: str) -> bool:
    salt = _ensure_password()
    h = database.get_setting("admin_password_hash")
    if not h:
        return False
    return secrets.compare_digest(_hash_pwd(pwd, salt), h)


def _set_password(pwd: str):
    salt = secrets.token_hex(16)
    database.set_setting("admin_salt", salt)
    database.set_setting("admin_password_hash", _hash_pwd(pwd, salt))
    database.set_setting("must_change_password", "0")


def _check_token(token: str | None) -> bool:
    if not token:
        return False
    exp = _tokens.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _tokens.pop(token, None)
        return False
    return True


def require_admin(x_admin_token: str | None = Header(None)):
    if not _check_token(x_admin_token):
        raise HTTPException(status_code=401, detail="未授权，请先通过管理密码验证")


def _refresh_static_snapshot():
    """本地后端抓取 / 重解读结束后，把最新 DB 回写 frontend/data 静态快照，供前端重载展示。"""
    try:
        export_static.export()
    except Exception as e:
        print(f"[snapshot] 静态快照导出失败：{e!r}")

def _new_days() -> int:
    try:
        return max(0, int(database.get_setting("new_days", "3")))
    except (TypeError, ValueError):
        return 3


def _is_new(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        d = datetime.strptime(str(fetched_at)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days <= _new_days()
    except Exception:
        return False

# 批量重解读进度（内存态，供前端轮询）
_reanalyze_state = {"running": False, "total": 0, "done": 0, "failed": 0,
                    "started_at": None, "finished_at": None}
_reanalyze_lock = threading.Lock()

# 本轮政策抓取结果（内存态，供前端轮询新增条数 / ID）
_crawl_status = {"running": False, "started_at": None, "finished_at": None,
                 "found": 0, "added": 0, "updated": 0, "new_ids": [], "skipped": False,
                 "exposure_error": None}
_crawl_lock = threading.Lock()

FRONTEND_DIR = None
for cand in (
    __import__("os").path.join(config.BASE_DIR, "frontend"),
):
    if __import__("os").path.isdir(cand):
        FRONTEND_DIR = cand


@app.on_event("startup")
def _startup():
    database.init_db()
    scheduler.start_scheduler()


# ------------------------------------------------------------ 查询
def _row_to_policy(row, analysis=None):
    d = dict(row)
    for f in ("keywords", "topic_tags", "applicable_to", "key_points"):
        if analysis and f in analysis:
            d[f] = json.loads(analysis[f] or "[]")
    if analysis:
        d["effective_date"] = analysis["effective_date"]
        d["relevance"] = analysis["relevance"]
        d["relevance_note"] = analysis["relevance_note"]
        d["ai_summary"] = analysis["ai_summary"]
        d["ai_type"] = analysis["ai_type"]
    return d


@app.get("/api/policies")
def list_policies(
    level: str | None = None,
    column: str | None = None,
    keyword: str | None = None,
    tag: str | None = None,
    sort: str = Query("date", pattern="^(date|relevance)$"),
    page: int = 1,
    size: int = Query(20, le=100),
):
    conn = database.get_conn()
    where, params = [], []
    if level:
        where.append("p.level=?"); params.append(level)
    if column:
        where.append("p.column_key=?"); params.append(column)
    if keyword:
        where.append("(p.title LIKE ? OR p.summary LIKE ? OR p.content LIKE ? OR p.doc_no LIKE ?)")
        params += [f"%{keyword}%"] * 4
    if tag:
        where.append("a.topic_tags LIKE ?"); params.append(f"%{tag}%")
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) c FROM policies p LEFT JOIN analysis a ON a.policy_id=p.id {sql_where}", params
    ).fetchone()["c"]

    order = "a.relevance DESC" if sort == "relevance" else "p.publish_date DESC, p.id DESC"
    rows = conn.execute(
        f"""SELECT p.*, a.effective_date, a.relevance, a.relevance_note, a.ai_summary, a.ai_type,
                   a.topic_tags, a.applicable_to, a.keywords, a.key_points
            FROM policies p LEFT JOIN analysis a ON a.policy_id=p.id
            {sql_where} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size],
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        for f in ("topic_tags", "applicable_to", "keywords", "key_points"):
            try:
                d[f] = json.loads(d[f] or "[]")
            except Exception:
                d[f] = []
        d["is_new"] = _is_new(d.get("fetched_at"))
        items.append(d)
    return {"total": total, "page": page, "size": size, "items": items}


@app.get("/api/ask")
def ask(question: str = Query(..., min_length=2), top: int = Query(6, ge=1, le=10)):
    """政策问答：先按问题检索相关政策，启用大模型则基于材料作答，否则回退规则摘要。"""
    q = (question or "").strip()
    conn = database.get_conn()
    rows = conn.execute(
        """SELECT p.id, p.level, p.source_name, p.column_name, p.title, p.doc_no, p.publish_date, p.url,
                  a.ai_summary, a.relevance, a.relevance_note, a.topic_tags, a.key_points, a.ai_type
           FROM policies p LEFT JOIN analysis a ON a.policy_id=p.id
           WHERE p.content IS NOT NULL AND length(p.content) > 0"""
    ).fetchall()
    conn.close()

    # 中文 2-gram + 英文/数字词作为检索项
    grams = set()
    for seg in re.findall(r"[\u4e00-\u9fa5]{2,}", q):
        for i in range(len(seg) - 1):
            grams.add(seg[i:i + 2])
    words = [w for w in re.findall(r"[A-Za-z0-9]{2,}", q)]

    scored = []
    for r in rows:
        title = r["title"] or ""
        # 排除规则词典已标记的非医保事务（公务员遴选、面试、获奖/公示名单等）
        if any(k in title for k in analyzer.LOW_RELEVANCE):
            continue
        tags = r["topic_tags"] or ""
        summary = r["ai_summary"] or ""
        blob = f"{title} {tags} {summary}"
        score = 0
        title_hit = False
        tag_hit = False
        for g in grams:
            if g in title:
                score += 5; title_hit = True
            elif g in tags:
                score += 4; tag_hit = True
            elif g in summary:
                score += 1
        for w in words:
            if w.lower() in blob.lower():
                score += 3
                if w.lower() in title.lower():
                    title_hit = True
        # 相关性门槛：标题或标签需命中，避免纯摘要弱相关政策被纳入导致误答
        if score > 0 and (title_hit or tag_hit):
            scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], -(x[1]["relevance"] or 0)))
    # 最低相关度门槛：最高分不足视为无强相关政策，避免大模型依据弱材料误答
    if not scored or scored[0][0] < 8:
        return {"question": q, "answer": "未检索到与该问题直接相关的医保政策，可换用医保关键词（如：参保缴费、异地就医、集采药品、门诊统筹、定点管理、基金监管、生育保险、个人账户）再试。",
                "points": [], "note": "当前无强相关政策。", "llm": False, "sources": []}
    top_rows = [r for _, r in scored[:top]]

    def _j(v):
        try:
            return json.loads(v or "[]")
        except Exception:
            return []

    sources = []
    for r in top_rows:
        sources.append({
            "id": r["id"], "level": r["level"], "title": r["title"],
            "source_name": r["source_name"], "column_name": r["column_name"],
            "publish_date": r["publish_date"], "relevance": r["relevance"], "url": r["url"],
        })

    if not top_rows:
        return {"question": q, "answer": "未检索到与该问题直接相关的政策，可换用关键词（如：参保缴费、异地就医、集采、门诊统筹、定点管理、基金监管）再试。",
                "points": [], "note": "当前无匹配政策。", "llm": False, "sources": []}

    ctx_lines = []
    for i, r in enumerate(top_rows, 1):
        points = _j(r["key_points"])
        ctx_lines.append(
            f"[{i}] 标题：{r['title']}（{r['publish_date'] or '日期未知'}）\n"
            f"摘要：{r['ai_summary'] or '—'}\n"
            f"要点：{'；'.join(points[:3]) or '—'}"
        )
    ctx = "\n".join(ctx_lines)

    system = (
        "你是服务云南玉溪澄江市乡镇卫生院的医保政策问答专家。仅依据下面给出的政策材料回答，"
        "不要编造材料未提及的规定；材料不足以回答时如实说明。用中文，输出严格 JSON（不要 markdown）："
        "answer(通俗结论与做法，可分点，200字内)、points(数组，2-4条可执行要点)、"
        "note(一句话适用提醒或政策层级依据)。"
    )
    user = f"用户问题：{q}\n\n政策材料：\n{ctx}\n\n请基于材料作答。"
    parsed = analyzer.llm_chat_json(system, user)

    if parsed and isinstance(parsed, dict) and (parsed.get("answer") or parsed.get("points")):
        answer = parsed.get("answer") or ""
        points = parsed.get("points") if isinstance(parsed.get("points"), list) else []
        note = parsed.get("note") or ""
        llm = True
    else:
        # 规则回退：用检索到的政策摘要与要点组织答复
        answer = "；".join((r["ai_summary"] or "") for r in top_rows[:3])[:300]
        points = []
        for r in top_rows:
            for k in _j(r["key_points"])[:2]:
                if k not in points:
                    points.append(k)
        points = points[:4]
        note = "当前为规则检索结果（大模型未启用或调用受限），详细解读以政策原文为准。"
        llm = False

    return {"question": q, "answer": answer, "points": points, "note": note, "llm": llm, "sources": sources}


@app.get("/api/policies/facets")
def policy_facets(level: str | None = None):
    """按真实条目统计栏目 / 主题标签分布，前端据此只渲染有内容的按钮。"""
    conn = database.get_conn()
    where, params = [], []
    if level:
        where.append("p.level=?"); params.append(level)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""

    cols = conn.execute(
        f"""SELECT p.level lv, p.column_key k, p.column_name n, COUNT(*) c
            FROM policies p {sql_where}
            GROUP BY p.level, p.column_key, p.column_name ORDER BY p.level, c DESC""", params
    ).fetchall()
    by_column = [
        {"level": r["lv"], "key": r["k"] or "", "name": r["n"] or "其他", "count": r["c"]}
        for r in cols if r["k"]
    ]

    tag = {}
    rows = conn.execute(
        f"""SELECT a.topic_tags FROM analysis a JOIN policies p ON p.id=a.policy_id {sql_where}""",
        params,
    ).fetchall()
    for r in rows:
        try:
            for t in json.loads(r["topic_tags"] or "[]"):
                if t:
                    tag[t] = tag.get(t, 0) + 1
        except Exception:
            pass
    by_tag = [{"tag": k, "count": v} for k, v in sorted(tag.items(), key=lambda x: -x[1])]
    conn.close()
    return {"by_column": by_column, "by_tag": by_tag}


@app.get("/api/policies/{pid}")
def get_policy(pid: int):
    conn = database.get_conn()
    row = conn.execute("SELECT * FROM policies WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        return JSONResponse({"error": "not found"}, status_code=404)
    a = conn.execute("SELECT * FROM analysis WHERE policy_id=?", (pid,)).fetchone()
    conn.close()
    d = dict(row)
    if a:
        a = dict(a)
        for f in ("keywords", "topic_tags", "applicable_to", "key_points", "actions", "risks", "standards", "impact_matrix", "key_data"):
            try:
                a[f] = json.loads(a[f] or "[]")
            except Exception:
                a[f] = []
        try:
            a["core_elements"] = json.loads(a["core_elements"] or "[]")
        except Exception:
            a["core_elements"] = []
        d.update(a)
    return d


# ------------------------------------------------------------ 抓取
@app.post("/api/crawl", dependencies=[Depends(require_admin)])
def trigger_crawl(level: str | None = None):
    if _crawl_status["running"]:
        return {"status": "already_running", "level": level or "all"}

    def job():
        progress.reset()
        with _crawl_lock:
            _crawl_status.update({"running": True, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "finished_at": None, "found": 0, "added": 0, "updated": 0,
                                  "new_ids": [], "skipped": False})
        try:
            result = crawler.run_all()
            policy = result.get("policy") or {}
            exposure = result.get("exposure") or {}
            with _crawl_lock:
                _crawl_status.update({
                    "running": False,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "found": policy.get("found", 0),
                    "added": policy.get("added", 0),
                    "updated": policy.get("updated", 0),
                    "new_ids": policy.get("new_ids", []),
                    "skipped": policy.get("skipped") == "running",
                    "exposure_error": exposure.get("error"),
                })
            progress.update(phase="done", stage="抓取完成", percent=100)
            _refresh_static_snapshot()
        except Exception as e:
            with _crawl_lock:
                _crawl_status.update({"running": False, "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "error": repr(e)})
            progress.update(phase="done", stage="抓取异常", percent=100)
            _refresh_static_snapshot()

    threading.Thread(target=job, daemon=True).start()
    return {"status": "started", "level": level or "all"}


@app.get("/api/crawl/status")
def crawl_status():
    with _crawl_lock:
        out = dict(_crawl_status)
    out.update(progress.snapshot())
    return out


@app.post("/api/reanalyze", dependencies=[Depends(require_admin)])
def trigger_reanalyze(limit: int = Query(50, ge=1, le=500), only: str = Query("rule")):
    """后台批量重解读历史政策。only=rule 仅重跑规则解读条目；开启大模型后可由大模型重新解读。"""
    with _reanalyze_lock:
        if _reanalyze_state["running"]:
            return {"status": "already_running", **_reanalyze_state}

    def job():
        conn = database.get_conn()
        q = """SELECT p.id, p.title, p.doc_no, p.publish_date, p.content, p.level, a.ai_type
               FROM policies p LEFT JOIN analysis a ON a.policy_id=p.id
               WHERE p.content IS NOT NULL AND length(p.content) > 0"""
        args = []
        if only == "rule":
            q += " AND (a.ai_type IS NULL OR a.ai_type='rule')"
        q += " ORDER BY p.publish_date DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
        with _reanalyze_lock:
            _reanalyze_state.update(running=True, total=len(rows), done=0, failed=0,
                                     started_at=time.time(), finished_at=None)
        for i, r in enumerate(rows, 1):
            try:
                a = analyzer.analyze(r["title"], r["doc_no"], r["publish_date"], r["content"], r["level"])
                analyzer.save_analysis(conn, r["id"], a)
                with _reanalyze_lock:
                    _reanalyze_state["done"] += 1
            except Exception as e:
                print(f"[reanalyze] 第 {i} 条(id={r['id']})失败：{e!r}")
                with _reanalyze_lock:
                    _reanalyze_state["failed"] += 1
            if i % 10 == 0:
                conn.commit()
            time.sleep(0.2)
        conn.commit()
        conn.close()
        with _reanalyze_lock:
            _reanalyze_state.update(running=False, finished_at=time.time())
        _refresh_static_snapshot()

    threading.Thread(target=job, daemon=True).start()
    return {"status": "started", "limit": limit, "only": only}


@app.get("/api/reanalyze/status")
def reanalyze_status():
    with _reanalyze_lock:
        return dict(_reanalyze_state)


@app.get("/api/logs")
def logs(limit: int = 30):
    conn = database.get_conn()
    rows = conn.execute("SELECT * FROM crawl_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/stats")
def stats():
    conn = database.get_conn()
    out = {"by_level": {}, "total": 0, "latest": None, "logs": []}
    for lv, name in [("national", "国家医保局"), ("provincial", "云南省医保局"), ("municipal", "玉溪市医保局")]:
        r = conn.execute("SELECT COUNT(*) c, MAX(publish_date) d FROM policies WHERE level=?", (lv,)).fetchone()
        out["by_level"][lv] = {"name": name, "count": r["c"], "latest": r["d"]}
        out["total"] += r["c"]
    latest = conn.execute("SELECT title, level, publish_date FROM policies ORDER BY publish_date DESC LIMIT 1").fetchone()
    if latest:
        out["latest"] = dict(latest)
    last_log = conn.execute("SELECT MAX(run_at) t FROM crawl_log").fetchone()
    out["last_run_at"] = last_log["t"] if last_log and last_log["t"] else None
    out["next_run"] = scheduler.next_run_time()
    conn.close()
    return out


# ------------------------------------------------------------ 曝光台
@app.get("/api/exposures")
def list_exposures(
    level: str | None = None,
    kind: str | None = None,
    org_type: str | None = None,
    exit_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = Query(20, le=100),
):
    conn = database.get_conn()
    where, params = [], []
    if level:
        where.append("e.level=?"); params.append(level)
    if kind:
        where.append("e.kind=?"); params.append(kind)
    if org_type:
        where.append("e.org_type=?"); params.append(org_type)
    if exit_type:
        where.append("e.exit_type=?"); params.append(exit_type)
    if keyword:
        where.append("(e.org_name LIKE ? OR e.problem LIKE ? OR e.penalty LIKE ? OR e.title LIKE ?)")
        params += [f"%{keyword}%"] * 4
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) c FROM exposures e {sql_where}", params
    ).fetchone()["c"]
    rows = conn.execute(
        f"""SELECT e.* FROM exposures e {sql_where}
            ORDER BY e.publish_date DESC, e.id DESC LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size],
    ).fetchall()
    conn.close()
    return {"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]}


@app.get("/api/exposures/stats")
def exposure_stats():
    conn = database.get_conn()
    out = {"case_total": 0, "exit_total": 0, "passive_exit": 0, "active_exit": 0, "by_level": {}, "org_type": {}}
    row = conn.execute("SELECT kind, COUNT(*) n FROM exposures GROUP BY kind").fetchall()
    for r in row:
        if r["kind"] == "case":
            out["case_total"] = r["n"]
        else:
            out["exit_total"] = r["n"]
    row = conn.execute("SELECT exit_type, COUNT(*) n FROM exposures WHERE kind='exit' GROUP BY exit_type").fetchall()
    for r in row:
        if r["exit_type"] == "被动":
            out["passive_exit"] = r["n"]
        elif r["exit_type"] == "主动":
            out["active_exit"] = r["n"]
    for lv in ("national", "provincial", "municipal"):
        r = conn.execute("SELECT COUNT(*) n FROM exposures WHERE level=?", (lv,)).fetchone()
        out["by_level"][lv] = r["n"]
    row = conn.execute("SELECT org_type, COUNT(*) n FROM exposures GROUP BY org_type").fetchall()
    for r in row:
        out["org_type"][r["org_type"]] = r["n"]
    conn.close()
    return out


@app.post("/api/exposure/crawl", dependencies=[Depends(require_admin)])
def trigger_exposure_crawl():
    def job():
        exposure_crawler.run_exposure_crawl()
        _refresh_static_snapshot()
    threading.Thread(target=job, daemon=True).start()
    return {"status": "started"}


@app.get("/api/sources")
def sources():
    return config.SOURCES


# ------------------------------------------------------------ 设置
@app.get("/api/settings")
def get_settings():
    conn = database.get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    data = {r["key"]: r["value"] for r in rows}
    # 隐藏密钥与密码哈希回显
    data["llm_api_key_set"] = bool(data.get("llm_api_key"))
    for secret in ("llm_api_key", "admin_password_hash", "admin_salt"):
        data.pop(secret, None)
    # 展示用默认值回填
    data.setdefault("site_org", config.SITE_CONTEXT.get("org", ""))
    data.setdefault("new_days", "3")
    data.setdefault("min_policy_date", config.MIN_POLICY_DATE)
    data.setdefault("list_pages", str(config.LIST_PAGES))
    data["must_change_password"] = database.get_setting("must_change_password", "0") == "1"
    return data


@app.post("/api/settings", dependencies=[Depends(require_admin)])
def save_settings(payload: dict):
    for k, v in payload.items():
        if k not in SETTING_KEYS:
            continue
        if k == "llm_api_key" and not v:  # 留空不覆盖原密钥
            continue
        database.set_setting(k, v)
    scheduler.reload_scheduler()
    return {"status": "ok", "next_run": scheduler.next_run_time()}


# ------------------------------------------------------------ 管理鉴权
@app.post("/api/auth/login")
def auth_login(payload: dict):
    pwd = str(payload.get("password") or "")
    if not _verify_pwd(pwd):
        raise HTTPException(status_code=401, detail="管理密码错误")
    token = secrets.token_hex(16)
    _tokens[token] = time.time() + TOKEN_TTL
    return {"status": "ok", "token": token,
            "must_change": database.get_setting("must_change_password", "0") == "1"}


@app.post("/api/auth/logout")
def auth_logout(x_admin_token: str | None = Header(None)):
    _tokens.pop(x_admin_token, None)
    return {"status": "ok"}


@app.post("/api/auth/password", dependencies=[Depends(require_admin)])
def auth_change_password(payload: dict):
    old = str(payload.get("old_password") or "")
    new = str(payload.get("new_password") or "")
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if not _verify_pwd(old):
        raise HTTPException(status_code=401, detail="原密码错误")
    _set_password(new)
    return {"status": "ok"}


# ------------------------------------------------------------ 静态前端
@app.get("/")
def index():
    if FRONTEND_DIR:
        return FileResponse(__import__("os").path.join(FRONTEND_DIR, "index.html"))
    return JSONResponse({"error": "frontend not found"})


if FRONTEND_DIR:
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    # 本地后端调试兜底：让根路径下的相对资源（app.js / style.css / data/*）直接命中，
    # 与 GitHub Pages 站点根部署的相对路径行为一致；/api 路由已在前面注册，优先匹配不受影响。
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend-root")
