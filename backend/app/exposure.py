# -*- coding: utf-8 -*-
"""曝光台：违规案例机构抽取 + 退出协议机构公告解析。"""
import re

from . import sources

ORG_SUFFIX_MED = ["医院", "卫生院", "卫生所", "卫生室", "医务室", "门诊部", "诊所", "社区卫生服务中心", "活动中心"]
ORG_SUFFIX_DRUG = ["药店", "大药房", "药房", "店", "药业", "连锁"]

ORG_NAME_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()·、]{4,40}?"
    r"(?:社区卫生服务中心|门诊部|医务室|卫生室|卫生所|卫生院|活动中心|大药房|药店|药房|药业|医院|诊所|连锁|公司|中心))"
)
AMOUNT_RE = re.compile(r"\d+\.?\d*\s*(?:万元|元)")
# 编号分段：一、 二、 … / ## 一、
SEG_RE = re.compile(r"(?:^|\n)\s*(?:##\s*)?[一二三四五六七八九十]+、")


def org_type(name):
    # 医疗机构后缀优先（“XX药房…诊所”这类混排应判医疗机构）
    if any(k in name for k in ORG_SUFFIX_MED):
        return "医疗机构"
    if any(k in name for k in ORG_SUFFIX_DRUG):
        return "零售药店"
    return "其他机构"


def _clean_org(name):
    name = re.sub(r"^[一二三四五六七八九十]+、", "", name)
    name = re.sub(r"^第?\d+号?", "", name)
    # 剔除日期时间段（2026年7月13日起至2026年12月31日止）
    name = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日(?:起|至)?(?:\d{1,2}月\d{1,2}日)?(?:止|起)?", "", name)
    # 剔除搬迁 / 装修等原因词
    name = re.sub(r"经营地址搬迁|店面装修升级|地址搬迁|搬迁|装修升级", "", name)
    name = name.replace("行政相对人名称", "")
    name = re.sub(r"^[：:、\s]+", "", name)
    return name.strip("，。、； ")


# 机构名前需要剥离的监管方 / 连接 / 动作词（取最后一段为真正机构主体）
_ORG_PREFIX_RE = re.compile(
    r"医保中心|医疗保障中心|医保局|医疗保障局|关于|解除|中止|终止|暂停|自愿|主动|与|因|根据|以及|和|"
    r"定点医药机构|定点医疗机构|机构名称|机构地址|地址|序号|编码|国家编码|名称|"
    r"起止时间|协议起止时间|中止原因|解除原因|医保服务协议|服务协议|医保协议"
)

# 强地址特征：出现在机构名内通常意味着多机构/地址混排的脏行
_ADDR_RE = re.compile(r"街道|社区|村|小区|幢|商铺|号|乡|花苑|社区居民委员会")


def _strip_prefix(name):
    if not name:
        return name
    parts = _ORG_PREFIX_RE.split(name)
    tail = next((p for p in reversed(parts) if p and p.strip()), name)
    return _clean_org(tail)


def _extract_org(text):
    """从文本末尾方向取最后一个机构后缀，返回完整机构名（避免被“医院”提前截断到“门诊部”前）。"""
    if not text:
        return None
    suffixes = sorted(ORG_SUFFIX_MED + ORG_SUFFIX_DRUG + ["公司"], key=len, reverse=True)
    best = None
    for suf in suffixes:
        i = text.rfind(suf)
        if i >= 0 and (best is None or i + len(suf) > best[1]):
            best = (suf, i + len(suf))
    if not best:
        return None
    return _clean_org(text[:best[1]])


# 机构名必须命中的后缀 / 需排除的监管方与泛指词
_ORG_SUFFIX_ALL = ORG_SUFFIX_MED + ORG_SUFFIX_DRUG + ["公司", "中心", "门诊部"]
_ORG_STOP = ("医保局", "医保中心", "医疗保障局", "医疗保险中心", "医疗保险基金管理中心", "基金管理中心",
             "零售药店", "医药机构", "医疗机构", "定点医药机构", "定点医疗机构",
             "部分", "若干", "相关机构", "某机构",
             "某药店", "某公司", "某医院", "职业开药人", "参保人", "个人")


def _valid_org(name):
    if not name or len(name) < 4:
        return False
    if any(k in name for k in _ORG_STOP):
        return False
    if _ADDR_RE.search(name):
        return False
    return any(name.endswith(s) for s in _ORG_SUFFIX_ALL)


def _exit_state(text):
    """返回 (exit_status, exit_type)；含主动/自愿即判主动申请。"""
    active = bool(re.search(r"主动|自愿", text))
    if re.search(r"解除|终止", text):
        return "解除协议", "主动" if active else "被动"
    if re.search(r"中止|暂停", text):
        return "中止/暂停协议", "主动" if active else "被动"
    if active:
        return "主动退出", "主动"
    return "未退出协议", "—"


