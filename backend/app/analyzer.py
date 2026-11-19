# -*- coding: utf-8 -*-
"""政策解读：本地规则抽取为主，配置大模型后自动补充 / 升级为 LLM 解读。"""
import json
import re
import time
import requests

from . import config, database

# ------------------------------------------------------------ 主题词典
TOPIC_DICT = [
    ("药品目录/用药保障", ["药品目录", "用药保障", "中成药", "生物制品", "创新药", "集采中选药品", "用药"]),
    ("医用耗材", ["医用耗材", "耗材分类", "耗材编码", "植入材料", "口腔种植体", "托槽"]),
    ("医疗服务价格/项目", ["医疗服务价格", "诊疗项目", "立项指南", "诊查", "价格项目"]),
    ("DRG/DIP 付费", ["按病种付费", "按病组", "病种分值", "DRG", "DIP", "分组方案", "清算"]),
    ("长期护理保险", ["长期护理", "长护险", "失能", "护理保险"]),
    ("生育保险", ["生育", "产前检查", "生育津贴"]),
    ("异地就医", ["异地就医", "异地直接结算", "跨省", "省内异地"]),
    ("个人账户共济", ["个人账户", "家庭共济", "个账", "共济"]),
    ("定点机构管理", ["定点医药机构", "定点医疗机构", "定点零售药店", "协议管理", "定点管理"]),
    ("基金监管/智能审核", ["基金监管", "智能监管", "两库", "欺诈骗保", "智能审核", "基金安全", "纠正医药购销"]),
    ("医疗救助/困难群众", ["医疗救助", "困难群众", "低保", "脱贫人口", "资助参保"]),
    ("参保缴费", ["参保", "缴费", "居民医保", "职工医保", "灵活就业", "新就业形态"]),
    ("基层医疗卫生", ["基层医疗卫生", "乡镇卫生院", "社区卫生", "村卫生室", "基层医疗", "家庭医生"]),
    ("门诊统筹/慢特病", ["门诊统筹", "门诊慢特病", "慢特病", "门诊报销", "双通道"]),
    ("医保经办/政务服务", ["经办", "政务服务事项", "办事指南", "清单", "结算服务", "医疗保障经办"]),
    ("数字医保/信息平台", ["信息平台", "接口规范", "医保信息系统", "小程序", "云端", "索引码"]),
]

APPLICABLE_RULES = [
    ("基层医疗卫生机构", ["乡镇卫生院", "社区卫生服务", "村卫生室", "基层医疗卫生", "基层医疗"]),
    ("定点医疗机构", ["定点医疗机构", "医疗机构", "医院", "诊所"]),
    ("定点零售药店", ["定点零售药店", "零售药店", "药店"]),
    ("参保人员（职工/居民）", ["参保人员", "参保群众", "职工", "居民", "灵活就业", "新就业形态"]),
    ("困难群体", ["困难群众", "低保", "脱贫人口", "救助对象"]),
    ("医保经办机构", ["医保局", "经办机构", "医保经办"]),
]

# 基层影响固定 8 维度（与前端矩阵一一对应）；other 兜底不参与关键词命中
IMPACT_DIMENSIONS = [
    ("门诊统筹与慢病", ["门诊统筹", "慢特病", "门诊报销", "双通道", "普通门诊", "门诊待遇"]),
    ("住院与DRG/DIP结算", ["住院", "DRG", "DIP", "病种", "分值", "清算", "按病种", "床旁结算"]),
    ("药品目录与集采配备", ["药品目录", "集采", "中选", "药品", "耗材", "配备", "用药", "采购"]),
    ("医保结算与系统操作", ["结算", "报销", "支付", "经办", "备案", "个人账户", "共济", "参保登记", "异地就医"]),
    ("考核与违规风险", ["监管", "违规", "处罚", "追责", "考核", "协议管理", "欺诈骗保", "风控", "稽核", "追回"]),
    ("信息化与数据上报", ["信息平台", "信息系统", "接口", "数据", "上报", "编码", "小程序", "云端", "索引码"]),
    ("人员与培训", ["培训", "队伍", "人员", "宣传", "告知", "政策解读"]),
    ("其他影响", []),
]

