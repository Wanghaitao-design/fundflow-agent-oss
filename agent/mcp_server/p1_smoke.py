"""P1行为验收：旧算法等价、正向五维、重算失效、大表与报告门禁。"""
import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import networkx as nx
import numpy as np
import pandas as pd
from common import CACHE, DELIVERABLES, ga, folder
from fixtures import generate
from tools import (scan_dataset, build_fund_graph, classify_tiers, rank_suspects, export_evidence,
                   detect_laundering, trace_funds, profile_account, scan_structure)
from smoke import check
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verify'))
from report_check import check as report_check

def main():
    output = []
    output.append(check判据表缺失())
    output.append(check聚类手写实现())
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        did = check(scan_dataset(str(generate())))['结论']['dataset_id']
        check(build_fund_graph(did)); check(classify_tiers(did))
        ctx = CACHE[did]
        check(rank_suspects(did))
        old = copy.deepcopy(ctx['analyzer'])
        with contextlib.redirect_stdout(sys.stderr):
            old._detect_money_laundering()
        detect = check(detect_laundering(did))
        assert 'rank_result' not in ctx
        assert [(v['launder_score'], v['launder_flags'], v['is_launder_suspect']) for v in old.nodes.values()] == [
            (v['launder_score'], v['launder_flags'], v['is_launder_suspect']) for v in ctx['analyzer'].nodes.values()]
        output.append('PASS 洗钱检测写回与旧算法等价，检测后排名失效')
        structure = check(scan_structure(did))
        assert len(structure['结论']['检测器状态']) == 7
        # 这里原来写的是「_detect_time_patterns 必须以 UnboundLocalError 崩掉」——把老 numpy bug 当成了契约，
        # bug 修好反而算自检失败。现在只提两句：① 七个检测器必须都跑完不许崩；
        # ② 该命中的必须命中、这份样例里不该命中的必须报 0 命中。真命中的正例在下面另造一份流水验。
        states = structure['结论']['检测器状态']
        assert all(v['状态'] == '完成' for v in states.values()), states
        hits = structure['结论']['各检测器命中数']
        assert all(isinstance(v, int) for v in hits.values()), hits
        assert hits['_detect_time_patterns'] == 0, hits       # 样例交易只跨两天，没有每周周期，必须报 0
        assert hits['_detect_one_way_accounts'] > 0, hits     # 样例里确实有单向账户，不许悄悄漏成 0
        assert any('未提供数值置信度' in str(row['置信标注']) for row in structure['结论']['命中'])
        # 正例：同一账号每 7 天进一笔差不多的钱，必须被抓成每周额度注入
        probe = copy.deepcopy(ctx['analyzer'])
        probe.nodes = {}                                      # 正例只验检测器本身，不污染真节点
        probe._tx_original = pd.DataFrame([
            {'owner_id': 'syn_weekly', 'cp_key': 'syn_upstream', 'amount_clean': 50000.0,
             'datetime_parsed': pd.Timestamp('2026-01-%02d 10:00:00' % (7 * i + 1)),
             'is_income': True, 'remark': '虚构额度注入', 'desc': ''} for i in range(4)])
        with contextlib.redirect_stdout(sys.stderr):
            weekly = probe._detect_time_patterns()
        assert 'syn_weekly' in weekly and weekly['syn_weekly']['has_weekly_pattern'], weekly
        output.append('PASS 七结构检测器全部跑完（不许崩），周注入正例命中、样例无误报，未自造置信度')
        # 额度分配检测器：这份反面用例是 AMLSim 考场（2026-11-11）替我抓出来的——
        # 老代码在函数里再 import numpy as np，分配笔数<=3 时那行 import 根本不执行，
        # 走到 np.mean(intervals) 必崩 UnboundLocalError，整个结构检测这一路全废。
        # 按新规矩只写两句：必须不崩；三个下级、每 7 天一笔这种正例必须命中。
        probe = copy.deepcopy(ctx['analyzer'])
        probe.nodes = {}
        probe._tx_original = pd.DataFrame([
            {'owner_id': 'syn_alloc', 'cp_key': f'syn_down{i}', 'amount_clean': 30000.0 + i,
             'datetime_parsed': pd.Timestamp('2026-02-%02d 09:00:00' % (7 * i + 1)),
             'is_income': False, 'remark': '', 'desc': ''} for i in range(3)])
        with contextlib.redirect_stdout(sys.stderr):
            alloc = probe._detect_credit_allocation()
        assert 'syn_alloc' in alloc and alloc['syn_alloc']['has_periodic_pattern'], alloc
        probe._tx_original = probe._tx_original.iloc[:2]
        with contextlib.redirect_stdout(sys.stderr):
            assert probe._detect_credit_allocation() == {}, '只发给两个下级，不该算额度分配'
        output.append('PASS 额度分配检测器不崩（分配三笔这种少笔数用例）、三下级周分配命中、两下级不误报')
        rank = check(rank_suspects(did))
        assert rank['证据']['洗钱检测状态'] == '已检测'
        profile = check(profile_account(did, 'synthetic_receiver'))
        assert profile['结论']['指标']['in_flow'] == ctx['analyzer'].nodes['synthetic_receiver']['in_flow']
        assert profile['结论']['上游']
        traced = check(trace_funds(did))
        expected = []
        from common import observe
        visual = ga.Visualizer(ctx['analyzer'])
        observe(visual.fund_penetration_trace, lambda event, values: expected.extend(values.get('node_links', [])))
        assert [(r['来源'], r['去向'], r['金额元'], r['展开深度']) for r in traced['结论']['穿透链路']] == expected
        output.append('PASS 画像指标/上下游与图一致，穿透链路与旧BFS逐行一致')
        exported = check(export_evidence(did))
        out = folder(did)
        assert report_check(out)['状态'] == 'PASS'
        # 单次局部篡改后恢复，逐个验证门禁拒绝，不改上游算法。
        report = out / '06_report.html'
        original = report.read_text(encoding='utf-8')
        report.write_text(re.sub(r'(data-pointer="/结论/节点数">)\d+', r'\g<1>9999', original), encoding='utf-8')
        assert report_check(out)['状态'] == 'FAIL'
        report.write_text(original.replace('</body>', '<p>已认定犯罪事实并定罪</p></body>'), encoding='utf-8')
        assert report_check(out)['状态'] == 'FAIL'
        report.write_text(original, encoding='utf-8')
        evidence = out / '06_evidence_index.json'
        raw = evidence.read_text(encoding='utf-8')
        data = json.loads(raw)
        data['工具结果']['05_tiers']['结论']['判定'][0]['依据'].pop('适用规则')
        evidence.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        assert report_check(out)['状态'] == 'FAIL'
        evidence.write_text(raw, encoding='utf-8')
        clean = out / '02_cleaned.csv'
        clean.rename(out / '02_cleaned.backup')
        try:
            assert report_check(out)['状态'] == 'FAIL'
        finally:
            (out / '02_cleaned.backup').rename(clean)
        report.write_text(original.replace('"金额单位": "元"', '"金额单位": "万元"'), encoding='utf-8')
        assert report_check(out)['状态'] == 'FAIL'
        report.write_text(original, encoding='utf-8')
        output.append('PASS 报告正常PASS；篡改数值/禁用结论/缺三元组/缺交付物/单位冲突均FAIL')
        override = {key: 0 for key in ctx['analyzer'].parameters}
        check(classify_tiers(did, override))
        assert all(key not in ctx for key in ('laundering_result', 'structure_result', 'rank_result'))
        assert all(key not in ctx['results'] for key in ('05_laundering', '05_structure', '05_ranking', '06_export'))
        undetected = check(rank_suspects(did))
        assert undetected['证据']['洗钱检测状态'] == '未检测'
        assert all(r['评分构成']['洗钱附加'] == 0 for r in undetected['结论']['排名'])
        output.append('PASS 判层重算失效洗钱/结构/排名/导出；未检测洗钱附加为0并明确状态')
        # 构造明确正向的五维测试：所有记录都是虚构，比较旧方法结果。
        positive = copy.deepcopy(ctx['analyzer'])
        template = copy.deepcopy(next(iter(positive.nodes.values())))
        positive.G = nx.DiGraph()
        positive.G.add_edge('synthetic_up', 'synthetic_mid', weight=120000, count=3)
        positive.G.add_edge('synthetic_mid', 'synthetic_end', weight=120000, count=1)
        positive.nodes = {}
        for n, inf, outf, level in [('synthetic_up', 0, 120000, 1), ('synthetic_mid', 120000, 120000, 3),
                                  ('synthetic_end', 120000, 0, 4)]:
            v = copy.deepcopy(template)
            v.update(name=n, in_flow=inf, out_flow=outf, total_flow=inf+outf,
                     in_degree=positive.G.in_degree(n), out_degree=positive.G.out_degree(n), level=level,
                     net_out_ratio=(outf-inf)/max(inf+outf, 1))
            positive.nodes[n] = v
        keyword = ga.OVERSEAS_KEYWORDS[0]
        positive.tx = pd.DataFrame([{'owner_id':'synthetic_mid','cp_key':'synthetic_up' if i<3 else 'synthetic_end',
            'amount_clean':40000 if i<3 else 120000, 'is_income':i<3, 'remark':keyword, 'desc':'虚构正向样例',
            'datetime_parsed':pd.Timestamp('2026-01-01')+pd.Timedelta(hours=i)} for i in range(4)])
        old = copy.deepcopy(positive)
        with contextlib.redirect_stdout(sys.stderr):
            old._detect_money_laundering()
        CACHE['p1_positive'] = {'id':'p1_positive','analyzer':positive,'tier_result':{},'issues':[],'results':{}}
        detect = check(detect_laundering('p1_positive'))
        mid = next(r for r in detect['结论']['判定'] if r['账号']=='synthetic_mid')
        assert [r['得分'] for r in mid['五维']] == [40.,25.,20.,15.,15.], mid
        assert mid['总分'] == old.nodes['synthetic_mid']['launder_score'] == 100
        assert positive.nodes['synthetic_mid']['is_launder_suspect'] is True
        positive_rank = check(rank_suspects('p1_positive'))
        assert next(r for r in positive_rank['结论']['排名'] if r['账号'] == 'synthetic_mid')['评分构成']['洗钱附加'] == 15
        output.append('PASS 正向五维40/25/20/15/15，原始115封顶100，与旧算法一致')
        # 大图追线返回前50；文件保存全部，顺序与旧图一致。
        large = copy.deepcopy(ctx['analyzer'])
        large.G = nx.DiGraph()
        large.nodes = {}
        for i in range(61):
            n = 'synthetic_large_' + str(i)
            large.nodes[n] = dict(template, name=n)
            large.G.add_node(n)
            if i:
                large.G.add_edge('synthetic_large_0', n, weight=i, count=1)
        CACHE['p1_large'] = {'id':'p1_large','analyzer':large,'issues':[],'results':{}}
        traced = check(trace_funds('p1_large', target_id='synthetic_large_0'))
        assert len(traced['结论']['穿透链路']) == 50
        assert traced['结论']['穿透链路总数'] > 50
        assert len(pd.read_csv(traced['artifacts']['穿透链路表'])) == traced['结论']['穿透链路总数']
        output.append('PASS >50行追线主动摘要，完整CSV保留全部行')
        # 恢复默认链，留下可验收样例，检查器将生成07。
        check(classify_tiers(did)); check(detect_laundering(did)); check(scan_structure(did))
        check(rank_suspects(did)); check(trace_funds(did)); check(export_evidence(did))
        assert report_check(out)['状态'] == 'PASS'
    assert not capture.getvalue(), capture.getvalue()
    output.extend(['PASS P1直接调用stdout无杂质', 'P1 ALL PASS', '样例交付物目录：' + str(out)])
    text = '\n'.join(output) + '\n'
    (DELIVERABLES / 'p1_output.txt').write_text(text, encoding='utf-8')
    print(text, end='')