def _org_from_text(text):
    """从标题/正文抽取机构名：多句式正则优先，后缀抽取兜底。"""
    if not text:
        return None
    patterns = [
        r"与(.+?)(?:等?(?:医药机构|医疗机构))?(?:中止|终止|解除|退出)",  # 基金中心与XX机构…
        r"关于(.+?)(?:解除|中止|终止|暂停)",                              # 关于XX机构解除…
        r"^(.+?)关于(?:解除|中止|终止|暂停)",                              # XX机构关于解除…
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            org = _strip_prefix(m.group(1))
            if _valid_org(org):
                return org
    org = _strip_prefix(_extract_org(text) or "")
    return org if _valid_org(org) else None


def _exit_row(status_text, reason):
    """表格行：按原因判定状态与主动/被动。"""
    if re.search(r"解除|终止", status_text):
        status = "解除协议"
    elif re.search(r"中止|暂停", status_text):
        status = "中止/暂停协议"
    else:
        status, _ = _exit_state(status_text)
    active = bool(re.search(r"主动|自愿", reason))
    etype = "主动" if active else "被动"
    if active and re.search(r"退出", reason):
        status = "主动退出"
    return status, etype


def _problem(seg):
    m = re.search(r"存在(.{4,120}?)(?:行为|问题|情形)", seg)
    if m:
        return m.group(1).strip("，。、； ")
    m = re.search(r"涉嫌(.{4,80}?)(?:行为|问题|情形)", seg)
    return m.group(1).strip("，。、； ") if m else None


def _penalty(seg):
    # 优先取含处理动作的分句（退回/罚款/违约金/解除/中止/暂停/追回/移交）
    for sent in re.split(r"[。；;\n]", seg):
        if any(k in sent for k in ("责令退回", "退回违规", "罚款", "违约金", "解除", "中止", "暂停", "追回", "移交", "行政罚款")):
            if not re.search(r"电话[:：]|地址|备注|未经允许", sent):
                return sent.strip("，。； ")[:300]
    # 取“处理如下/处理结果/依据…：”之后
    m = re.search(r"(?:处理如下|处理结果|处罚如下|依据《[^》]+》[^：]*[:：])(.{20,300})", seg)
    if m and not re.search(r"电话[:：]|地址|备注", m.group(1)):
        return m.group(1).strip("，。； ")[:300]
    return None


def extract_cases(title, content, level, url, publish_date, source_name):
    """从案例通报正文切分多条机构记录。"""
    out = []
    if not content:
        return out
    parts = [p.strip() for p in SEG_RE.split(content) if p and len(p.strip()) > 20]
    for seg in parts:
        m = ORG_NAME_RE.search(seg)
        if not m:
            continue
        org = _extract_org(m.group(1))
        if not _valid_org(org):
            continue
        problem = _problem(seg)
        if problem:
            problem = problem.lstrip("的，。、； ")
        penalty = _penalty(seg)
        amounts = AMOUNT_RE.findall(seg)
        exit_status, exit_type = _exit_state(seg)
        out.append(
            {
                "level": level,
                "source_name": source_name,
                "kind": "case",
                "org_name": org,
                "org_type": org_type(org),
                "region": None,
                "problem": problem,
                "penalty": penalty,
                "exit_status": exit_status,
                "exit_type": "—",
                "amount": "；".join(amounts[:3]) or None,
                "publish_date": publish_date,
                "title": title,
                "url": url,
                "summary": (problem or penalty or seg[:120])[:160],
            }
        )
    return out


def _row_record(org, reason, title, level, url, date, name, summary):
    status, etype = _exit_row(reason or title, reason)
    return {
        "level": level,
        "source_name": name,
        "kind": "exit",
        "org_name": org,
        "org_type": org_type(org),
        "region": None,
        "problem": None,
        "penalty": status,
        "exit_status": status,
        "exit_type": etype,
        "amount": None,
        "publish_date": date,
        "title": title,
        "url": url,
        "summary": summary or title,
    }


def _exit_from_html(html, title, level, url, date, name):
    """解析公告正文表格：机构名列 + 原因列（主动/被动、解除/中止）。"""
    out = []
    if not html:
        return out
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.select("tr"):
        cells = [re.sub(r"\s+", "", c.get_text()) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        # 跳过把整段正文包进单个 td 的布局行（非名单表）
        if len(cells) == 1 and len(cells[0]) > 30:
            continue
        org, reason = None, ""
        for c in cells:
            cand = _strip_prefix(_extract_org(c) or "")
            if cand and not org:
                if _valid_org(cand):
                    org = cand
            if re.search(r"主动|自愿|违规|解除|中止|终止|暂停", c):
                reason += c + " "
        if org:
            out.append(_row_record(org, reason, title, level, url, date, name, title))
    return out


def extract_exit_notice(title, content, level, url, publish_date, source_name, html=None):
    """退出协议公告：优先正文表格名单，回退标题/正文机构抽取；无具名机构记“未列明具体机构”。"""
    # 1) HTML 表格名单（玉溪 / 红塔等城市公告名单表）
    records = _exit_from_html(html, title, level, url, publish_date, source_name)
    # 2) 标题 / 正文回退抽机构（标题缺失时表格优先）
    if not records:
        org = _org_from_text(title) or _org_from_text(content)
        if not org:
            org = "未列明具体机构"
        exit_status, exit_type = _exit_state((title or "") + " " + (content or ""))
        records = [
            {
                "level": level,
                "source_name": source_name,
                "kind": "exit",
                "org_name": org,
                "org_type": org_type(org),
                "region": None,
                "problem": None,
                "penalty": exit_status,
                "exit_status": exit_status,
                "exit_type": exit_type,
                "amount": None,
                "publish_date": publish_date,
                "title": title,
                "url": url,
                "summary": title,
            }
        ]
    # 同公告同机构去重（噪声表格行 / 表格与标题回退可能重复）
    seen = set()
    dedup = []
    for r in records:
        key = (r["org_name"], r["url"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup
