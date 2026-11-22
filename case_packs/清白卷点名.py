"""把指定卷子里「被点成代理嫌疑」的账号连事实数一起打出来，并对比「最少一个下级」这条线开/关的差别。

为什么有这支脚本：2026-11-11 那份清白卷（603 个账号一个罪犯都没有）点了 4 个代理嫌疑，
大家对着 main 报告里的描述猜是谁、谁被降级，猜得挺像但没有名单。这支脚本就是把名单和事实数打出来，
不许再拿描述当证据。只读不改：不动算法、不动案由包、不写 main 的成绩单目录。

跑法：
    env MPLCONFIGDIR=/tmp/mplcache /home/wht/orca/fundflow-agent-oss/.venv/bin/python -X utf8 -u \\
        case_packs/清白卷点名.py s500_innocent_full_dev s30_innocent_full_dev
"""
import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORK / 'agent' / 'range'))
sys.path.insert(0, str(WORK / 'agent' / 'mcp_server'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from common import CACHE, ga                                          # noqa: E402
from generator import generate, load_scenario                         # noqa: E402
from tools import scan_dataset, build_fund_graph, classify_tiers       # noqa: E402

AGENT = ('一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑')
OUT_DEG_KEY = 'AGENT_MIN_OUT_DEG'


def _full(result):
    path = result['artifacts'].get('完整结果')
    return json.loads(Path(path).read_text(encoding='utf-8')) if path else result


def run(scenario: str, min_out_deg: int) -> list:
    """跑一份卷子，返回 [(账号, 判成, 几个人给他转钱, 他有几个下级)]，按付款人数从多到少排。"""
    art = generate(**load_scenario(scenario))
    truth = json.loads(Path(art['标准答案路径']).read_text(encoding='utf-8'))
    truth_tier = {a['合成ID']: (a.get('层级标签') or '') for a in truth['accounts']}
    original = getattr(ga, OUT_DEG_KEY)
    ga.AGENT_MIN_OUT_DEG = min_out_deg
    try:
        scan = _full(scan_dataset(art['数据集目录']))
        dataset_id = scan['结论']['dataset_id']
        build_fund_graph(dataset_id)
        tiers = _full(classify_tiers(dataset_id, thresholds={}))['结论'].get('判定', [])
        base = (CACHE.get(dataset_id) or {}).get('base_nodes') or {}
    finally:
        setattr(ga, OUT_DEG_KEY, original)
        CACHE.pop(dataset_id, None)
    rows = []
    for row in tiers:
        if row['层级'] not in AGENT:
            continue
        node = base.get(row['账号']) or {}
        rows.append((row['账号'], row['层级'],
                     int(node.get('in_degree') or 0), int(node.get('out_degree') or 0),
                     '代理嫌疑' in truth_tier.get(row['账号'], '')))
    return sorted(rows, key=lambda r: -r[2])


def main() -> None:
    scenarios = sys.argv[1:] or ['s500_innocent_full_dev', 's30_innocent_full_dev']
    for scenario in scenarios:
        for min_out_deg in (0, 1):
            rows = run(scenario, min_out_deg)
            print(f'=== {scenario}｜要求转出人数≥{min_out_deg}：点出 {len(rows)} 个 ===', flush=True)
            for account, level, in_deg, out_deg, is_agent in rows:
                tag = '答案真是代理' if is_agent else '答案不是代理（冤枉或线索）'
                print(f'    {account} 判成{level}｜{in_deg} 个人给他转过钱｜出度 {out_deg}｜{tag}')
        print(flush=True)


if __name__ == '__main__':
    main()