IMPACT_LEVELS = ("高", "中", "低", "未涉及")

# 与乡镇卫生院日常关联度低的事项（降权）
LOW_RELEVANCE = ["遴选公务员", "面试", "大赛", "获奖名单", "公示名单", "网站升级", "平台升级维护", "小程序登录", "答疑", "筹备公告"]

# ---- 解读质量清洗：占位值 / 口号 / 泛化风险 / 无数字标准 ----
# 要素 value 为占位（原文确无信息）时整条剔除
_PLACEHOLDER_VAL = re.compile(r"^(无|暂无|无具体|无相关|无明确|待定|暂无数据|未明确|未规定|未列明|未提供|根据实际|视情况|视实际|按实际|结合实际|N/?A|—|–|-|不适用|具体时限未明确|无具体数字|无具体规定)$", re.I)
# 动作口号：无具体对象/事项的泛化表述
_ACTION_SLOGAN = re.compile(r"^(加强领导|提高认识|加强培训|培训工作人员|做好宣传|加强管理|规范管理|提升(服务|质效|能力)|落实责任|完善制度|关注政策修订动态|关注动态|关注评审结果|关注定点变动|加强沟通|做好日常工作|提高服务质量|提升服务质效|规范服务|加强医保基金使用管理)$")
# 风险：真正的处罚/处理动词 vs 单纯禁止措辞 vs 泛化担忧
_RISK_PENALTY = re.compile(r"追回|退回|拒付|扣除|处罚|追责|罚款|骗保|解除协议|暂停协议|取消定点|扣款|追缴|记入诚信|列入失信|移送司法")
_RISK_FORBID = re.compile(r"不得|禁止|严禁")
_RISK_VAGUE = re.compile(r"不当|不规范|不到位|风险|隐患|不按规定|违规使用|违规行为")
# 标准条目必须含数字与计量单位
_STD_NUM = re.compile(r"\d+\s*(%|％|元|万元|岁|年|日|月|级|档|倍|起付线|封顶线|限额|比例|标准|次|人)")
# 要点过短/纯标签词
_POINT_MIN = 8

# 正文尾部常见噪声（附件清单、联系方式、二维码说明）
_TAIL_NOISE = re.compile(r"(附件[一二三四五六七八九十\d]*[：:].*|电子邮箱[：:].*|通讯地址[：:].*|邮编[：:].*|扫一扫|手机打[开印]|二维码|网站地图|主办单位|承办单位)$")


def _prep_content(content, limit=8000):
    """喂给大模型前的轻度清洗：折叠空白、去尾部噪声行，按字数截断。"""
    if not content:
        return ""
    lines = []
    for ln in content.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln:
            continue
        if _TAIL_NOISE.search(ln):
            continue
        lines.append(ln)
    text = "\n".join(lines)
    return text[:limit]


_EFF_RE = re.compile(r"自?\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起(?:施行|执行|实施|执行)")
_DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")


def _match_topics(text):
    tags = []
    for topic, kws in TOPIC_DICT:
        if any(k in text for k in kws):
            tags.append(topic)
    return tags


def _align_topics(tags):
    """把模型自造标签对齐到标准主题词典；精确命中保留，模糊命中映射，其余剔除。"""
    out = []
    for t in tags or []:
        t = str(t).strip()
        if not t:
            continue
        if any(t == topic for topic, _ in TOPIC_DICT):
            if t not in out:
                out.append(t)
            continue
        for topic, kws in TOPIC_DICT:
            if any(k in t or t in k for k in kws):
                if topic not in out:
                    out.append(topic)
                break
    return out[:5]


def _match_applicable(text):
    out = []
    for name, kws in APPLICABLE_RULES:
        if any(k in text for k in kws):
            out.append(name)
    return out


