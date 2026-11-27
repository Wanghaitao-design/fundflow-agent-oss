# -*- coding: utf-8 -*-
"""实验-171对账（2026-11-27 清欠账①）：清白卷「老办法点几个代理嫌疑」三口径对照。

背景：口径.md 记 171、langouste 复测 173，两个数对外不能并存。
本脚本在同一份 s500_innocent_full_dev 卷上跑三种口径：
  A 老办法(尺子原版) = 四条代理固定线参数置 0        → 173
  B 跳过复核整步     = _apply_fixed_line_review 变空函数 → 173（A==B，复核代码不是差因）
  C 现状             = 默认参数                        → 2
结论见 docs/口径.md 勘误块：171 作废、173 为准。

跑法（仓库根目录）：.venv\\Scripts\\python.exe -X utf8 -u agent\\verify\\实验-171对账.py
只读不改：不动算法、不动案由包。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from common import CACHE, ga                                       # noqa: E402
from generator import generate, load_scenario                      # noqa: E402
from tools import scan_dataset, build_fund_graph, classify_tiers   # noqa: E402

AGENT = ('一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑')
固定线关掉时 = {'AGENT_MIN_INFLOW': 0.0, 'AGENT_MIN_IN_DEG': 0.0,
                'AGENT_MIN_IN_DAYS': 1.0, 'AGENT_MIN_OUT_DEG': 0.0}


def 完整(result):
    路径 = result['artifacts'].get('完整结果')
    return json.loads(Path(路径).read_text(encoding='utf-8')) if 路径 else result


def 跑(口径):
    产物 = generate(**load_scenario('s500_innocent_full_dev'))
    真值 = json.loads(Path(产物['标准答案路径']).read_text(encoding='utf-8'))
    答案层级 = {a['合成ID']: (a.get('层级标签') or '') for a in 真值['accounts']}
    原值 = {名: getattr(ga, 名) for 名 in 固定线关掉时}
    原复核 = ga.GamblingAnalyzer._apply_fixed_line_review
    try:
        if 口径 == 'A 老办法置0':
            for 名, 值 in 固定线关掉时.items():
                setattr(ga, 名, 值)
        elif 口径 == 'B 跳过复核':
            ga.GamblingAnalyzer._apply_fixed_line_review = lambda self: None
        扫描 = 完整(scan_dataset(产物['数据集目录']))
        编号 = 扫描['结论']['dataset_id']
        build_fund_graph(编号)
        判定 = 完整(classify_tiers(编号, {}))['结论'].get('判定', [])
    finally:
        ga.GamblingAnalyzer._apply_fixed_line_review = 原复核
        for 名, 值 in 原值.items():
            setattr(ga, 名, 值)
        CACHE.pop(编号, None)
    点出 = [r['账号'] for r in 判定 if r['层级'] in AGENT]
    真代 = {a for a, 层 in 答案层级.items() if '代理嫌疑' in 层}
    print(f'{口径:12s} 点出 {len(点出):3d} 人｜其中真代理 {len(set(点出) & 真代)}', flush=True)
    return set(点出)


if __name__ == '__main__':
    a = 跑('A 老办法置0')
    b = 跑('B 跳过复核')
    c = 跑('C 现状')
    print('A-B 差集:', sorted(a - b)[:10], '｜', sorted(b - a)[:10])
    print('A==B:', a == b)