def check聚类手写实现():
    """层级聚类换成 numpy 手写之后的契约（2026-11-12）。

    换掉 sklearn 的理由在 算法对照/双跑结果-2026-11-12.md。按 AGENTS.md 新规矩，
    这里只提四句"必须"，不拿任何惯性数值当契约：
      ① 同一份数据跑两次标签必须一模一样（可复现是答辩要问的）；
      ② 两堆明显分开的点必须各成一簇（聚不出来说明实现是死的）；
      ③ 整列数一个样这种退化数据必须不崩、不出 NaN（以前 sklearn 那条路会打一句警告
         然后"回退规则判定"，等于悄悄换了算法——现在这条路只有一条，崩了就是错）；
      ④ 特征矩阵里混进 NaN/Inf 必须显式报错，不许聚出一版没人核对的层级。
    最后一条是门：分析机 gambling_analysis.py 里再也不许出现 import sklearn。
    """
    两堆 = np.vstack([np.random.default_rng(1).normal(0.0, 1.0, (40, 3)),
                      np.random.default_rng(2).normal(8.0, 1.0, (40, 3))])
    标1, 惯1 = ga._kmeans_numpy(ga._zscore(两堆), 2)
    标2, 惯2 = ga._kmeans_numpy(ga._zscore(两堆), 2)
    assert (标1 == 标2).all() and 惯1 == 惯2, '同数据两次跑结果不同，种子没写死'
    assert len(set(标1[:40].tolist())) == 1 and len(set(标1[40:].tolist())) == 1, '两堆点没各成一簇'
    assert set(标1[:40].tolist()) != set(标1[40:].tolist()), '两堆被聚成一堆了'
    常量列 = np.ones((20, 3))
    标3, 惯3 = ga._kmeans_numpy(ga._zscore(常量列), 3)
    assert not np.isnan(标3).any() and float(惯3) == 0.0, ('退化列没接住', 标3, 惯3)
    try:
        ga._kmeans_numpy(np.array([[1.0, float('nan')], [2.0, 3.0]]), 2)
    except ValueError:
        pass
    else:
        raise AssertionError('特征矩阵含 NaN 还让聚，必须显式报错')
    源码 = Path(ga.__file__).read_text(encoding='utf-8')
    assert 'import sklearn' not in 源码, '分析机里又出现 sklearn 了（打包那条路会重新变长）'
    return 'PASS 手写聚类可复现、两堆分得开、退化列不崩、NaN显式报错，分析机里已无sklearn'


