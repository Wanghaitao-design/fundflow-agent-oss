#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改层级判据之前先把账算出来：完全不靠"跟本批人比排名"，只看每个人自己的绝对量，
几条候选线各能命中多少、冤枉多少。

为什么写这个：`docs/口径.md` 第 5 节要求分析机侧把"按本批排名判代理"改成"按固定标准判"。
但固定线划在哪个数没人能拍（法条里没有这条线），所以先把几组候选线的结果摆出来，
给 main 和用户看着数决定，而不是我蒙一个数再对外说"判得准"。

跑法：
  env MPLCONFIGDIR=/tmp/mplcache /home/wht/orca/fundflow-agent-oss/.venv/bin/python -X utf8 case_packs/门槛试算.py

只算不改：不改算法、不改案由包、不写交付物、不碰 agent/range/reports/。
唯一会写的是 agent/deliverables/range/<卷子名>/dataset（dev 卷本来就要现生成，和跑分脚本一样）。
"""
import copy
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))

from common import CACHE                                          # noqa: E402
from generator import generate, load_scenario                     # noqa: E402
from tools import scan_dataset, build_fund_graph                  # noqa: E402

DEV = ['s30_clean_full_dev', 's30_noise_full_dev', 's100_clean_full_dev',
       's100_noise_full_dev', 's500_noise_full_dev', 's30_innocent_full_dev',
       's500_innocent_full_dev']
AML = ['20K_fanin200cycle200_n30_s11', '20K_fanin200cycle200_n100_s11',
       '20K_fanin200_n100_s11', '20K_cycle200_n100_s11']
AGENT_LEVELS = (1, 2, 3)


def wan(v):
    return f'{v / 10000:g}万' if v >= 10000 else f'{v:g}元'


# 候选线。big>0 表示"流入到得了这个大钱线，付款人数不够也照样算候选"（和现在代码里的写法一致）
def line(label, inflow, indeg, indays, outdeg, big=0):
    return dict(名称=label, inflow=inflow, indeg=indeg, indays=indays, outdeg=outdeg, big=big)


SETS = [
    line('现用线(5千/3人/不看天数/不看转出/5万兜底)', 5000, 3, 1, 0, 50000),
    line('现用线+收款跨2天', 5000, 3, 2, 0, 50000),
    line('现用线+必须有1个下级', 5000, 3, 1, 1, 50000),
    line('2万/3人/跨2天/1下级', 20000, 3, 2, 1, 0),
    line('5万/3人/跨2天/1下级', 50000, 3, 2, 1, 0),
    line('5万/5人/跨2天/1下级', 50000, 5, 2, 1, 0),
    line('10万/3人/跨2天/1下级', 100000, 3, 2, 1, 0),
    line('20万/3人/跨3天/1下级', 200000, 3, 3, 1, 0),
]


def hits(node_facts, s, bad):
    """按一条候选线筛人，返回(命中, 冤枉)。"""
    hit = wrong = 0
    for key, f in node_facts.items():
        ok = (f['in_flow'] >= s['inflow']
              and (f['in_degree'] >= s['indeg'] or f['in_flow'] >= s['big'])
              and (s['indays'] <= 1 or f['in_days'] >= s['indays'])
              and (s['outdeg'] <= 0 or f['out_degree'] >= s['outdeg']))
        if not ok:
            continue
        if bad.get(key, False):
            hit += 1
        else:
            wrong += 1
    return hit, wrong


def dev_truth(name):
    """dev 卷：先生成数据，再读标准答案。返回(数据集目录, {账号: 是不是代理})。"""
    art = generate(**load_scenario(name))
    truth = json.loads(Path(art['标准答案路径']).read_text(encoding='utf-8'))
    # 真值里的写法是「一级代理嫌疑」这种带「嫌疑」两字的标签，别按「一级代理」去比对（比对不上会全 0）
    agent = {a['合成ID']: '代理嫌疑' in (a.get('层级标签') or '') for a in truth['accounts']}
    return art['数据集目录'], agent


def aml_truth(name):
    """AMLSim 卷：真值 = 官方配置里标 isFraud 的账户（没有代理层级概念，只能算"是不是罪犯"）。"""
    case = ROOT / 'amlsim' / '产物' / name
    truth = json.loads((case / 'truth.json').read_text(encoding='utf-8'))
    return str(case / 'dataset'), {a['合成ID']: bool(a['isFraud']) for a in truth['accounts']}


def facts(dataset_dir):
    """跑取数→建图→层级判定（含固定线复核），把每个账号的事实数和最终判层倒出来。"""
    scan = scan_dataset(dataset_dir)
    path = scan['artifacts'].get('完整结果')
    scan = json.loads(Path(path).read_text(encoding='utf-8')) if path else scan
    did = scan['结论']['dataset_id']
    build_fund_graph(did)
    ctx = CACHE[did]
    a = ctx['analyzer']
    a.nodes = copy.deepcopy(ctx['base_nodes'])
    a.overrides, a.rules, a.cluster_evidence = {}, {}, {}
    a._classify_levels()
    out = {str(n): dict(in_flow=float(i.get('in_flow') or 0),
                        in_degree=int(i.get('in_degree') or 0),
                        out_degree=int(i.get('out_degree') or 0),
                        in_days=int(i.get('in_days') or 0),
                        active_days=int(i.get('active_days') or 0),
                        level=i['level']) for n, i in a.nodes.items()}
    CACHE.pop(did, None)
    return out


def q(vals, p):
    """分位数（样本小，取最近档位够用，不装精确）。"""
    if not vals:
        return 0
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, round(p * (len(s) - 1))))
    return s[idx]


def report(kind, name, label):
    dataset_dir, bad = (dev_truth(name) if kind == 'dev' else aml_truth(name))
    node_facts = facts(dataset_dir)
    n_all = sum(bad.values())
    if kind == 'aml':
        # AMLSim 的 isFraud 把整条链上的人都算罪犯，包括最底下只往上送钱的那一层。
        # "代理嫌疑"这一栏不该去抓只出不进的人（真案子里那种人通常是赌客），
        # 所以这份卷子的答案只算**站在收钱位置上**的罪犯：账单里 ≥2 个不同账号给他转过钱。
        # 位置是从账单数出来的，跟程序判成什么无关。全量口径记在 amlsim/产物/成绩单 里，两边都对得上。
        bad = {k: (v and node_facts[k]['in_degree'] >= 2) for k, v in bad.items()}
    n_true = sum(bad.values())
    if kind == 'aml':
        print(f'（这份卷子 IBM 标了 {n_all} 个罪犯，其中站在收钱位置上的 {n_true} 个才是这里的答案；'
              f'剩下 {n_all - n_true} 个只出不进，按设计不该往代理上看）')

    cur_out = sum(1 for f in node_facts.values() if f['level'] in AGENT_LEVELS)
    cur_hit = sum(1 for k, f in node_facts.items() if f['level'] in AGENT_LEVELS and bad.get(k, False))
    cur_wrong = cur_out - cur_hit
    print(f'\n=== {name}（{label}）账号 {len(node_facts)} 个，该被看出来的 {n_true} 个 ===', flush=True)
    print(f'现在这套（排名判定+固定线复核）：判出 {cur_out} 人，命中 {cur_hit}，'
          f'冤枉 {cur_wrong}，漏 {n_true - cur_hit}，判出的人里真货占 '
          f'{(cur_hit / cur_out * 100 if cur_out else 0):.1f}%')

    for s in SETS:
        hit, wrong = hits(node_facts, s, bad)
        out = hit + wrong
        print(f'   {s["名称"]:<36} 判出 {out:>3} 命中 {hit:>3} 冤枉 {wrong:>3} '
              f'漏 {n_true - hit:>3} 真货占比 {(hit / out * 100 if out else 0):>5.1f}%')

    # 划线要看的分布：真代理的中间水平 vs 清白账号的高位（清白账号 90 分位就是"误伤警戒线"）
    true_f = [f for k, f in node_facts.items() if bad.get(k, False)]
    pure_f = [f for k, f in node_facts.items() if not bad.get(k, False)]
    if true_f:
        print('   该被看出来的人：流入中位 {}｜付款人数中位 {}｜收款天数中位 {}'.format(
            wan(statistics.median(f['in_flow'] for f in true_f)),
            round(statistics.median(f['in_degree'] for f in true_f), 1),
            round(statistics.median(f['in_days'] for f in true_f), 1)))
    if pure_f:
        print('   不该被碰的人  ：流入90分位 {}｜付款人数90分位 {}｜收款天数90分位 {}'.format(
            wan(q([f['in_flow'] for f in pure_f], 0.9)),
            q([f['in_degree'] for f in pure_f], 0.9),
            q([f['in_days'] for f in pure_f], 0.9)), flush=True)


if __name__ == '__main__':
    print('固定线试算 —— 只算账不改代码。真值来源：dev 卷=生成器标准答案；AMLSim 卷=官方 isFraud')
    print('注意一：AMLSim 金额是美元量级（中位 252、最大 599.91），下面所有"元"的线在它身上没有可比性，只能看相对高低')
    print('注意二：AMLSim 卷子的答案只算"站在收钱位置上"的罪犯（理由见 report 里的注释）')
    for name in DEV:
        report('dev', name, '自家考卷')
    for name in AML:
        report('aml', name, 'AMLSim 替身考卷')
