#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空案卷尺子：同一批卷子，三种判法各量一次「点出几个代理嫌疑 / 里面有几个是真的」。

为什么有这支脚本（2026-11-15 立的活：先把空案卷那套固定线复测数准备好）：
现在判代理靠的是"跟本批人比排名"（收钱排前 5% 就算一级候选），案子越小被冤枉的比例越高
（100 个账号的卷子判出 17 个、真的只有 8 个）。要改成"按固定标准判"，改之前改之后各要一个数，
否则没法证明改好了。三种判法：

  现状      = 案由包里的默认值（排名线 + 四条固定线都开着）
  只看绝对线 = 把排名用的百分位全压到 0（等于完全不看本批排名，只看每个人自己的绝对量）
  老办法    = 把代理方向四条固定线关掉（等于退回纯排名，用来复现"500 个清白账号点 171 个"）

只读不改：不改算法、不改案由包、不写 agent/range/reports/。跑完把表打在屏幕上，
并写一份 case_packs/空案卷尺子-<日期>.md 存档。

跑法：
  env MPLCONFIGDIR=/tmp/mplcache /home/wht/orca/fundflow-agent-oss/.venv/bin/python -X utf8 -u \\
      case_packs/空案卷尺子.py [2026-11-15]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from common import CACHE, ga                                    # noqa: E402
from generator import generate, load_scenario                   # noqa: E402
from tools import scan_dataset, build_fund_graph, classify_tiers  # noqa: E402

AGENT = ('一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑')
固定线常量 = ('AGENT_MIN_INFLOW', 'AGENT_MIN_IN_DEG', 'AGENT_MIN_IN_DAYS', 'AGENT_MIN_OUT_DEG')
固定线关掉时 = {'AGENT_MIN_INFLOW': 0.0, 'AGENT_MIN_IN_DEG': 0.0,
                'AGENT_MIN_IN_DAYS': 1.0, 'AGENT_MIN_OUT_DEG': 0.0}
百分位键 = ('p50_in', 'p70_in', 'p80_in', 'p90_in', 'p95_in', 'p99_in',
            'p70_out_d', 'p80_out_d', 'p90_out_d', 'p80_in_d')   # 与 adapter.THRESHOLD_KEYS 一致
# 只用 dev 卷。留考卷（holdout）按 docs/口径.md 第 7 节"只考不看"，不进这张对照表。
卷子 = ['s30_innocent_full_dev', 's500_innocent_full_dev',
        's30_clean_full_dev', 's100_clean_full_dev', 's500_noise_full_dev']
判法 = ['现状', '只看绝对线', '老办法']


def 完整(result):
    路径 = result['artifacts'].get('完整结果')
    return json.loads(Path(路径).read_text(encoding='utf-8')) if 路径 else result


def 跑一份(卷子名, 判法名):
    产物 = generate(**load_scenario(卷子名))
    真值 = json.loads(Path(产物['标准答案路径']).read_text(encoding='utf-8'))
    答案层级 = {a['合成ID']: (a.get('层级标签') or '') for a in 真值['accounts']}
    原值 = {名: getattr(ga, 名) for 名 in 固定线常量}
    阈值 = {}
    try:
        if 判法名 == '只看绝对线':
            阈值 = {键: 0.0 for 键 in 百分位键}
        elif 判法名 == '老办法':
            for 名, 值 in 固定线关掉时.items():
                setattr(ga, 名, 值)
        扫描 = 完整(scan_dataset(产物['数据集目录']))
        编号 = 扫描['结论']['dataset_id']
        build_fund_graph(编号)
        判定 = 完整(classify_tiers(编号, 阈值))['结论'].get('判定', [])
        基础 = (CACHE.get(编号) or {}).get('base_nodes') or {}
    finally:
        for 名, 值 in 原值.items():
            setattr(ga, 名, 值)
        CACHE.pop(编号, None)
    点出 = [r['账号'] for r in 判定 if r['层级'] in AGENT]
    真的 = [a for a in 点出 if '代理嫌疑' in 答案层级.get(a, '')]
    全部真代理 = [a for a, 层 in 答案层级.items() if '代理嫌疑' in 层]
    抓到 = [a for a in 全部真代理 if a in set(点出)]
    return {'账号数': len(答案层级), '点出': len(点出), '真的': len(真的),
            '真代理总数': len(全部真代理), '抓到真代理': len(抓到)}


def main():
    日期 = sys.argv[1] if len(sys.argv) > 1 else '未标日期'
    表 = {卷: {判: 跑一份(卷, 判) for 判 in 判法} for 卷 in 卷子}
    行 = ['| 卷子 | 账号数 | 判法 | 点出代理嫌疑 | 其中真是代理 | 真代理总数 | 抓到几个真代理 |',
           '|---|---|---|---|---|---|---|']
    for 卷 in 卷子:
        for 判 in 判法:
            d = 表[卷][判]
            行.append(f"|{卷}|{d['账号数']}|{判}|{d['点出']}|{d['真的']}|{d['真代理总数']}|{d['抓到真代理']}|")
        print(f"=== {卷} ===", flush=True)
        for 判 in 判法:
            d = 表[卷][判]
            print(f"    {判:6s} 点出 {d['点出']:3d} 人｜其中真代理 {d['真的']:3d}｜"
                  f"真代理共 {d['真代理总数']:3d} 人，抓到 {d['抓到真代理']:3d} 个", flush=True)
    文件 = Path(__file__).with_name(f'空案卷尺子-{日期}.md')
    文件.write_text(f'# 空案卷尺子（{日期}）\n\n'
                    '判法说明见 `case_packs/空案卷尺子.py` 开头。'
                    '每个数都必须带上：卷子名、账号数、案由包版本、生成种子（种子在 `agent/range/scenarios/` 的 yaml 里）。\n\n'
                    + '\n'.join(行) + '\n', encoding='utf-8')
    print('已写：', 文件)


if __name__ == '__main__':
    main()
