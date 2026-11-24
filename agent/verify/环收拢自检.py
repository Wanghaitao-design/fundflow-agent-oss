# -*- coding: utf-8 -*-
"""环收拢自检：锁死"循环转账不许掀桌、环上同层、无环结果一个数都不许变"。

2026-11-24 配套修复入库。背景：classify_tiers 原来见有向环就 raise 整批判不了层
（理由是"旧 BFS 在环上可能不终止"，实测过时）；判层真正的隐患是环上深度被图遍历
顺序乱编——100 个账号互转一圈会被编成 1~100 层的假金字塔。现在环上账号统一按
强连通分量收拢取同一深度（gambling_analysis._环收拢拓扑深度）。
跑法：.venv\\Scripts\\python.exe agent\\verify\\环收拢自检.py
"""
import random
import sys
from pathlib import Path

OSS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(OSS))
import networkx as nx
from gambling_analysis import GamblingAnalyzer


def 裸(G):
    a = GamblingAnalyzer.__new__(GamblingAnalyzer)
    a.G = G
    a.环组 = []
    a.nodes = {n: {'in_flow': 1000.0, 'out_flow': 1000.0, 'total_flow': 2000.0,
                   'in_degree': G.in_degree(n), 'out_degree': G.out_degree(n)}
               for n in G.nodes()}
    return a


def G_边(边):
    g = nx.DiGraph()
    g.add_edges_from(边)
    return g


def 老BFS(G, nodes):
    """2026-11-24 之前的无环图算法原样抄一份，专门用来证明无环结果分毫未动。"""
    from collections import deque
    topo = {}
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    if not roots:
        roots = sorted(G.nodes(), key=lambda n: nodes.get(n, {}).get('in_flow', 0),
                       reverse=True)[:max(1, len(G.nodes()) // 10)]
    q, iq = deque(), set()
    for r in roots:
        topo[r] = 0
        q.append(r)
        iq.add(r)
    while q:
        cur = q.popleft()
        for s in list(G.successors(cur)):
            nd = topo[cur] + 1
            if s not in topo or topo[s] < nd:
                topo[s] = nd
                if s not in iq:
                    q.append(s)
                    iq.add(s)
    return topo


def main():
    # 1 纯环：三个账号同层
    a = 裸(G_边([('A', 'B'), ('B', 'C'), ('C', 'A')]))
    d = a._compute_topo_depth()
    assert d == {'A': 0, 'B': 0, 'C': 0}, d
    assert a.环组 == [['A', 'B', 'C']], a.环组

    # 2 环+外部：上游 0，环整体 1，环下游 2
    a = 裸(G_边([('A', 'B'), ('B', 'C'), ('C', 'A'), ('D', 'A'), ('C', 'E')]))
    d = a._compute_topo_depth()
    assert d == {'D': 0, 'A': 1, 'B': 1, 'C': 1, 'E': 2}, d

    # 3 自环边界：不崩、不算环组（同一人给自己转账是数据噪音不是洗钱环）
    a = 裸(G_边([('A', 'A'), ('B', 'A')]))
    d = a._compute_topo_depth()
    assert d.get('A') == 1 and d.get('B') == 0 and a.环组 == [], (d, a.环组)

    # 4 确定性：40 节点大环打乱加边顺序，深度与环组一模一样
    边4 = [(f'N{i:02d}', f'N{(i + 1) % 40:02d}') for i in range(40)] + [('N00', 'TAIL')]
    结果 = []
    for seed in (1, 7, 999):
        g = nx.DiGraph()
        e = 边4[:]
        random.Random(seed).shuffle(e)
        g.add_edges_from(e)
        a = 裸(g)
        结果.append((a._compute_topo_depth(), tuple(sorted(map(tuple, a.环组)))))
    assert 结果[0] == 结果[1] == 结果[2], '同一张图换个加边顺序结果就变，确定性破了'
    assert len(set(结果[0][0].values())) == 2 and 结果[0][0]['TAIL'] == 1

    # 5 两环串联：环内同层、环之间分先后
    a = 裸(G_边([('A', 'B'), ('B', 'A'), ('B', 'C'), ('C', 'D'), ('D', 'C')]))
    d = a._compute_topo_depth()
    assert d == {'A': 0, 'B': 0, 'C': 1, 'D': 1}, d
    assert sorted(map(tuple, a.环组)) == [('A', 'B'), ('C', 'D')], a.环组

    # 6 金标保护：随机 DAG 100 组，新入口和老 BFS 逐点一致——无环账单结果分毫未动
    rnd = random.Random(42)
    for trial in range(100):
        n = rnd.randint(2, 25)
        lab = [f'v{i}' for i in range(n)]
        边 = [(lab[i], lab[j]) for i in range(n) for j in range(i + 1, n) if rnd.random() < 0.25]
        if not 边:
            continue
        g = G_边(边)
        a = 裸(g)
        assert a._compute_topo_depth() == 老BFS(g, a.nodes), f'第{trial}组无环结果变了'

    # 7 掀桌已拆：classify_tiers 不再见环就 raise
    src = (OSS / 'agent' / 'mcp_server' / 'tools' / 'classify_tiers.py').read_text(encoding='utf-8')
    assert '存在有向环' not in src and 'is_directed_acyclic_graph' not in src

    # 8 民警线接口：判层步骤的『异常』会被并进要紧提醒（officer_pack 跑分析里的合并）
    合并处 = (OSS / 'agent' / 'officer_pack.py').read_text(encoding='utf-8')
    assert '判层这一步提示：' in 合并处

    print('环收拢自检 ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
