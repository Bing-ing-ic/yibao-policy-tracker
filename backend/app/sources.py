# -*- coding: utf-8 -*-
"""三站点列表 / 详情抓取解析器（仅官方政府站点）。"""
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from . import config, database

requests.packages.urllib3.disable_warnings()


def _list_pages() -> int:
    try:
        return max(1, int(database.get_setting("list_pages", str(config.LIST_PAGES))))
    except (TypeError, ValueError):
        return config.LIST_PAGES

_DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")


def _norm_date(s):
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)

    @staticmethod
    def _detect_encoding(r):
        """优先 meta charset，其次 chardet 探测，最后 utf-8 兜底，避免中文乱码。"""
        try:
            head = r.content[:2048]
            m = re.search(rb'charset=["\']?([\w-]+)', head, re.I)
            if m:
                return m.group(1).decode("ascii", "ignore").lower()
        except Exception:
            pass
        return r.apparent_encoding or r.encoding or "utf-8"

    def get(self, url, referer=None, soft_status=()):
        """带重试退避的 GET；连接/读取超时分离；可重试 5xx/429 与网络/超时错误。
        soft_status 中的状态码（如 403/404 空分页）不抛异常，原样返回由调用方跳过。"""
        headers = {"Referer": referer} if referer else {}
        last_exc = None
        for attempt in range(1, config.REQUEST_RETRIES + 1):
            try:
                r = self.session.get(
                    url, headers=headers,
                    timeout=(config.REQUEST_TIMEOUT_CONNECT, config.REQUEST_TIMEOUT_READ),
                    verify=False,
                )
                if r.status_code in soft_status:
                    time.sleep(config.REQUEST_DELAY)
                    return r
                if r.status_code in config.RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                r.encoding = self._detect_encoding(r)
                time.sleep(config.REQUEST_DELAY)
                return r
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last_exc = e
                if attempt < config.REQUEST_RETRIES:
                    time.sleep(config.RETRY_BACKOFF * (2 ** (attempt - 1)))
                continue
            except requests.RequestException as e:
                last_exc = e
                break
        raise last_exc


# ------------------------------------------------------------ 国家医保局
def _parse_nhsa_list(html, home, col_key, col_name):
    out = []
    # <record><![CDATA[ <li>...</li> ]]></record>
    for block in re.findall(r"<record>(.*?)</record>", html, re.S):
        block = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", block, flags=re.S)
        soup = BeautifulSoup(block, "lxml")
        li = soup.find("li")
        if not li:
            continue
        a = li.find("a", href=True)
        if not a:
            continue
        spans = li.find_all("span")
        title = a.get("title") or _clean_text(a.get_text())
        doc_no = _clean_text(spans[2].get_text()) if len(spans) >= 3 else None
        date = _norm_date(spans[-1].get_text()) if spans else None
        out.append(
            {
                "column_key": col_key,
                "column_name": col_name,
                "title": _clean_text(title),
                "doc_no": doc_no,
                "url": urllib.parse.urljoin(home, a["href"]),
                "publish_date": date,
            }
        )
    return out


def _nhsa_pages(base_url):
    # index.html 首页，其后为 index_1.html / index_2.html ...
    urls = [base_url]
    for i in range(1, _list_pages()):
        urls.append(base_url.replace("index.html", f"index_{i}.html"))
    return urls


# ------------------------------------------------------------ 云南省医保局
def _parse_yn_list(html, base_url, col_key, col_name):
    out = []
    soup = BeautifulSoup(html, "lxml")
    for li in soup.select("li.clearfix, li.list-item"):
        a = li.find("a", href=True)
        if not a or a["href"].startswith("javascript"):
            continue
        if "ylbz.yn.gov.cn" not in urllib.parse.urljoin(base_url, a["href"]) and not a["href"].startswith("./"):
            continue
        title = _clean_text(a.get_text())
        if not title or len(title) < 6:
            continue
        out.append(
            {
                "column_key": col_key,
                "column_name": col_name,
                "title": title,
                "doc_no": None,
                "url": urllib.parse.urljoin(base_url, a["href"]),
                "publish_date": _norm_date(li.get_text()),
            }
        )
    return out


# 区县部门列表中需剔除的非政策类栏目标题
_YX_NOISE_TITLE = re.compile(
    r"(职责|内设机构|机构设置|机构职能|公开指南|信息公开制度|预决算|年度报告|网站地图|"
    r"领导分工|联系方式|公开目录|部门简介|工作职责|规划计划|公示目录)"
)