def _extract_effective_date(text):
    m = _EFF_RE.search(text)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def _policy_type(title, text):
    blob = title + " " + text
    if re.search(r"解读|说明|问答|答问", blob):
        return "政策解读"
    if re.search(r"办法|规定|规程|规则|条例", blob):
        return "管理办法"
    if re.search(r"细则|实施方案|方案|通知", blob) and not re.search(r"公示|公告", blob):
        return "实施细则"
    if re.search(r"目录|清单|名录", blob):
        return "目录清单"
    if re.search(r"公示|公告|通报|名单", blob):
        return "公示公告"
    return "规范性文件"


def _validity(title, text):
    blob = title + " " + text
    if re.search(r"已废止|被废止|失效|停止执行|不再执行|予以废止", blob):
        return "已废止"
    if re.search(r"征求意见", blob):
        return "征求意见"
    if re.search(r"试行|暂行", blob):
        return "试行中"
    return "现行有效"


def _extract_standards(text):
    """抽待遇/支付标准句：须含具体数字与计量单位（比例/金额/限额/起付封顶等）。"""
    out = []
    for s in re.split(r"[。；;\n]", text):
        s = s.strip()
        if len(s) < 8:
            continue
        if _STD_NUM.search(s) and re.search(r"起付线|封顶线|报销比例|限额|标准|支付类别|补助|津贴|筹资|缴费|报销|支付", s):
            if s not in out:
                out.append(s[:120])
    return out[:5]


def _extract_risks(text):
    """抽合规约束/禁止/违规后果句。"""
    out = []
    for s in re.split(r"[。；;\n]", text):
        s = s.strip()
        if 8 <= len(s) <= 120 and re.search(r"不得|禁止|严禁|违规|追回|退回|处罚|追责|不得骗|骗保|扣除|拒付", s):
            if s not in out:
                out.append(s[:120])
    return out[:5]


def _extract_points(text, limit=5):
    sentences = re.split(r"[。；;\n]", text)
    keep = []
    verbs = ("应当", "须", "负责", "规范", "提高", "调整", "落实", "推进", "明确", "统一", "建立", "完善", "做好", "加强", "支持")
    for s in sentences:
        s = s.strip()
        if 8 <= len(s) <= 120 and any(v in s for v in verbs):
            if s not in keep:
                keep.append(s)
        if len(keep) >= limit:
            break
    return keep


def _relevance(title, text, topics):
    score = 30  # 基础分：医保政策对基层均有参考价值
    blob = title + text
    if any(k in blob for k in ["乡镇卫生院", "社区卫生服务", "村卫生室", "基层医疗卫生", "基层医疗"]):
        score += 35
    if any(k in blob for k in ["医疗服务价格", "诊疗项目", "医保支付", "报销", "门诊统筹", "慢特病", "支付类别"]):
        score += 20
    if any(k in blob for k in ["定点医药机构", "定点医疗机构", "协议管理", "定点管理"]):
        score += 12
    if any(k in blob for k in ["药品目录", "医用耗材", "集采"]):
        score += 8
    if any(k in blob for k in ["长期护理", "生育", "医疗救助", "异地就医", "个人账户"]):
        score += 8
    if any(k in blob for k in ["基金监管", "智能审核", "智能监管"]):
        score += 8
    if any(k in blob for k in LOW_RELEVANCE):
        score -= 35
    return max(0, min(100, score))


def _rule_matrix(text):
    """规则粗判 8 维度：命中关键词记“中”，否则显式标未涉及。"""
    matrix, hit = [], 0
    for dim, kws in IMPACT_DIMENSIONS:
        if not kws:
            matrix.append({"dimension": dim, "level": "未涉及", "note": "该维度未提及"})
            continue
        if any(k in text for k in kws):
            matrix.append({"dimension": dim, "level": "中", "note": ""})
            hit += 1
        else:
            matrix.append({"dimension": dim, "level": "未涉及", "note": "该维度未提及"})
    return matrix, hit


