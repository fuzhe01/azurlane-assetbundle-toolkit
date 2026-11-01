# -*- coding: utf-8 -*-
"""探针退出码契约：把「打印了失败但 exit 0」这类假绿统一成非零退出。

背景（2026-10-27 实测）：WF-16 六件套第 2/3 件传 `lafeiii_3`（本项目画廊根本没有该模型），
探针打印 `{"key":"lafeiii_3","skip":"no skin"}` 后**直接走到文件末尾**，退出码 0，runner 记成通过。
同类的还有 `interact_verify.py` 打完「总判定: 有未通过项」也不退出非零。
判据与退出码脱节 ⇒ 回归永远是绿的，真故障来了也看不出来。

约定（三档）：
  0 = 判据成立（真 PASS）
  2 = 探针自身故障（拿不到执行上下文 / 端口不通 / Chrome 起不来），与产品无关
  3 = 未评估（样本不在画廊、页面脚本未就绪、超时未加载、脚本抛错）——**不是通过**

用法：
    from probe_exit import bad_reason, available_keys
    bad = bad_reason(payload)          # payload 可以是 JSON 串或 dict
    if bad:
        print(f'[NOT-EVALUATED] {bad}'); print(available_keys()); sys.exit(3)
"""
import json
import os

# 探针 payload 里出现即代表「没真正评估」的键
BAD_KEYS = ('skip', 'fail', 'err')


def bad_reason(payload):
    """返回非空字符串 = 该探针没有真正评估；返回 '' = 可以判 PASS。"""
    if payload is None:
        return '探针没有拿到任何 payload'
    obj = payload
    if isinstance(payload, str):
        s = payload.strip()
        if s.startswith('EVALERR'):
            return '页面脚本抛错: ' + s[:160]
        if s.startswith('ERR '):
            return '页面脚本抛错: ' + s[:160]
        try:
            obj = json.loads(s)
        except Exception:
            # 非 JSON 输出（如 l2d_coord_forensics 的正常摘要就是缩进 JSON，这里只是兜底）
            return ''
    if not isinstance(obj, dict):
        return ''
    for k in BAD_KEYS:
        v = obj.get(k)
        if v:
            return f'{k}={v}' if not isinstance(v, bool) else f'{k}=true'
    return ''


def available_keys(index_json=None):
    """本项目画廊实有的 live2d 模型 key（从 index.json 读，不写死）。"""
    if index_json is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        index_json = os.path.join(root, 'Output', 'gallery_v2', 'index.json')
    try:
        with open(index_json, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return '(读不到 index.json，无法列出可用样本)'
    keys = set()
    for s in d.get('ships') or []:
        for k in s.get('live2dSkins') or []:
            keys.add(k)
    return ', '.join(sorted(keys)) if keys else '(index.json 里没有 live2d 模型)'