# ------------------------------------------------------------ 玉溪市医保局（含下辖区县）
def _parse_yx_list(html, home, col_key, col_name):
    out = []
    soup = BeautifulSoup(html, "lxml")
    article_re = re.compile(r"/20\d{6}/\d+\.html")
    home_host = urllib.parse.urlparse(home).netloc
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        # 保留本站（市级/下辖区县门户）本地文章，过滤微信公众号 / 外省站外链 / 导航
        netloc = urllib.parse.urlparse(href).netloc
        if netloc and home_host not in netloc:
            continue
        if not article_re.search(href):
            continue
        title = _clean_text(a.get_text())
        if not title or len(title) < 6:
            continue
        if _YX_NOISE_TITLE.search(title):
            continue
        out.append(
            {
                "column_key": col_key,
                "column_name": col_name,
                "title": title,
                "doc_no": None,
                "url": urllib.parse.urljoin(home, href),
                "publish_date": _norm_date(li.get_text()),
            }
        )
    # 去重（列表项常被多层容器重复包裹）
    seen, uniq = set(), []
    for it in out:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        uniq.append(it)
    return uniq


def parse_list(source, column, html, current_url):
    level = source["level"]
    home = source["home"]
    ck, cn = column["key"], column["name"]
    if level == "national":
        return _parse_nhsa_list(html, home, ck, cn)
    if level == "provincial":
        return _parse_yn_list(html, current_url, ck, cn)
    return _parse_yx_list(html, home, ck, cn)


def list_page_urls(source, column):
    level = source["level"]
    if level == "national":
        return _nhsa_pages(column["url"])
    if level == "municipal":
        return [column["url"].format(page=p) for p in range(1, _list_pages() + 1)]
    # 省级：index.html → index_1.html / index_2.html ...
    urls = [column["url"]]
    for i in range(1, _list_pages()):
        urls.append(column["url"].rstrip("/") + f"/index_{i}.html")
    return urls


# ------------------------------------------------------------ 详情正文
_NOISE_RE = re.compile(
    r"(【?字体】?|大\s*中\s*小|打印|发布时间|来源[:：]|索引号|主题分类|成文日期|效力状态|"
    r"分享到|微信扫一扫|关闭窗口|浏览次数|主办[:：]|承办[:：]|当前位置|首页\s*>)"
)


def _extract_paragraphs(container, title=None):
    if not container:
        return []
    title_clean = _clean_text(title) if title else None
    paras = []
    for p in container.find_all(["p", "div", "td", "li"]):
        txt = _clean_text(p.get_text())
        if txt and len(txt) > 1 and not _NOISE_RE.search(txt):
            paras.append(txt)
    # 兜底：直接全文
    if not paras:
        t = _clean_text(container.get_text())
        if t and not _NOISE_RE.search(t):
            paras = [t]
    # 去相邻重复
    dedup = []
    for p in paras:
        if not dedup or dedup[-1] != p:
            dedup.append(p)
    # 剔除与标题相同或被标题包含的首段
    if title_clean and dedup and (dedup[0] == title_clean or title_clean.startswith(dedup[0]) or dedup[0].startswith(title_clean[:20])):
        dedup = dedup[1:]
    return dedup


def fetch_detail(fetcher: Fetcher, level, url, referer=None):
    """返回 (标题, 文号, 发布日期, 正文段落列表)。"""
    r = fetcher.get(url, referer=referer)
    soup = BeautifulSoup(r.text, "lxml")

    title_el = soup.find(["h1", "h2"])
    title = _clean_text(title_el.get_text()) if title_el else None
    publish_date = None
    doc_no = None

    if level == "national":
        container = soup.select_one("#zoom, .TRS_Editor, .article-content, #UCAP-CONTENT")
        publish_date = _norm_date(r.text)
    elif level == "provincial":
        container = soup.select_one(".acticle-content, .trs_editor_view, .TRS_Editor, #UCAP-CONTENT, .article-content")
        # 元信息区：成文日期 / 文号
        meta = soup.select_one(".article-overview-wrapper")
        if meta:
            mt = meta.get_text()
            publish_date = _norm_date(mt) or publish_date
            m = re.search(r"〔20\d{2}〕[一-龥A-Za-z0-9]{1,8}号", mt)
            if m:
                doc_no = m.group(0)
    elif level == "municipal":
        container = soup.select_one("#content-txt-1, .content-txt, .print-container, #xilan_cont, .xilan_all, .article-main-content, .article-main, #zoom, .TRS_Editor, #UCAP-CONTENT, .article-content")
        meta = soup.select_one(".main-container, .col.content-container")
        if meta:
            mt = meta.get_text()
            publish_date = _norm_date(mt) or publish_date
            m = re.search(r"〔20\d{2}〕[一-龥A-Za-z0-9]{1,8}号", mt)
            if m:
                doc_no = m.group(0)

    paragraphs = _extract_paragraphs(container, title)
    content = "\n".join(paragraphs)[: config.MAX_DETAIL_CHARS]
    return title, doc_no, publish_date, content
