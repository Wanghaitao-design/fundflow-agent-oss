# -*- coding: utf-8 -*-
"""归集沉淀自检：锁死"钱只收不发要抓到、凑钱看病/发工资/小额一个都不许多抓"。

2026-11-25 配套洗钱第6维入库。背景：老五维全按「钱过境就走」设计
（高过路率要流出≥80%），归集卡流出比只有 1%~34%，五个维度一个都碰不到
（交接本欠账②）。第6维 F「归集沉淀」抓的是反过来的形状：多人多天打款进来、
钱沉淀在账上不走。最大的反例是 langouste 血案「凑钱看病41亲属被冤枉」——
那种形状收一天就一次转走，被「收款天数≥2」和「流出比≤35%」两条硬条件同时挡住。
跑法：.venv\\Scripts\\python.exe agent\\verify\\归集维度自检.py
"""
import sys
from pathlib import Path

import pandas as pd

OSS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(OSS))
import networkx as nx
from gambling_analysis import GamblingAnalyzer


def 裸分析(流水行):
    """流水行: [(本人, 对方, 是否收入, 金额, 天数偏移0起, 备注)]"""
    tx = pd.DataFrame([{
        'owner_id': 本人, 'cp_key': 对方, 'is_income': 收,
        'amount_clean': float(额),
        'datetime_parsed': pd.Timestamp('2026-01-01') + pd.Timedelta(days=天),
        'remark': 备注, 'desc': '',
    } for 本人, 对方, 收, 额, 天, 备注 in 流水行])
    g = nx.DiGraph()
    for 本人, 对方, 收, 额, 天, 备注 in 流水行:
        g.add_edge(本人, 对方, amount=float(额)) if not g.has_edge(本人, 对方) \
            else g[本人][对方].__setitem__('amount', g[本人][对方]['amount'] + float(额))
    a = GamblingAnalyzer.__new__(GamblingAnalyzer)
    a.tx = tx
    a.G = g
    收总 = tx[tx.is_income].groupby('owner_id')['amount_clean'].sum()
    支总 = tx[~tx.is_income].groupby('owner_id')['amount_clean'].sum()
    所有人 = set(tx.owner_id) | set(tx.cp_key)
    a.nodes = {n: {
        'in_flow': float(收总.get(n, 0.0)), 'out_flow': float(支总.get(n, 0.0)),
        'total_flow': float(收总.get(n, 0.0)) + float(支总.get(n, 0.0)),
        'in_degree': g.in_degree(n), 'out_degree': g.out_degree(n),
        'level': 9,
    } for n in 所有人}
    return a


def main():
    # 1 纯归集：6 人分 5 天各打 5000，进 3 万分文不出 → 必须抓到
    行 = [('AGG', f'下级{i}', True, 5000, i, '货款') for i in range(6)]
    a = 裸分析(行)
    a._detect_money_laundering()
    n = a.nodes['AGG']
    assert n['is_launder_suspect'], '纯归集形状没抓到（欠账②没补上）'
    assert any('归集沉淀' in f for f in n['launder_flags']), n['launder_flags']

    # 2 边界恰好：3 人 2 天共 3 万、流出恰 35%、沉淀 65% → 恰好过线要抓到
    行 = [('AGG', f'甲{i}', True, 10000, min(i, 1), '还款') for i in range(3)]
    行.append(('AGG', '提现', False, 10500, 1, ''))
    a = 裸分析(行)
    a._detect_money_laundering()
    assert a.nodes['AGG']['is_launder_suspect'], '恰好达线的归集卡漏了'

    # 3 凑钱看病（langouste 血案反例）：10 亲属一天各转 5000，次日一次转医院 5 万
    行 = [('牵头', f'亲属{i}', True, 5000, 0, '看病凑钱') for i in range(10)]
    行.append(('牵头', '医院', False, 50000, 1, ''))
    a = 裸分析(行)
    a._detect_money_laundering()
    n = a.nodes['牵头']
    assert not any('归集沉淀' in f for f in n['launder_flags']), \
        f'凑钱看病牵头人被第6维冤枉了：{n["launder_flags"]}'

    # 4 发薪老板：收 3 个客户各 2 万分 6 天，发 8 个员工 → 付款人数只有 3 但流出比≈2/3 → 不抓
    行 = [('BOSS', f'客户{i}', True, 20000, i, '工程款') for i in range(3)]
    行 += [('BOSS', f'员工{i}', False, 5000, i + 3, '工资') for i in range(8)]
    a = 裸分析(行)
    a._detect_money_laundering()
    assert not any('归集沉淀' in f for f in a.nodes['BOSS']['launder_flags']), \
        a.nodes['BOSS']['launder_flags']

    # 5 单对象进账（工资卡）：公司 6 天各发 6000 共 3.6 万零流出 → 付款人=1 不算归集
    行 = [('WAGE', '公司', True, 6000, d, '工资') for d in range(6)]
    a = 裸分析(行)
    a._detect_money_laundering()
    assert not a.nodes['WAGE']['is_launder_suspect'], \
        '单付款人的死钱账户被当归集（付款人数闸门失效）'

    # 6 小额闸门：5 人打款共 2.9 万（差 1 千不到线）→ 不抓
    行 = [('AGG', f'下级{i}', True, [5000, 5000, 5000, 5000, 4000][i], i, '') for i in range(5)]
    a = 裸分析(行)
    a._detect_money_laundering()
    assert not any('归集沉淀' in f for f in a.nodes['AGG']['launder_flags']), \
        a.nodes['AGG']['launder_flags']

    # 7 参数搬家没搬丢：五个数必须从判据表读，不许写死
    src = (OSS / 'gambling_analysis.py').read_text(encoding='utf-8')
    for 键 in ['归集沉淀最低流入', '归集沉淀流出比上限', '归集沉淀沉淀下限',
              '归集沉淀最少付款人数', '归集沉淀最少收款天数']:
        assert f"PACK.num('{键}')" in src, f'{键} 没走判据表'
    表 = (OSS / 'case_packs' / 'wangdu' / '03_门槛.csv').read_text(encoding='utf-8')
    assert '归集沉淀·钱只收不发' in 表, '判据表缺归集沉淀这一行'

    # 8 触发第四路在位：归集命中单 flag 即嫌疑（AGGB 形状只有这一个 flag）
    import re
    assert re.search(r'\)\s*or\s+agg_hit\s*\n\s*\)', src), '第四触发路丢了'

    print('归集维度自检 ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
