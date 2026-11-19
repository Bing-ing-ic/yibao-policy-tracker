# -*- coding: utf-8 -*-
"""全局配置：官方抓取源、栏目、定时任务、大模型接口。

所有抓取源均为政府官方站点：
- 国家医疗保障局 https://www.nhsa.gov.cn            （主线指导）
- 云南省医疗保障局 https://ylbz.yn.gov.cn           （政策引导）
- 玉溪市医疗保障局（玉溪市政府门户 市医保局栏目）    （政策执行）
"""
import os

_here = os.path.dirname(os.path.abspath(__file__))          # backend/app
BACKEND_DIR = os.path.dirname(_here)                        # backend
BASE_DIR = os.path.dirname(BACKEND_DIR)                     # 项目根
DATA_DIR = os.path.join(BACKEND_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "policies.db")

# ---------------------------------------------------------------- 站点源
# level: national / provincial / municipal
SOURCES = [
    {
        "level": "national",
        "source_name": "国家医疗保障局",
        "home": "https://www.nhsa.gov.cn",
        "columns": [
            {"key": "policy_doc", "name": "政策文件", "url": "https://www.nhsa.gov.cn/col/col104/index.html"},
            {"key": "policy_read", "name": "政策解读", "url": "https://www.nhsa.gov.cn/col/col105/index.html"},
            {"key": "notice", "name": "通知公告", "url": "https://www.nhsa.gov.cn/col/col109/index.html"},
        ],
    },
    {
        "level": "provincial",
        "source_name": "云南省医疗保障局",
        "home": "https://ylbz.yn.gov.cn",
        "columns": [
            {"key": "policy_doc", "name": "政策文件", "url": "https://ylbz.yn.gov.cn/zfxxgk/zcwj/qtwj/"},
            {"key": "policy_read", "name": "政策解读", "url": "https://ylbz.yn.gov.cn/zfxxgk/fdzdgknr/zcjd/"},
            {"key": "notice", "name": "通知公告", "url": "https://ylbz.yn.gov.cn/zfxxgk/fdzdgknr/tzgg/"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "玉溪市医疗保障局",
        "home": "http://www.yuxi.gov.cn",
        "columns": [
            {
                "key": "policy_doc",
                "name": "政策文件及解读",
                "url": "http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?channelId=16576&pageNo={page}&path=yxszfxxgk",
            },
            {
                "key": "notice",
                "name": "通知公告",
                "url": "http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?channelId=16270&pageNo={page}&path=yxszfxxgk",
            },
            {
                "key": "key_area",
                "name": "重点领域信息公开",
                "url": "http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?channelId=16577&pageNo={page}&path=yxszfxxgk",
            },
            {
                "key": "guide",
                "name": "办事指南",
                "url": "http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?channelId=19171&pageNo={page}&path=yxszfxxgk",
            },
        ],
    },
    # ---- 玉溪市下辖区县医保部门（同套政务 CMS，归市级执行层） ----
    {
        "level": "municipal",
        "source_name": "澄江市医疗保障局",
        "home": "https://www.yncj.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.yncj.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=cjxzfxxgk&channelId=16672&pageNo={page}"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "江川区医疗保障局",
        "home": "https://www.ynjc.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.ynjc.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=jcqzfxxgk&channelId=18583&pageNo={page}"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "红塔区医疗保障局",
        "home": "https://www.hongta.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.hongta.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=htqzfxxgk&channelId=3096&pageNo={page}"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "通海县医疗保障局",
        "home": "https://www.tonghai.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.tonghai.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=thxzfxxgk&channelId=17050&pageNo={page}"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "华宁县医疗保障局",
        "home": "https://www.huaning.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.huaning.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=hnxzfxxgk&channelId=16815&pageNo={page}"},
        ],
    },
    {
        "level": "municipal",
        "source_name": "元江县医疗保障局",
        "home": "https://www.yjx.gov.cn",
        "columns": [
            {"key": "dept_policy", "name": "区县医保动态与文件", "url": "https://www.yjx.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=yjxzfxxgk&channelId=19053&pageNo={page}"},
        ],
    },
]

# 政策抓取起始日期：仅保留 2024 年至今；日期缺失的条目暂留待详情日期补全
MIN_POLICY_DATE = os.environ.get("MIN_POLICY_DATE", "2024-01-01")