def _rule_parent_basis(level, title):
    if level == "national":
        return "顶层政策文件，作为全省、全市医保执行的上位依据。"
    if level == "provincial":
        return "省级政策文件，承接国家顶层制度，指导市级落地执行。"
    if level == "municipal":
        return "市级落地执行文件，承接国家、省级政策要求。"
    return "政策层级待核验，未建立明确上位关联。"


def _extract_key_data(text):
    """抽原文含数字与单位的关键数据短句（比例/金额/日期/数量等）。"""
    out = []
    for s in re.split(r"[。；;\n]", text):
        s = s.strip()
        if 4 <= len(s) <= 60 and _STD_NUM.search(s):
            if s not in out:
                out.append(s)
        if len(out) >= 5:
            break
    return out


def _rule_analyze(title, doc_no, publish_date, content, level=None):
    blob = f"{title}\n{content}"
    topics = _match_topics(blob)
    applicable = _match_applicable(blob)
    eff = _extract_effective_date(content)
    points = _extract_points(content)
    rel = _relevance(title, content, topics)

    # 规则摘要：取首段目的句 + 要点；剥掉“各省/各州…：”呼告前缀
    first = re.split(r"[。；\n]", content)
    purpose = next((s.strip() for s in first if len(s.strip()) > 15), "")
    purpose = re.sub(r"^[^：:，,；;]{2,30}[：:]", "", purpose).strip()
    summary = purpose[:160]
    if points:
        summary += " " + "；".join(points[:2])[:160]

    if rel >= 70:
        note = "与乡镇卫生院业务高度相关，建议重点研读并对照执行。"
    elif rel >= 45:
        note = "与基层医保经办、诊疗或结算有一定关联，建议了解掌握。"
    else:
        note = "多为宏观/专项事项或内部事务，作为背景了解即可。"

    matrix, hit = _rule_matrix(blob)
    if hit == 0:
        impact_level = "未涉及"
    elif rel >= 70:
        impact_level = "高"
    elif rel >= 45:
        impact_level = "中"
    else:
        impact_level = "低"

    return {
        "keywords": [k for _, kws in TOPIC_DICT for k in kws if k in blob][:12],
        "topic_tags": topics,
        "applicable_to": applicable,
        "effective_date": eff,
        "relevance": rel,
        "relevance_note": note,
        "key_points": points,
        "ai_summary": summary[:300],
        "ai_type": "rule",
        "policy_type": _policy_type(title, content),
        "validity": _validity(title, content),
        "core_elements": [],
        "actions": [],
        "risks": _extract_risks(content),
        "standards": _extract_standards(content),
        "impact_level": impact_level,
        "impact_matrix": matrix,
        "parent_basis": _rule_parent_basis(level, title),
        "city_impact": "",
        "key_data": _extract_key_data(content),
    }


