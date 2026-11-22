"""观测旧洗钱检测的实际加分，不复制判定算法。"""
import ast
import dis
import inspect
import sys
import textwrap
import pandas as pd
from common import context, folder, ok, tool, finish, ga

DIMENSIONS = ('境外关键词', '高过路率', '快速中转', '整数金额', '单线中转')


def _偏移行号表(code):
    """字节码的位置 → 源码第几行。打包成 exe 之后电脑里没有源码，只剩字节码，行号只能从这儿读。"""
    表 = {}
    try:
        for 起, 止, 行 in code.co_lines():            # Python 3.10 起有这个东西
            for 偏 in range(起, 止, 2):
                表[偏] = 行
    except AttributeError:                            # 3.9 及以前
        当前 = None
        for 指 in dis.get_instructions(code):
            if 指.starts_line is not None:
                当前 = 指.starts_line
            表[指.offset] = 当前
    return 表


def _加分行从字节码(method):
    """数出 l_score += ... 写在哪几行。认法：同一行既读了 l_score 又把结果写回 l_score。
    开头那句 l_score = 0.0 只写不读，不会被当成加分行。"""
    code = getattr(method, "__func__", method).__code__
    表 = _偏移行号表(code)
    读, 写 = set(), set()
    for 指 in dis.get_instructions(code):
        行 = 表.get(指.offset)
        if 行 is None:
            continue
        值 = 指.argval
        名 = set(值) if isinstance(值, (tuple, list)) else {值}
        if 指.opname.startswith('LOAD') and 'l_score' in 名:
            读.add(行)
        if 指.opname == 'STORE_FAST' and 指.argval == 'l_score':
            写.add(行)
    return sorted(写 & 读)


def 找加分行(method):
    """找出旧代码给洗钱分加分的那几行，返回（行号，用的哪种读法）。
    有源码照源码读；打包成 exe 没源码就读字节码。两条路读出来的行号必须一模一样，
    这条在 agent/verify/洗钱加分行自检.py 里当场对过。"""
    try:
        源行, 首行 = inspect.getsourcelines(method)
    except OSError:
        return _加分行从字节码(method), '字节码（这台电脑上没有源码，只有打包好的软件）'
    树 = ast.parse(textwrap.dedent(''.join(源行)))
    行 = sorted(首行 + n.lineno - 1 for n in ast.walk(树) if isinstance(n, ast.AugAssign)
                and isinstance(n.target, ast.Name) and n.target.id == 'l_score')
    return 行, '源码'

@tool
def detect_laundering(dataset_id: str) -> dict:
    """执行旧五维洗钱识别并写回节点，供rank使用。顺序build→classify→detect_laundering→rank；classify重算后须重新检测。"""
    ctx = context(dataset_id)
    if 'tier_result' not in ctx:
        raise ValueError('请先 build_fund_graph → classify_tiers')
    if 'laundering_result' in ctx:
        return ctx['laundering_result']
    a = ctx['analyzer']
    method = a._detect_money_laundering
    additions, 行号读法 = 找加分行(method)
    if len(additions) != 6:
        raise ValueError('旧洗钱加分的结构变了，或者行号没读出来（读法：%s，只读到%d处）——'
                         '洗钱这一项不能出，要人工核对' % (行号读法, len(additions)))
    mapping = dict(zip(additions, (DIMENSIONS[0], DIMENSIONS[0], *DIMENSIONS[1:])))
    scores = {str(n): dict.fromkeys(DIMENSIONS, 0.) for n in a.nodes}
    explanations = {str(n): {} for n in a.nodes}
    previous = sys.gettrace()
    pending = None
    def trace(frame, event, arg):
        nonlocal pending
        if frame.f_code is not method.__func__.__code__:
            return None
        if event in ('line', 'return'):
            local = frame.f_locals
            if pending:
                nid, dimension, before = pending
                scores[nid][dimension] += float(local['l_score']) - before
                explanations[nid][dimension] = local['flags'][-1]
                pending = None
            if event == 'line' and frame.f_lineno in mapping:
                pending = (str(local['nid']), mapping[frame.f_lineno], float(local['l_score']))
        return trace
    # 先失效排名，避免检测失败后导出旧排名。
    ctx.pop('rank_result', None)
    for key in ('05_ranking', '06_export'):
        ctx.get('results', {}).pop(key, None)
    try:
        sys.settrace(trace)
        method()
    finally:
        sys.settrace(previous)
    thresholds = {
        '最低总流水元': ga.MONEY_LAUNDER_MIN_FLOW,
        '境外关键词': '1笔25分；≥3笔40分',
        '高过路率': {'转出流入比下限': ga.MONEY_LAUNDER_TRANSIT_RATIO,
                   '净余额流入比上限': ga.MONEY_LAUNDER_MAX_BALANCE_RATIO},
        '快速中转': {'窗口小时': ga.MONEY_LAUNDER_BURST_INTERVAL, '转出收款比下限': ga.FAST_OUT_RATIO,
                   '收入总额下限元': ga.MONEY_LAUNDER_MIN_FLOW},
        '整数金额': {'整千比例下限': ga.ROUND_RATIO_MIN, '总流水下限元': ga.LEVEL2_MIN_INFLOW},
        '单线中转': {'入度上限': ga.SINGLE_LINE_MAX_RELATIONS, '出度上限': ga.SINGLE_LINE_MAX_RELATIONS,
                   '流入下限元': ga.LEVEL2_MIN_INFLOW,
                   '层级条件': '上游平均层级<下游平均层级且下游平均层级≥4'},
        '嫌疑规则': '境外≥3笔且原始分≥40；或境外≥1笔且原始分≥25且flag≥1；或原始分≥30且flag≥2'}
    rows = []
    for n, info in a.nodes.items():
        nid = str(n)
        raw = sum(scores[nid].values())
        if round(min(raw, 100), 1) != info['launder_score']:
            raise ValueError(f'{nid} 五维回算与旧引擎不一致')
        rows.append({'账号': nid, '总分': info['launder_score'], '封顶前得分': raw,
                     '洗钱嫌疑': info['is_launder_suspect'], '命中说明': info['launder_flags'],
                     '五维': [{'维度': d, '得分': scores[nid][d], '命中': d in explanations[nid],
                              '说明': explanations[nid].get(d, '未命中；不代表不存在风险'),
                              '阈值': thresholds[d]} for d in DIMENSIONS],
                     '纳入分析': info['total_flow'] >= ga.MONEY_LAUNDER_MIN_FLOW})
    path = folder(dataset_id) / '05_laundering.csv'
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8')
    result = finish(ctx, '05_laundering', ok({'dataset_id': dataset_id, '判定': rows,
        '嫌疑节点数': sum(r['洗钱嫌疑'] for r in rows)},
        {'阈值': thresholds, '数据口径': '旧检测使用合并后tx；整数金额和境外命中按owner视角，未另行补推对手数据。',
         '观测方式': '逐条观测旧方法l_score实际增量；结果由旧方法写回节点；加分行号读法：' + 行号读法},
        ctx['issues'], {'洗钱表': str(path)}))
    ctx['laundering_result'] = result
    return result
