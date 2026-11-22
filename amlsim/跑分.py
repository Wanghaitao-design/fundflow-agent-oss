#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AMLSim 卷子跑分：只打印、只写 amlsim/产物，不碰 main 的 agent/range/reports/。

跟 main 的 evaluate.py 走同一条工具链（scan→build→classify→laundering→structure→rank），
区别只有三点：
  1. 真值来自 IBM 的 isFraud（有没有参与洗钱剧本），**没有层级真值**，所以层级准确率不适用；
  2. AMLSim 金额是美元量级（中位数 252），按人民币定的固定线必须先关掉才公平，
     所以每份卷子跑「固定线关」和「固定线开」两遍，开的这遍是用来证明换量级必须重新定线。
  3. **答案分两口报，两口都不许只报好看的那个**（2026-11-11 发现，20 个"罪犯"里 12 个在卷子里
     只有支出没有一笔进账）：
       · 全量答案 = IBM 标 isFraud 的所有账号。严苛：IBM 把整条洗钱链路上的人全算罪犯，
         包括最底下只往上送钱的那一层。我们程序按设计就不该把"只出不进"的人判成代理
         （真案子里那种人通常是赌客），把他们算漏掉是冤枉程序。
       · 收钱位置答案 = isFraud 且账单里确实有 ≥2 个不同账号给他转过钱（站在收钱位置上）。
         这才是"代理嫌疑"这一栏该对的答案。
     位置是从账单本身数出来的（谁给他转过钱），跟程序判成什么无关，所以不算事后改答案。