# ------------------------------------------------------------ 大模型预留
def _dedup(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _dict_to_text(e):
    """把模型偶发返回的对象元素转成干净中文文本，避免出现 Python repr。"""
    if e is None:
        return ""
    if isinstance(e, str):
        return e.strip()
    if not isinstance(e, dict):
        return str(e).strip()
    single = next((e[k] for k in ("text", "内容", "value", "what", "事项", "动作", "风险", "标准", "说明", "摘要") if e.get(k)), None)
    if single is not None:
        return str(single).strip()
    who = next((e[k] for k in ("who", "主体", "对象", "适用对象") if e.get(k)), None)
    what = next((e[k] for k in ("what", "事项", "动作", "内容", "要求", "标准") if e.get(k)), None)
    if who and what:
        return f"{who}：{what}".strip("：")
    parts = [f"{k}：{v}" for k, v in e.items() if v]
    return "；".join(parts).strip()


def _match_dim(name):
    name = str(name or "").strip()
    for dim, _ in IMPACT_DIMENSIONS:
        if name == dim or name in dim or dim in name:
            return dim
    return None


def _norm_matrix(parsed):
    """把模型输出归一到固定 8 维度；分级枚举校验，未涉及显式标注；缺维度补齐。"""
    by_dim = {}
    raw = parsed.get("impact_matrix")
    if isinstance(raw, list):
        for e in raw:
            if not isinstance(e, dict):
                continue
            dim = _match_dim(e.get("dimension"))
            if not dim or dim in by_dim:
                continue
            lv = str(e.get("level") or "").strip()
            note = str(e.get("note") or "").strip()
            if lv not in IMPACT_LEVELS:
                lv = "未涉及"
            if lv == "未涉及":
                note = "该维度未提及"
            by_dim[dim] = {"dimension": dim, "level": lv, "note": note}
    matrix = []
    for dim, _ in IMPACT_DIMENSIONS:
        matrix.append(by_dim.get(dim, {"dimension": dim, "level": "未涉及", "note": "该维度未提及"}))
    parsed["impact_matrix"] = matrix

    lv = str(parsed.get("impact_level") or "").strip()
    parsed["impact_level"] = lv if lv in IMPACT_LEVELS else "未涉及"
    parsed["parent_basis"] = str(parsed.get("parent_basis") or "").strip()
    parsed["city_impact"] = str(parsed.get("city_impact") or "").strip()
    kd = parsed.get("key_data")
    if not isinstance(kd, list):
        kd = []
    parsed["key_data"] = [t for t in (_dict_to_text(x) for x in kd) if t]
    return parsed


def _sanitize_llm(parsed, content):
    """对大模型输出做质量兜底：剔除占位要素、口号动作、泛化风险、无数字标准与过短要点。"""
    def keep_std(s):
        return len(s) >= 6 and bool(_STD_NUM.search(s))

    def keep_risk(s):
        if len(s) < 8:
            return False
        penalty = bool(_RISK_PENALTY.search(s))
        forbid = bool(_RISK_FORBID.search(s))
        vague = bool(_RISK_VAGUE.search(s))
        # 只有泛化担忧、没有具体处罚/处理动作 → 不算红线
        if vague and not penalty:
            return False
        return penalty or forbid

    def keep_action(s):
        return len(s) >= 8 and not _ACTION_SLOGAN.match(s.strip())

    def keep_point(s):
        return len(s) >= _POINT_MIN and not _ACTION_SLOGAN.match(s.strip())

    parsed["standards"] = [s for s in parsed.get("standards", []) if keep_std(str(s))]
    parsed["risks"] = [s for s in parsed.get("risks", []) if keep_risk(str(s))]
    parsed["actions"] = _dedup([s for s in parsed.get("actions", []) if keep_action(str(s))])
    parsed["key_points"] = _dedup([s for s in parsed.get("key_points", []) if keep_point(str(s))])

    elems = []
    for e in parsed.get("core_elements", []):
        if not isinstance(e, dict):
            continue
        label, value = str(e.get("label") or "").strip(), str(e.get("value") or "").strip()
        if label and value and len(value) >= 2 and not _PLACEHOLDER_VAL.match(value):
            elems.append({"label": label, "value": value})
    parsed["core_elements"] = elems

    parsed["topic_tags"] = _dedup(parsed.get("topic_tags", []))
    parsed["applicable_to"] = _dedup(parsed.get("applicable_to", []))

    # 摘要过短/空泛时置空，交由 analyze 用规则目的句兜底
    summary = str(parsed.get("ai_summary") or parsed.get("summary") or "").strip()
    if len(summary) < 25:
        summary = ""
    parsed["ai_summary"] = summary
    _norm_matrix(parsed)
    return parsed


def _llm_creds():
    return (
        database.get_setting("llm_base_url", "") or config.LLM_BASE_URL,
        database.get_setting("llm_api_key", ""),
        database.get_setting("llm_model", "") or config.LLM_MODEL,
    )


def _post_chat(url, headers, payload, retries=1):
    """聊天接口请求：超时/网络/5xx 退避重试一次，降低免费接口波动导致的回退率。"""
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=config.LLM_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.2)
    raise last


