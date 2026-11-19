# -*- coding: utf-8 -*-
"""抓取进度共享状态：后台抓取线程写入，API 线程读取，供前端进度条轮询。"""
import threading

_lock = threading.Lock()
_state = {
    "phase": "",            # policy / exposure / done
    "stage": "",            # 当前正在处理的源 / 阶段文字
    "source_idx": 0,       # 当前阶段第几个源（1-based）
    "source_total": 1,     # 当前阶段源总数
    "count": 0,             # 本轮已处理条目数
    "percent": 0,           # 0-100
}


def reset():
    with _lock:
        _state.update(phase="", stage="准备开始…", source_idx=0,
                      source_total=1, count=0, percent=0)


def update(**kw):
    with _lock:
        _state.update(kw)


def bump_count(n=1):
    with _lock:
        _state["count"] = _state.get("count", 0) + n


def snapshot():
    with _lock:
        return dict(_state)