报数四要素（docs/口径.md 第 3 节）：哪份卷 / 多少账号 / 参数版本 / 种子，一个都不能少。
"""
import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / '产物'
# 「固定线关」= 把下面九条**全填 0**，也就是**退回老办法**（只看这个人在这批人里排第几）。
# 为什么连人数、天数也一起关：这条基准要跟 2026-11-11 之前的老结果对得上，老办法本来一条绝对线都不看。
# 三条"最少几天/最少几个下级"填 0 或 1 都是"不看"（只出现 1 天必然满足 ≥1 天），下面 zeros 里显式写死以免歧义。
# AMLSim 金额中位数只有 252（美元量级），按人民币定的线不关就没法比。
REVIEW_KEYS = ('AGENT_MIN_INFLOW', 'AGENT_BIG_INFLOW', 'AGENT_MIN_IN_DEG', 'AGENT_MIN_IN_DAYS',
               'AGENT_MIN_OUT_DEG', 'GAMBLER_MIN_OUTFLOW', 'GAMBLER_MIN_DAYS',
               'MONEY_LAUNDER_MIN_FLOW', 'LEVEL2_MIN_INFLOW')
AGENT = ('一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑')

import sys
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
sys.path.insert(0, str(ROOT))
from common import CACHE, ga                      # noqa: E402
from tools import (scan_dataset, build_fund_graph, classify_tiers,   # noqa: E402
                   detect_laundering, scan_structure, rank_suspects)

PRISTINE = {k: getattr(ga, k) for k in REVIEW_KEYS}   # 案由包里的原值，跑完要还原


def full(result):
    path = result['artifacts'].get('完整结果')
    return json.loads(Path(path).read_text(encoding='utf-8')) if path else result


def set_review(on):
    zeros = {k: 0 for k in REVIEW_KEYS}
    zeros.update(AGENT_MIN_IN_DAYS=1, AGENT_MIN_OUT_DEG=0, GAMBLER_MIN_DAYS=1)
    values = PRISTINE if on else zeros
    for key, value in values.items():
        setattr(ga, key, value)
    return values


def score(pred, truth):
    """pred/truth 都是 {账号: 布尔}。按 docs/口径.md：命中数、漏掉数、冤枉数、含金量一起报。"""
    c = Counter()
    for acc, is_bad in truth.items():
        c[('TP' if is_bad else 'FP') if pred.get(acc) else ('FN' if is_bad else 'TN')] += 1
    tp, fn, fp, tn = c['TP'], c['FN'], c['FP'], c['TN']
    return {'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
            '召回': round(tp / (tp + fn), 4) if tp + fn else '不适用',
            '冤枉率': round(fp / (fp + tn), 4) if fp + tn else '不适用',
            '含金量': round(tp / (tp + fp), 4) if tp + fp else '不适用'}


def run_case(case_dir, review_on):
    truth = json.loads((case_dir / 'truth.json').read_text(encoding='utf-8'))
    accounts = truth['accounts']
    is_bad = {a['合成ID']: bool(a['isFraud']) for a in accounts}
    failures, results = [], {}
    did = None
    try:
        used = set_review(review_on)
        scan = full(scan_dataset(str(case_dir / 'dataset')))
        if scan['结论'].get('成功') is False:
            raise RuntimeError(json.dumps(scan['异常'], ensure_ascii=False))
        did = scan['结论']['dataset_id']
        failures.extend({'stage': 'scan_dataset', **f} for f in scan['证据']['失败清单'])
        for fn in (build_fund_graph, classify_tiers, detect_laundering, scan_structure, rank_suspects):
            res = full(fn(did, thresholds={}) if fn is classify_tiers else fn(did))
            results[fn.__name__] = res
            if res['结论'].get('成功') is False:
                failures.append({'stage': fn.__name__, '原因': res['异常']})
            if fn is scan_structure:
                failures.extend({'stage': 'scan_structure', '检测器': n, **s}
                                for n, s in res['结论'].get('检测器状态', {}).items() if s['状态'] == '失败')
    except Exception as exc:
        failures.append({'stage': 'scenario', '原因': f'{type(exc).__name__}: {exc}'})
    tiers = {r['账号']: r['层级'] for r in results.get('classify_tiers', {}).get('结论', {}).get('判定', [])}
    launder = {r['账号']: r['洗钱嫌疑'] for r in results.get('detect_laundering', {}).get('结论', {}).get('判定', [])}
    agent_pred = {a: t in AGENT for a, t in tiers.items()}
    dist = Counter(tiers.values())
    fp_list = []
    detail = {r['账号']: r['依据']['指标值'] for r in
              results.get('classify_tiers', {}).get('结论', {}).get('判定', [])}
    # 收钱位置：从账单数出来的「有几个不同账号给他转过钱」。取建图后的节点度数，
    # 不取判层结果里的数——判层失败（比如有向环）时也要能把这个位置数算出来。
    base = (CACHE.get(did) or {}).get('base_nodes') or {}
    feeders = {a: int((base.get(a) or {}).get('in_degree') or 0) for a in is_bad}
    pos_measurable = bool(base)
    is_bad_pos = {a: bool(bad) and feeders.get(a, 0) >= 2 for a, bad in is_bad.items()}
    if not failures:
        for acc, flag in agent_pred.items():
            if flag and not is_bad.get(acc, False):
                m = detail.get(acc, {})
                fp_list.append({'账号': acc, '层级': tiers[acc], '流入': round(m.get('in_flow', 0), 2),
                                '付款人数': m.get('in_degree'), '收款笔数': None})
    row = {'卷子': case_dir.name, '固定线': '开' if review_on else '关（金额量级对不上）',
           '账号数': len(accounts), '剧本账户数': sum(is_bad.values()),
           '种子': truth['metadata']['seed'], '样本': truth['metadata']['sample'],
           '样本SHA256前8': (truth['metadata']['sample_sha256'] or '')[:8],
           '案由包参数版本': ga.PACK.version if hasattr(ga.PACK, 'version') else 'case_packs/wangdu',
           '固定线取值': used if not review_on else PRISTINE,
           '层级分布': dict(dist), '赌客线索': dist.get('赌客线索', 0), '待定外围': dist.get('待定外围', 0),
           '收钱位置罪犯数': sum(is_bad_pos.values()) if pos_measurable else '建图没出结果，数不出位置',
           '只出不进的罪犯数': (sum(1 for a, b in is_bad.items() if b and feeders.get(a, 0) == 0)
                          if pos_measurable else '建图没出结果，数不出位置'),
           '代理嫌疑_vs_isFraud_全量': score(agent_pred, is_bad) if tiers else '判层没出结果',
           '代理嫌疑_vs_收钱位置罪犯': (score(agent_pred, is_bad_pos) if tiers
                              else ('建图没出结果，数不出位置' if not pos_measurable else '判层没出结果')),
           '洗钱嫌疑_vs_isFraud_全量': score(launder, is_bad) if launder else '洗钱判定没出结果',
           '洗钱嫌疑_vs_收钱位置罪犯': (score(launder, is_bad_pos) if launder
                              else ('建图没出结果，数不出位置' if not pos_measurable else '洗钱判定没出结果')),
           '冤枉名单': sorted(fp_list, key=lambda r: -r['流入'])[:10],
           '失败项': failures[:5], '失败数': len(failures)}
    if did:
        CACHE.pop(did, None)
    set_review(True)
    return row


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cases', nargs='+')
    ap.add_argument('--review', choices=['off', 'on', 'both'], default='both')
    args = ap.parse_args()
    rows = []
    for name in args.cases:
        case_dir = OUT / name
        modes = {'off': [False], 'on': [True], 'both': [False, True]}[args.review]
        for mode in modes:
            row = run_case(case_dir, mode)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    stamp = date.today().isoformat()
    (OUT / f'成绩单_{stamp}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'写完 {len(rows)} 行 → amlsim/产物/成绩单_{stamp}.json')