def llm_chat_json(system, user, temperature=0.2):
    """通用 OpenAI 兼容 JSON 调用（供政策问答等复用）；失败返回 None，由调用方回退。"""
    base, key, model = _llm_creds()
    if not base or not key:
        return None
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    base_payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
    }
    for use_json in (True, False):
        payload = dict(base_payload)
        if use_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = _post_chat(url, headers, payload)
            r.raise_for_status()
            data = r.json()["choices"][0]["message"]["content"]
            return json.loads(data)
        except Exception as e:
            if not use_json:
                print(f"[LLM] 问答调用失败，回退规则：{e!r}")
                return None


def _llm_analyze(title, doc_no, publish_date, content):
    base = database.get_setting("llm_base_url", "") or config.LLM_BASE_URL
    key = database.get_setting("llm_api_key", "")
    model = database.get_setting("llm_model", "") or config.LLM_MODEL
    if not base or not key:
        return None
    org = database.get_setting("site_org", config.SITE_CONTEXT.get("org", "乡镇卫生院"))
    sys_prompt = (
        f"你是资深医保政策解读专家，服务对象为{org}（基层医疗机构）。"
        "先通读政策原文，只依据原文事实输出，不得编造原文没有的数字、比例、日期或结论。"
        "用中文输出严格 JSON（不要 markdown、不要解释性文字），字段与要求如下：\n"
        "1. summary：3-4 句通俗解读，依次说明【这份政策是什么】【主要变化或关键安排（尽量带上原文出现的数字/比例/时间）】【对乡镇卫生院或参保群众意味着什么】；"
        "禁止“提升质效、规范管理、加强服务”这类无信息空话；原文无数字时不要硬凑。\n"
        "2. topic_tags：数组，从医保经办、参保缴费、异地就医、门诊统筹/慢特病、定点机构管理、基金监管、药品目录、医用耗材、医疗服务价格、DRG/DIP、长期护理、生育、医疗救助、个人账户共济、基层医疗卫生、数字医保等标准主题中选取最贴合的。\n"
        "3. applicable_to：数组，面向基层机构/人员（乡镇卫生院、定点医疗机构、定点零售药店、参保人员、困难群体、医保经办机构等）。\n"
        "4. effective_date：YYYY-MM-DD 或 null。\n"
        "5. key_points：3-5 条完整句子，每条讲清一个具体事项或动作（≥10 字）；禁止 2-6 字的标签词、口号词。\n"
        "6. relevance：0-100，结合基层是否涉及报销结算、诊疗项目、定点管理、经办服务、药品耗材等来评；与基层无关的宏观/内部事项给低分。\n"
        "7. relevance_note：一句话写明相关性理由与执行提示，不要只给“高度相关”。\n"
        "8. policy_type：管理办法/实施细则/规范性文件/政策解读/目录清单/公示公告 之一。\n"
        "9. validity：现行有效/试行中/征求意见/已废止/未知 之一。\n"
        "10. core_elements：对象数组，每项 {label,value}，只提炼原文确实给出的要素（发文主体、适用对象、适用条件、标准或额度、办理时限、执行时间等）；"
        "原文没有的要素不要列；value 不得用“无、待定、根据实际情况”等占位。\n"
        "11. actions：数组，站在乡镇卫生院角度的具体可执行动作（谁、做什么、依据/时限）；不要“加强领导、提高认识、关注动态、加强培训”这类空口号。\n"
        "12. risks：数组，仅收录原文明确写出的禁止性规定、违规处理（追回/拒付/处罚/解除协议等）红线；"
        "不得泛化“基金使用不当、行为不规范、服务不到位”这类推测；原文无明确红线则空数组。\n"
        "13. standards：数组，报销比例/起付线/封顶线/限额/补助津贴等待遇支付标准，每条必须带具体数字与单位；纯描述、无数字的不放入；无则空数组。\n"
        "14. impact_level：对乡镇卫生院（基层）的整体影响程度，取值 高/中/低/未涉及 之一。\n"
        "15. impact_matrix：对象数组，必须覆盖以下固定 8 个维度，每项 {dimension, level, note}；"
        "dimension 严格使用：门诊统筹与慢病、住院与DRG/DIP结算、药品目录与集采配备、医保结算与系统操作、考核与违规风险、信息化与数据上报、人员与培训、其他影响；"
        "level 取值 高/中/低/未涉及；未涉及的维度 note 填“该维度未提及”；涉及的维度 note 用一句话写明原文依据（谁、做什么、影响哪块业务），不要空话。\n"
        "16. parent_basis：一句话说明政策层级与上位衔接（国家→省→市）；若为顶层文件或原文未建立明确上位关联，如实写明，不要编造上位文件名称或文号。\n"
        "17. city_impact：一句话说明对市级/医保经办层面的影响（执行主体、覆盖的机构/企业/系统、关键执行节点、涉及业务）；基层文件则写市级如何组织落地。\n"
        "18. key_data：数组，提炼原文出现的关键数据（比例、金额、限额、日期、数量、批次等），每条保留数字与单位；无则空数组。"
    )
    user = (
        f"标题：{title}\n文号：{doc_no or '无'}\n发布日期：{publish_date or '无'}\n"
        f"正文：{_prep_content(content)}\n请按上述要求输出 JSON。"
    )
    base_payload = {
        "model": model,
        "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
        "temperature": 0.2,
    }
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # 先按 JSON 模式请求；若该型号不支持 response_format，去掉该参数降级重试一次，仍失败再回退规则。
    for use_json_mode in (True, False):
        payload = dict(base_payload)
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = _post_chat(url, headers, payload)
            r.raise_for_status()
            data = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(data)
            parsed["ai_type"] = "llm"
            # 模型字段 summary 对齐到前端/规则使用的 ai_summary（兼容 {text:...} 对象）
            parsed["ai_summary"] = _dict_to_text(parsed.get("ai_summary") or parsed.get("summary") or "")
            for f in ("topic_tags", "applicable_to", "key_points", "keywords", "actions", "risks", "standards"):
                if not isinstance(parsed.get(f), list):
                    parsed[f] = []
                else:
                    parsed[f] = [t for t in (_dict_to_text(e) for e in parsed[f]) if t]
            # 核心要素：归一为 [{label,value}]
            elems = parsed.get("core_elements")
            if not isinstance(elems, list):
                elems = []
            norm_elems = []
            for e in elems:
                if isinstance(e, dict):
                    label = str(e.get("label") or e.get("名称") or "").strip()
                    value = str(e.get("value") or e.get("内容") or "").strip()
                    if label and value:
                        norm_elems.append({"label": label, "value": value})
                elif isinstance(e, str) and e.strip():
                    norm_elems.append({"label": "要素", "value": e.strip()})
            parsed["core_elements"] = norm_elems
            parsed["policy_type"] = str(parsed.get("policy_type") or "规范性文件").strip() or "规范性文件"
            parsed["validity"] = str(parsed.get("validity") or "现行有效").strip() or "现行有效"
            try:
                parsed["relevance"] = max(0, min(100, int(float(parsed.get("relevance", 50)))))
            except (TypeError, ValueError):
                parsed["relevance"] = 50
            parsed.setdefault("relevance_note", "")
            parsed.setdefault("effective_date", None)
            parsed = _sanitize_llm(parsed, content)
            return parsed
        except Exception as e:
            if not use_json_mode:
                print(f"[LLM] 调用失败，回退规则解读：{e!r}")
                return None


