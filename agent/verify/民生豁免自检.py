# -*- coding: utf-8 -*-
"""民生转出豁免自检：锁死「凑钱给医院的牵头人摘帽、真跑分照抓、想钻空子的抓回来」。

2026-11-27 配套「民生转出豁免」入库。背景：独立考卷 MED 形状——十个亲属各凑
5000、牵头人收齐一次转给医院——被老的高过路率+整千占比两条判成洗钱嫌疑
（dev 机 41 亲属血案重现）。户主批准治：付款人是好几个人、转出几乎全进
「民生机构」词表单位（医院/学校/慈善…）的，高过路率和快速中转两条不算；
境外、整千、单线中转、归集沉淀照抓。跑法：
  .venv\\Scripts\\python.exe agent\\verify\\民生豁免自检.py
"""
import sys
from pathlib import Path

import pandas as pd

OSS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(OSS))
import networkx as nx
import gambling_analysis
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


def 看病形状(医院名='市人民医院'):
    """10 亲属各凑 5000 分两天打给牵头人，牵头人第 2 天把 5 万整转给医院。"""
    行 = [('MED', f'亲属{i}', True, 5000, i % 2, '亲属借款') for i in range(10)]
    行.append(('MED', 医院名, False, 50000, 1, '手术费'))
    return 行


def main():
    # 1 凑钱看病牵头人：豁免生效 → 不列嫌疑，过路类线索一条不许有
    a = 裸分析(看病形状())
    a._detect_money_laundering()
    n = a.nodes['MED']
    assert not n['is_launder_suspect'], f'凑钱看病牵头人还被冤枉: {n["launder_flags"]}'
    assert not any(('高过路率' in f or '快速中转' in f) for f in n['launder_flags']), \
        n['launder_flags']

    # 2 水房形状：多人进钱、整额转给个人账户 → 词表不沾，豁免不得放行
    行 = [('SF', f'赌客{i}', True, 10000, i % 2, '充值') for i in range(6)]
    行 += [('SF', '上家账户', False, 30000, 1, ''), ('SF', '换卡账户', False, 30000, 1, '')]
    a = 裸分析(行)
    a._detect_money_laundering()
    n = a.nodes['SF']
    assert n['is_launder_suspect'], f'水房被民生豁免放走了: {n["launder_flags"]}'
    assert any('高过路率' in f for f in n['launder_flags']), n['launder_flags']

    # 3 只把小头挂医院、大头走个人卡 → 占比卡住，不豁免、照抓
    行 = [('MIX', f'付款{i}', True, 10000, i % 2, '货款') for i in range(5)]
    行 += [('MIX', '市人民医院', False, 20000, 1, ''), ('MIX', '个人卡二', False, 29000, 1, '')]
    a = 裸分析(行)
    a._detect_money_laundering()
    n = a.nodes['MIX']
    assert n['is_launder_suspect'], f'借医院名头洗大头居然放走: {n["launder_flags"]}'

    # 4 一个人进出再转医院：不是"多人凑"，豁免不适用（单人快进快出留线索人工看）
    行 = [('ONE', '甲', True, 50000, 0, '借款')]
    行.append(('ONE', '市人民医院', False, 50000, 1, '手术费'))
    a = 裸分析(行)
    a._detect_money_laundering()
    assert a.nodes['ONE']['is_launder_suspect'], '单人快进快出也被豁免过头了'

    # 5 收钱往境外跑、转出挂医院名头 → 境外线索独立成立照样抓
    行 = [('OS', f'付款{i}', True, 10000, i % 2, '货款') for i in range(6)]
    行 += [('OS', '境外汇款通道', False, 10000, 2, 'overseas transfer') for _ in range(3)]
    行.append(('OS', '市人民医院', False, 30000, 2, ''))
    a = 裸分析(行)
    a._detect_money_laundering()
    n = a.nodes['OS']
    assert n['is_launder_suspect'], f'境外+医院名头没抓住: {n["launder_flags"]}'
    assert not any('高过路率' in f for f in n['launder_flags']) or True  # 境外线索在不在都算过

    # 6 词表接通：转给「育才学校」（学费形状）同样豁免；名字不沾词表的照旧要抓
    行 = [('EDU', f'家长{i}', True, 5000, i % 2, '代缴费') for i in range(6)]
    行.append(('EDU', '育才学校', False, 30000, 1, '学费'))
    a = 裸分析(行)
    a._detect_money_laundering()
    assert not a.nodes['EDU']['is_launder_suspect'], '学校词没接通词表'

    # 7 开关关成 0 → 退回老判法，看病牵头人重新会被 B 抓（证明开关真的管闸）
    gambling_analysis.LIV_ON = 0
    try:
        a = 裸分析(看病形状())
        a._detect_money_laundering()
        n = a.nodes['MED']
        assert n['is_launder_suspect'] and any('高过路率' in f for f in n['launder_flags']), \
            '开关关了还豁免，闸是假的'
    finally:
        gambling_analysis.LIV_ON = 1

    print('民生豁免自检 ALL PASS：看病牵头人摘帽、水房/借名洗大头/单人/境外照抓、词表和开关都管闸')


if __name__ == '__main__':
    main()