# ── 判据表（案由包）找不到的验收 ────────────────────────────────────────────
# 为什么有这一条：2026-11-12 main 查明 Windows 那个 exe「双击闪一下就没」的真凶，
# 是 case_pack.py 在 import 的当口读表、表没打进包就当面色掉 FileNotFoundError。
# 两句契约（按 AGENTS.md 新规矩：只提「必须不崩」「必须拦住」，不写具体数值）：
#   ① 表找不到时 `import gambling_analysis` 退出码必须 0，并把原因记在 PACK_ERROR 里；
#   ② 这时候真开分析机必须显式抛 CasePackError，不许拿空词表 + 0 门槛算一份成绩单出来。
# 另加一句：那副顶空值的哑表读完常量就封上，之后再取值守卫必须报错——
# 防的就是"悄悄用了一份默认数字"这种第二个「换简易算法」式口径黑洞。
# 另起子进程跑：import 过的模块在本进程里没法重装，不能污染主链的 ga。
判据表子代码 = (
    'import os, sys\n'
    'os.environ["FUNDFLOW_CASE_PACKS"] = sys.argv[1]\n'
    'import gambling_analysis as ga\n'
    'assert ga.PACK_ERROR, "表读不出来却没记下原因，PACK_ERROR 是空的"\n'
    'try:\n'
    '    ga.GamblingAnalyzer(None, None)\n'
    'except ga.CasePackError:\n'
    '    pass\n'
    'else:\n'
    '    raise SystemExit("表都读不出来还让开分析机，这里必须拦住")\n'
    'try:\n'
    '    ga.PACK.num("代理嫌疑累计流入下限")\n'
    'except ga.CasePackError:\n'
    '    pass\n'
    'else:\n'
    '    raise SystemExit("哑表没封上，还能拿 0 当门槛用")\n'
    'print("判据表缺失已拦住")\n'
)


def check判据表缺失():
    根 = Path(__file__).resolve().parents[2]
    假目录 = str(根 / '__这份判据表根本不存在__')
    环境 = dict(os.environ, FUNDFLOW_CASE_PACKS=假目录,
                MPLCONFIGDIR=os.environ.get('MPLCONFIGDIR', '/tmp/mplcache'))
    跑 = subprocess.run([sys.executable, '-X', 'utf8', '-c', 判据表子代码, 假目录],
                        cwd=str(根), env=环境, capture_output=True, text=True,
                        encoding='utf-8', errors='replace',  # Windows 默认按本地 GBK 解码子进程输出会乱码，显式 UTF-8（2026-11-22 Windows 实测修正）
                        timeout=300)
    assert 跑.returncode == 0, ('表缺失时 import 不该崩 / 该拦的没拦住', 跑.returncode,
                               跑.stdout[-500:], 跑.stderr[-800:])
    assert '判据表缺失已拦住' in 跑.stdout, 跑.stdout
    return 'PASS 判据表找不到时import不崩、开分析机显式报错、空值哑表不许顶替真门槛'


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