def analyze(title, doc_no, publish_date, content, level=None):
    use_llm = database.get_setting("llm_enabled", "0") == "1"
    result = None
    if use_llm:
        result = _llm_analyze(title, doc_no, publish_date, content)
    if result is None:
        result = _rule_analyze(title, doc_no, publish_date, content, level)

    # 主题标签 / 适用对象归一到标准词典，保证与前端主题筛选、facets 一致；
    # 大模型的摘要、要点、相关度保留，仅在标准词典命中时覆盖标签与对象。
    blob = f"{title}\n{content}"
    std_topics = _match_topics(blob)
    if std_topics:
        result["topic_tags"] = std_topics[:5]
    else:
        result["topic_tags"] = _align_topics(result.get("topic_tags", []))
    std_app = _match_applicable(blob)
    if std_app:
        result["applicable_to"] = std_app[:4]
    if not result.get("keywords"):
        result["keywords"] = [k for _, kws in TOPIC_DICT for k in kws if k in blob][:12]
    # 新维度字段兜底，保证前端分区可安全读取
    result.setdefault("policy_type", "规范性文件")
    result.setdefault("validity", "现行有效")
    for f in ("core_elements", "actions", "risks", "standards", "impact_matrix", "key_data"):
        if not isinstance(result.get(f), list):
            result[f] = []
    result.setdefault("impact_level", "未涉及")
    result.setdefault("parent_basis", "")
    result.setdefault("city_impact", "")

    # LLM 清洗后摘要/要点过空时，用规则抽取兜底，避免出现空分区
    rule = _rule_analyze(title, doc_no, publish_date, content, level)
    if len(str(result.get("ai_summary") or "")) < 25:
        result["ai_summary"] = rule["ai_summary"]
    if not result.get("key_points"):
        result["key_points"] = rule["key_points"]
    if not result.get("impact_matrix"):
        result["impact_matrix"] = rule["impact_matrix"]
    if result.get("impact_level") not in IMPACT_LEVELS:
        result["impact_level"] = rule["impact_level"]
    if not result.get("parent_basis"):
        result["parent_basis"] = rule["parent_basis"]
    if not result.get("relevance_note"):
        rel = result.get("relevance", rule["relevance"])
        if rel >= 70:
            result["relevance_note"] = "与乡镇卫生院业务高度相关，建议重点研读并对照执行。"
        elif rel >= 45:
            result["relevance_note"] = "与基层医保经办、诊疗或结算有一定关联，建议了解掌握。"
        else:
            result["relevance_note"] = "多为宏观/专项事项或内部事务，作为背景了解即可。"
    return result