# 列表抓取页数（1 = 仅首页）；覆盖 2024 年至今所需分页
LIST_PAGES = int(os.environ.get("LIST_PAGES", "4"))
# 详情页超时（连接 / 读取分离）、并发礼貌间隔
REQUEST_TIMEOUT_CONNECT = 10
REQUEST_TIMEOUT_READ = 25
REQUEST_DELAY = 0.6
MAX_DETAIL_CHARS = 20000
# 抓取重试：可重试状态码 + 网络/超时错误；指数退避 base * 2**(n-1)
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "3"))
RETRY_BACKOFF = 1.2
RETRY_STATUS = {429, 500, 502, 503, 504}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------- 曝光台源
# 违规案例通报 + 退出医保协议机构公告，均来自官方站点
EXPOSURE_SOURCES = [
    {
        "level": "national",
        "source_name": "国家医疗保障局",
        "home": "https://www.nhsa.gov.cn",
        "case_lists": ["https://www.nhsa.gov.cn/col/col14/index.html", "https://www.nhsa.gov.cn/col/col14/index_1.html"],
        "case_keywords": ["曝光", "典型案例", "违反医保协议", "违规使用医保基金", "欺诈骗保"],
        "exit_lists": [],
    },
    {
        "level": "provincial",
        "source_name": "云南省医疗保障局",
        "home": "https://ylbz.yn.gov.cn",
        "case_lists": ["https://ylbz.yn.gov.cn/ztzl/ybpgt/index.html"],
        "case_keywords": ["案例通报", "典型案例", "违法违规", "违规使用医保基金"],
        "exit_lists": ["https://ylbz.yn.gov.cn/zfxxgk/fdzdgknr/tzgg/index.html"],
        "exit_keywords": ["终止", "中止", "解除", "退出"],
    },
    {
        "level": "municipal",
        "source_name": "玉溪市医疗保障局",
        "home": "http://www.yuxi.gov.cn",
        "case_lists": ["http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=yxszfxxgk&channelId=20774&pageNo=1&topChannelId=1680"],
        "case_keywords": ["典型案例", "行政处罚", "违法违规", "违规使用医保基金"],
        "exit_lists": ["http://www.yuxi.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=yxszfxxgk&channelId=16270&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    # ---- 玉溪下辖区县：退出协议公示多发布在各自区县站点栏目，市级列表不聚合 ----
    {
        "level": "municipal",
        "source_name": "澄江市医疗保障局",
        "home": "https://www.yncj.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.yncj.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=cjxzfxxgk&channelId=16672&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    {
        "level": "municipal",
        "source_name": "江川区医疗保障局",
        "home": "https://www.ynjc.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.ynjc.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=jcqzfxxgk&channelId=18583&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    {
        "level": "municipal",
        "source_name": "红塔区医疗保障局",
        "home": "https://www.hongta.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.hongta.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=htqzfxxgk&channelId=3096&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    {
        "level": "municipal",
        "source_name": "通海县医疗保障局",
        "home": "https://www.tonghai.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.tonghai.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=thxzfxxgk&channelId=17050&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    {
        "level": "municipal",
        "source_name": "华宁县医疗保障局",
        "home": "https://www.huaning.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.huaning.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=hnxzfxxgk&channelId=16815&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
    {
        "level": "municipal",
        "source_name": "元江县医疗保障局",
        "home": "https://www.yjx.gov.cn",
        "case_lists": [],
        "case_keywords": [],
        "exit_lists": ["https://www.yjx.gov.cn/yxgovfront/newDepartmentContentds.jspx?path=yjxzfxxgk&channelId=19053&pageNo=1"],
        "exit_keywords": ["解除", "中止", "终止", "退出", "暂停"],
    },
]

# ---------------------------------------------------------------- 定时任务
# daily / weekly；可在前端“抓取设置”里修改并写入 settings 表
DEFAULT_SCHEDULE = "daily"          # daily | weekly
DAILY_HOUR = 6                      # 每日 06:00 抓取
WEEKLY_WEEKDAY = 1                  # 每周一（0=周一 ... 6=周日）
WEEKLY_HOUR = 6

# ---------------------------------------------------------------- 大模型（OpenAI 兼容）
# 默认对接智谱 GLM-4-Flash（永久免费，国内直连）；留空 API Key 则使用本地规则解读，配置后自动切换，失败自动回退规则。
# 智谱注册：https://open.bigmodel.cn （手机号即开，控制台获取 API Key）；模型填 glm-4-flash。
# 备选：豆包方舟 https://ark.cn-beijing.volces.com/api/v3 （模型填接入点 ID ep-xxxxxx）。
LLM_ENABLED = os.environ.get("LLM_ENABLED", "0") == "1"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "glm-4-flash")
LLM_TIMEOUT = 30
# 每轮抓取路径最多调用大模型解读的条数（0=不限）；超出后本轮其余条目走规则解读，控制 runner 总时长与额度
LLM_MAX_PER_RUN = int(os.environ.get("LLM_MAX_PER_RUN", "0"))

# 站点身份（用于解读时标注适用语境）
SITE_CONTEXT = {
    "org": "玉溪澄江市乡镇卫生院",
    "level": "基层医疗机构（乡镇卫生院）",
}
