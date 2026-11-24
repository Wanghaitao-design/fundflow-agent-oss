"""参数化层级研判与证据三元组。"""
import copy
from collections import Counter
import pandas as pd
from common import context, folder, ok, tool, finish
from adapter import LEVELS, validate_thresholds

@tool
def classify_tiers(dataset_id: str, thresholds: dict[str, float] | None = None) -> dict:
    """复用聚类与规则修正。thresholds覆盖真实百分位金额/度数门槛，变更前须提议、说明理由并等待确认。重算重置节点：build→classify→detect_laundering→rank；重算后洗钱、结构须重跑。相同参数命中缓存不重置。"""
    ctx = context(dataset_id)
    if 'analyzer' not in ctx:
        raise ValueError('请先调用 build_fund_graph')
    overrides = thresholds or {}
    validate_thresholds(overrides)
    if ctx.get('tier_params') == overrides and 'tier_result' in ctx:
        return ctx['tier_result']
    # 实际重算前移除依赖缓存；失败时禁止导出旧参数下的结果。
    ctx.pop('tier_result', None)
    ctx.pop('rank_result', None)
    ctx.pop('laundering_result', None)
    ctx.pop('structure_result', None)
    for key in ('05_tiers', '05_ranking', '05_laundering', '05_structure', '05_profile', '05_trace', '06_export'):
        ctx.get('results', {}).pop(key, None)
    a = ctx['analyzer']
    # 2026-11-24：这里原来见有向环就 raise、整批判不了层，理由是"旧 BFS 在环上
    # 可能不终止"——实测已推翻（现实现 100 节点环 0.2ms 终止），且判层用的拓扑深度
    # 已改成环收拢算法（环上账号同层，见 gambling_analysis._环收拢拓扑深度），
    # 所以正常判层，环组进 issues 提醒人工核查，不再掀桌。
    a.nodes = copy.deepcopy(ctx['base_nodes'])
    a.overrides, a.rules, a.cluster_evidence = dict(overrides), {}, {}
    a._classify_levels()
    rows = []
    for node, info in a.nodes.items():
        rules = a.rules.get(node, [])
        if not a.cluster_evidence:
            rules = [{'规则': '样本<10或聚类失败，使用旧百分位规则初始化', '说明': 'p95且出度≥3或入度≥5→一级；p80且出度≥2→二级；p70且出度≥1或入度≥2→三级；出度≤1→赌客；其余外围'}] + rules
        rows.append({'账号': str(node), '层级': LEVELS[info['level']], '依据': {
            '指标值': {k: info[k] for k in ('in_flow', 'out_flow', 'in_degree', 'out_degree', 'total_flow', 'net_out_ratio', 'depth_ratio')},
            '百分位': {'流入': info['in_flow_pct'] * 100, '出度': info['out_deg_pct'] * 100},
            '适用规则': rules}})
    path = folder(dataset_id) / '05_tiers.csv'
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8')
    issues = list(ctx['issues'])
    n = len(a.nodes)
    if 10 <= n < 30:
        issues.append('样本10–29：k=3/4无一级代理初始通道；小样本结果需人工复核。')
    if n < 10:
        issues.append('样本<10：聚类未运行，回退百分位规则；该路径仍可能产生一级候选。')
    if n >= 10 and not a.cluster_evidence:
        issues.append('聚类失败，已显式记录回退规则；原因请查 stderr 日志。')
    环组 = getattr(a, '环组', [])
    if 环组:
        涉及 = sum(len(g) for g in 环组)
        issues.append(f'本批有{len(环组)}组循环互转（涉及{涉及}个账号）：环上账号已按同一层深度对待，'
                      f'层级只是初步参考，建议人工核查环性质（自己人对冲、还是走账闭环）。'
                      f'环组明细：' + '；'.join('↔'.join(map(str, g)) for g in 环组[:5]))
    result = finish(ctx, '05_tiers', ok({'dataset_id': dataset_id, '层级分布': dict(Counter(r['层级'] for r in rows)), '判定': rows},
        {'聚类': a.cluster_evidence or {'k': 0, '方法': '规则回退'}, '参数': a.parameters,
         '参数来源': '调用方覆盖' if overrides else '旧算法自适应百分位默认', '覆盖': overrides,
         '金额常量说明': '旧代码500000/50000/5000常量未被实际判层调用，故覆盖真实百分位门槛，不另造金额规则。',
         '表述口径': '嫌疑与线索仅供核实，不代表司法结论'}, issues, {'层级表': str(path)}))
    ctx['tier_params'] = dict(overrides)
    ctx['tier_result'] = result
    ctx.pop('rank_result', None)
    return result