def save_analysis(conn, policy_id, analysis):
    """将解读结果写入 analysis 表（插入或更新），供抓取入库与批量重解读复用。"""
    dumps = lambda obj: json.dumps(obj or [], ensure_ascii=False)
    conn.execute(
        """INSERT INTO analysis(policy_id, keywords, topic_tags, applicable_to, effective_date,
               relevance, relevance_note, key_points, ai_summary, ai_type,
               policy_type, validity, core_elements, actions, risks, standards,
               impact_level, impact_matrix, parent_basis, city_impact, key_data)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(policy_id) DO UPDATE SET
             keywords=excluded.keywords, topic_tags=excluded.topic_tags,
             applicable_to=excluded.applicable_to, effective_date=excluded.effective_date,
             relevance=excluded.relevance, relevance_note=excluded.relevance_note,
             key_points=excluded.key_points, ai_summary=excluded.ai_summary, ai_type=excluded.ai_type,
             policy_type=excluded.policy_type, validity=excluded.validity,
             core_elements=excluded.core_elements, actions=excluded.actions,
             risks=excluded.risks, standards=excluded.standards,
             impact_level=excluded.impact_level, impact_matrix=excluded.impact_matrix,
             parent_basis=excluded.parent_basis, city_impact=excluded.city_impact,
             key_data=excluded.key_data,
             created_at=datetime('now','localtime')""",
        (
            policy_id,
            dumps(analysis.get("keywords")), dumps(analysis.get("topic_tags")),
            dumps(analysis.get("applicable_to")), analysis.get("effective_date"),
            analysis.get("relevance"), analysis.get("relevance_note"),
            dumps(analysis.get("key_points")), analysis.get("ai_summary"), analysis.get("ai_type"),
            analysis.get("policy_type"), analysis.get("validity"),
            dumps(analysis.get("core_elements")), dumps(analysis.get("actions")),
            dumps(analysis.get("risks")), dumps(analysis.get("standards")),
            analysis.get("impact_level"), dumps(analysis.get("impact_matrix")),
            analysis.get("parent_basis"), analysis.get("city_impact"),
            dumps(analysis.get("key_data")),
        ),
    )
