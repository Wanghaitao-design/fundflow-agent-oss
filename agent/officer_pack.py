#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民警版输出：把分析结果变成三样能直接拿走的东西。

    1_人员名单.xlsx   谁是赌客、谁是代理、谁管账、谁中转，各多少钱多少笔，怎么核对
    2_资金流向图.png   钱从谁流向谁，A4 横向可打印
    3_情况说明.txt     能直接复制进笔录和报告的成段文字

用法：
    python agent/officer_pack.py <账单文件夹> [身份表.xlsx]
"""
import os
import sys
import io
import tempfile
import contextlib

from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'mplcache'))

# 打包成 exe 之后（冻结模式）没有源码目录，输出要放到 exe 外面的可写位置
冻结模式 = bool(getattr(sys, 'frozen', False))
ROOT = Path(__file__).resolve().parents[1]
程序目录 = Path(sys.executable).resolve().parent if 冻结模式 else ROOT
if not 冻结模式:
    sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))

for 流 in (sys.stdout, sys.stderr):
    try:
        流.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from common import ga, CACHE
from tools import (scan_dataset, build_fund_graph, classify_tiers, detect_laundering,
                   scan_structure, rank_suspects, trace_funds)

# 检测器内部名字 → 民警看得懂的话
标签名 = {
    '_detect_account_sharing': '多人共用同一账户',
    '_detect_accountants': '疑似管账账户',
    # 下面四条 2026-11-12 对着 gambling_analysis.py 逐行核过，改的是"话"不是"算法"：
    # 原来写的是代码没干的事（比如这条从头到尾没看过几点钟），民警照标签理解会理解错
    '_detect_one_way_accounts': '只有单向资金往来（只有来路或只有去处，待查）',
    '_detect_time_patterns': '每隔六到八天来一笔数目差不多的钱',
    '_detect_large_settlement': '五十万以上的大钱结算（不要求整数）',
    '_detect_credit_allocation': '信用额度套现分配',
    '_detect_credit_settlement': '五万以上的大钱隔六到八天进出一次',
}
角色序 = {'一级代理嫌疑': 1, '二级代理嫌疑': 2, '三级代理嫌疑': 3, '赌客线索': 4, '待定外围': 5}

中文字体候选 = [
    # Windows 10 / 11 自带
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/msyhbd.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/simsun.ttc',
    # macOS 自带
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    # Linux
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/wps-office/HYZYB5.ttf',
    '/usr/share/fonts/truetype/arphic/ukai.ttc',
]


def 读入账单(账单目录, 身份表=None):
    """逐份读出账单，并记下每一笔在原文件里是第几行（表头算第1行）。"""
    identity = ga.IdentityMapper()
    if 身份表:
        identity.load(str(身份表))
    每份 = []
    for f in sorted(Path(账单目录).glob('*')):
        if f.suffix.lower() not in ('.xlsx', '.xls', '.csv') or f.name.startswith('~'):
            continue
        try:
            if f.suffix.lower() == '.csv':
                raw = pd.read_csv(f, dtype=str, encoding='utf-8-sig')
            else:
                raw = ga.DataLoader.auto_read(str(f))
            raw.columns = raw.columns.astype(str).str.strip()
            kind = ga.DataLoader.detect_type(raw)
            if kind == 'unknown':
                每份.append({'文件': f, '状态': '失败', '原因': '认不出是哪种账单，没敢猜'})
                continue
            owner = ga.extract_owner_from_filename(f, identity)
            norm = getattr(ga.DataLoader, 'normalize_' + kind)(raw, owner)
            norm = norm.reset_index(drop=True)
            norm['行号'] = norm.index + 2          # 表头占第1行
            norm['文件'] = f.name
            每份.append({'文件': f, '状态': '成功', '类型': kind, '表': norm,
                         '原始行数': len(raw), '读入行数': len(norm)})
        except Exception as exc:
            每份.append({'文件': f, '状态': '失败', '原因': str(exc)[:120]})
    return 每份


步名 = {'受理': '读账单', '建图': '建资金图', '层级': '把账户分层',
        '洗钱': '洗钱线索比对', '结构': '找特征标签', '排名': '排谁先查'}
# 这两步没跑成，别的结果照样出，但要在纸上大声写明"这一栏是空的，空不等于没问题"；
# 其余步骤没跑成，出一份残缺名单比不出更危险，直接停下。
可缺步 = ('洗钱', '结构')


def 步毛病(包):
    """这一步要有毛病就写成一句人话，没毛病返回空字符串。

    注意："异常"这一格里常常装的是提醒（比如"这个账号好几个人在用"），
    那不是没跑成。真没跑成的记号是结论里的 成功=False（分析机出错时才会写这个）。
    """
    if not isinstance(包, dict):
        return '这一步根本没跑'
    if (包.get('结论') or {}).get('成功') is not False:
        return ''
    部 = []
    for 条 in (包.get('异常') or []):
        部.append('%s：%s' % (条.get('类型', ''), 条.get('原因', ''))
                 if isinstance(条, dict) else str(条))
    return '；'.join(部) or '没写出原因'[:200]


def 结论取(结果, 步, 键):
    """拿某一步的结论。拿不到就返回空表——跑不成时 跑分析 已经记过告警了，
    绝不允许在这儿 KeyError 把整个软件弄死（2026-11-12 第 4 次打包就是崩在
    洗钱那一步的 KeyError: '判定' 上）。"""
    包 = 结果.get(步)
    论 = (包.get('结论') or {}) if isinstance(包, dict) else {}
    return 论.get(键) or []


def 跑分析(账单目录, 身份表=None):
    with contextlib.redirect_stdout(io.StringIO()):
        受理 = scan_dataset(str(Path(账单目录).resolve()), str(身份表) if 身份表 else None)
        did = (受理.get('结论') or {}).get('dataset_id')
        建图 = 层级 = 洗钱 = 结构 = 排名 = None
        if did:
            建图 = build_fund_graph(did)
            层级 = classify_tiers(did)
            洗钱 = detect_laundering(did)
            结构 = scan_structure(did)
            排名 = rank_suspects(did)
    if not did:
        raise RuntimeError('读账单这一步没跑成（%s），一份账单都没读进来，不能往下算。'
                           % (步毛病(受理) or '没给出账单编号'))
    结果 = dict(dataset_id=did, 受理=受理, 建图=建图, 层级=层级, 洗钱=洗钱,
                结构=结构, 排名=排名, ctx=CACHE[did], 告警=[])
    # finish() 给外返回时把超过 50 行的名单砍到 50（MCP 返回上限），名单类步骤
    # 必须换回 ctx['results'] 里的完整版——50 人以上的案卷，第 51 个以后的账号
    # 会整行失踪（2026-11-25 AGGB 事件：洗钱嫌疑显示"否"其实是行被砍了）。
    完整 = CACHE[did].get('results', {})
    for 步名_, 存档名 in (('层级', '05_tiers'), ('洗钱', '05_laundering'),
                          ('结构', '05_structure'), ('排名', '05_ranking')):
        if 结果[步名_] is not None and 存档名 in 完整:
            结果[步名_] = 完整[存档名]
    for 键 in ('建图', '层级', '洗钱', '结构', '排名'):
        毛病 = 步毛病(结果[键]) if isinstance(结果[键], dict) else '这一步根本没跑'
        if 毛病:
            if 键 not in 可缺步:
                raise RuntimeError('%s这一步没跑成（%s）。名单是残缺的，不能交出去。'
                                   % (步名[键], 毛病))
            结果['告警'].append(
                '「%s」这一项本轮没跑成（%s）。名单和说明里跟它有关的那几栏是空的——'
                '空只说明这次没查出来，不能当作"这个人没有问题"，这一项得人工再查一遍。'
                % (步名[键], 毛病))
    # 判层步骤自己上报的问题（循环互转环组、小样本需复核等）一并进民警的要紧提醒：
    # 它承认的毛病不许在产物里咽掉（2026-11-24，环收拢改造配套）。
    for 条 in ((结果['层级'] or {}).get('异常') or []) if isinstance(结果['层级'], dict) else []:
        if isinstance(条, str) and 条.strip():
            结果['告警'].append('判层这一步提示：' + 条.strip())
    return 结果



def _规整账号(值):
    """把一列账号统一成分析机那种写法（大小写、空格、连字符都归一）。

    分析机建资金图时账号会变成 a001，账单原文里是 A001；
    两边不套同一个规矩，名单里的起止时间和"原文件第几行"就会全部对不上（真出过这事）。
    """
    return list(ga.GamblingAnalyzer._normalize_account_id(pd.Series([str(v) for v in 值])))


def _时分秒(时刻):
    return 时刻.strftime('%Y%m%d%H%M%S') if pd.notna(时刻) else ''


def 补行号(结果, 每份):
    """给分析机那份流水补上"原文件是第几行"，返回这一份流水。

    只认分析机自己那份（账号已规范化、带原文件名、带 cp_key）。
    """
    流水 = 结果['ctx']['analyzer'].tx.copy()
    排队 = defaultdict(list)
    for 份 in 每份:
        if 份.get('状态') != '成功':
            continue
        表 = 份['表']
        对端 = _规整账号(表['counterpart_id'].fillna('').astype(str).str.strip())
        for 位, r in enumerate(表.itertuples()):
            键 = (Path(str(r.文件)).name.lower(), _时分秒(r.datetime_parsed),
                  round(float(r.amount_clean), 2) if pd.notna(r.amount_clean) else None,
                  对端[位], bool(r.is_income))
            排队[键].append(int(r.行号))
    行号 = []
    for r in 流水.itertuples():
        键 = (Path(str(r.source_file)).name.lower(), _时分秒(r.datetime_parsed),
              round(float(r.amount_clean), 2) if pd.notna(r.amount_clean) else None,
              str(r.counterpart_id), bool(r.is_income))
        候补 = 排队.get(键)
        行号.append(int(候补.pop(0)) if 候补 else '')
    流水['行号'] = 行号
    流水['原文件'] = [Path(str(s)).name for s in 流水['source_file']]
    流水['第几行'] = [('第%d行' % v) if v != '' else '没配上，要翻原表' for v in 流水['行号']]
    return 流水


def 没配上行号的笔数(流水):
    return int(sum(1 for v in 流水['行号'] if v == ''))


def 索引明细(流水):
    """谁付给谁 → 原文件第几行。后面所有"翻回原表"都靠它，账号必须用规范化那一套。"""
    明细 = defaultdict(list)
    for r in 流水.itertuples():
        if pd.isna(r.amount_clean):
            continue
        付, 收 = ((r.owner_id, r.cp_key) if not r.is_income else (r.cp_key, r.owner_id))
        明细[(str(付), str(收))].append({
            '文件': r.原文件, '行号': ('第%d行' % r.行号) if r.行号 != '' else '没配上，要翻原表',
            '时间': r.datetime_parsed, '金额': float(r.amount_clean),
            '对方名字': str(r.counterpart_name_raw), '单号': str(r.trade_no),
            '说明': str(r.desc)[:40], '备注': str(r.remark)[:40],
            '本人': str(r.owner_id)})
    return 明细


def 名字库(流水):
    """账号 → 账单里写着的户名（同一账号取出现最多的那个名）。民警认人靠这个。"""
    库 = defaultdict(Counter)
    for r in 流水.itertuples():
        名 = str(r.counterpart_name_raw or '').strip()
        if 名 in ('', 'nan', 'None') or 名.replace(' ', '').isdigit():
            continue
        账 = str(r.cp_key)
        if not 账:
            continue
        库[账][名] += 1
    return {账: 次.most_common(1)[0][0] for 账, 次 in 库.items()}


def 起名(ident, 库):
    """返回 定名(账号)：先查身份表/文件名，再查账单里的户名，都没有就只能是账号。"""
    库 = 库 or {}

    def 定名(账号):
        账号 = str(账号)
        干净 = 账号.replace('[待核实]', '')
        try:
            名 = str(ident.resolve(账号) or '')
        except Exception:
            名 = ''
        if 名 and 名 != 账号:
            return 名, '身份表/文件名'
        if 账号 in 库:
            return 库[账号], '账单里的户名'
        if 干净 != 账号:
            return 干净, '账单里的名字（身份表里没查到）'
        return 账号, '只有账号没名字'
    return 定名


def 人员表(结果, 定名=None, 流水=None):
    ctx = 结果['ctx']
    an = ctx['analyzer']
    ident = ctx['identity']
    定名 = 定名 or (lambda 账: (str(账), ''))
    tx = 流水 if 流水 is not None else ctx['tx']
    层级map = {r['账号']: r['层级'] for r in 结论取(结果, '层级', '判定')}
    风险 = {r['账号']: r for r in 结论取(结果, '排名', '排名')}
    洗钱行 = 结论取(结果, '洗钱', '判定')
    洗钱可用 = bool(洗钱行)
    洗钱 = {r['账号']: r for r in 洗钱行}
    标签map = defaultdict(list)
    for r in 结论取(结果, '结构', '命中'):
        名 = 标签名.get(r['检测器'], r['检测器'])
        if 名 not in 标签map[r['账号']]:
            标签map[r['账号']].append(名)
    有本人账单 = set(str(x) for x in tx['owner_id'])
    时刻 = defaultdict(list)
    for row in tx.itertuples():
        时刻[str(row.owner_id)].append(row.datetime_parsed)
        时刻[str(row.cp_key)].append(row.datetime_parsed)
    G = an.G
    行 = []
    for 账号, info in an.nodes.items():
        账号 = str(账号)
        上家 = sorted(G.predecessors(账号)) if 账号 in G else []
        下家 = sorted(G.successors(账号)) if 账号 in G else []
        收 = float(info.get('in_flow') or 0)
        支 = float(info.get('out_flow') or 0)
        笔 = int(sum(d.get('count', 1) for _, _, d in G.in_edges(账号, data=True)) +
                 sum(d.get('count', 1) for _, _, d in G.out_edges(账号, data=True))) if 账号 in G else 0
        时 = [t for t in 时刻.get(账号, []) if pd.notna(t)]
        风 = 风险.get(账号, {})
        行.append({
            '姓名': 定名(账号)[0], '账号': 账号,
            '身份核实': ('本人交过账单（名字取自文件名或身份表）' if 账号 in 有本人账单 else
                       ('身份表已核实' if 账号 in getattr(ident, 'mapping', {})
                        else 定名(账号)[1] or '待核实')),
            '角色': 层级map.get(账号, '未定级'),
            '风险评分': 风.get('风险评分', info.get('risk_score', 0)),
            '风险分怎么来的': '、'.join('%s%.1f分' % (k, float(v))
                                 for k, v in (风.get('评分构成', {}) or {}).items() if float(v)) or '无',
            # 洗钱那步没跑成时写"没查成"，绝不写"否"——写"否"等于替人洗白
            '洗钱嫌疑': (('是' if 洗钱.get(账号, {}).get('洗钱嫌疑') else '否')
                        if 洗钱可用 else '没查成'),
            '洗钱线索说明': ('；'.join(洗钱.get(账号, {}).get('命中说明', []) or [])[:200]
                            if 洗钱可用 else '这一项本轮没查成，空白不等于没有洗钱'),
            '特征标签': '；'.join(标签map.get(账号, [])),
            '收(元)': round(收, 2), '支(元)': round(支, 2), '净流入(元)': round(收 - 支, 2),
            '笔数': 笔, '上家数': len(上家), '下家数': len(下家),
            '首次交易': min(时).strftime('%Y-%m-%d %H:%M') if 时 else '(账单里时间读不出)',
            '末次交易': max(时).strftime('%Y-%m-%d %H:%M') if 时 else '(账单里时间读不出)',
            '主要往来对象': '、'.join(sorted({定名(x)[0] for x in 上家 + 下家})[:4]),
            '数据来源': '本人账单' if 账号 in 有本人账单 else '他人账单里反推',
            '怎么翻回原表': '逐笔核对表里有这个账号每一笔的原文件名和第几行',
        })
    行.sort(key=lambda r: (角色序.get(r['角色'], 9), -float(r['风险评分'] or 0)))
    for i, r in enumerate(行, 1):
        r['序号'] = i
    return 行



def 资金对表(结果, 明细, 取前=60, 定名=None):
    定名 = 定名 or (lambda 账: (str(账), ''))
    G = 结果['ctx']['analyzer'].G
    行 = []
    for u, v, d in sorted(G.edges(data=True), key=lambda e: -e[2]['weight']):
        细 = sorted(明细.get((u, v), []), key=lambda x: -x['金额'])
        时 = [x['时间'] for x in 细 if pd.notna(x['时间'])]
        堆 = defaultdict(list)
        for x in 细:
            堆[x['文件']].append(str(x['行号']))
        原始 = '；'.join('%s %s' % (f, '、'.join(v)) for f, v in 堆.items()) or \
               '(这几笔没找到原始行，要翻原表核)'
        行.append({
            '付钱方': 定名(u)[0], '付钱方账号': u,
            '收钱方': 定名(v)[0], '收钱方账号': v,
            '金额(元)': round(d['weight'], 2), '笔数': d.get('count', len(细)),
            '首次': min(时).strftime('%Y-%m-%d %H:%M') if 时 else '(时间读不出)',
            '末次': max(时).strftime('%Y-%m-%d %H:%M') if 时 else '(时间读不出)',
            '最大一笔': round(细[0]['金额'], 2) if 细 else '',
            '在哪个账单': '、'.join(sorted(堆)) if 堆 else '(要翻原表核)',
            '第几行': ('；'.join('%s：%s' % (f, '、'.join(v)) for f, v in 堆.items())
                      if len(堆) > 1 else
                      ('、'.join(next(iter(堆.values()))) if 堆 else '(要翻原表核)')),
            '_原始记录': 原始,
        })
    return 行[:取前]

def 逐笔表(流水, 重点账号, 定名=None, 每人笔数=20):
    """重点人员逐笔列出，标清这一笔是本人账单里的、还是在别人账单里看到的。"""
    定名 = 定名 or (lambda 账: (str(账), ''))
    行 = []
    账列 = 流水['owner_id'].astype(str)
    对列 = 流水['cp_key'].astype(str)
    for 账号 in 重点账号:
        命 = 流水[(账列 == str(账号)) | (对列 == str(账号))]
        命 = 命.sort_values('amount_clean', ascending=False).head(每人笔数)
        for r in 命.itertuples():
            本人 = str(r.owner_id) == str(账号)
            对方账 = str(r.cp_key) if 本人 else str(r.owner_id)
            收 = bool(r.is_income) if 本人 else (not bool(r.is_income))
            对方名 = 定名(对方账)[0]
            if 对方名 in ('', 对方账):
                对方名 = str(r.counterpart_name_raw or '').strip() or 对方账
            行.append({
                '姓名': 定名(账号)[0], '账号': 账号,
                '视角': '本人账单' if 本人 else '别人的账单里看到',
                '时间': r.datetime_parsed.strftime('%Y-%m-%d %H:%M')
                        if pd.notna(r.datetime_parsed) else '(时间读不出)',
                '收/支': '收' if 收 else '支',
                '金额(元)': round(float(r.amount_clean), 2),
                '对方': 对方名, '对方账号': 对方账,
                '商品/说明': str(r.desc)[:40], '备注': str(r.remark)[:40],
                '单号': str(r.trade_no), '原文件': r.原文件,
                '第几行': ('第%d行' % r.行号) if r.行号 != '' else '没配上，要翻原表',
            })
    return 行

def 写Excel(输出文件, 人, 资金对, 逐笔, 每份, 结果, 流水=None):
    表头底 = PatternFill('solid', fgColor='DDEBF7')
    警示底 = PatternFill('solid', fgColor='FFF2CC')
    失败底 = PatternFill('solid', fgColor='F8CBAD')

    def 写表(工作簿, 表名, 行, 列宽, 金额列=(), 高亮=None):
        ws = 工作簿.create_sheet(表名)
        if not 行:
            ws.append(['（无数据）'])
            return ws
        列 = [k for k in 行[0].keys() if not str(k).startswith('_')]
        ws.append(列)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = 表头底
            c.alignment = Alignment(horizontal='center', vertical='center')
        for r in 行:
            ws.append([r.get(k, '') for k in 列])
        for i, 名 in enumerate(列, 1):
            ws.column_dimensions[get_column_letter(i)].width = 列宽.get(名, 14)
        for 名 in 金额列:
            j = 列.index(名) + 1
            for i in range(2, ws.max_row + 1):
                ws.cell(i, j).number_format = '#,##0.00'
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        if 高亮:
            for i in range(2, ws.max_row + 1):
                if 高亮(ws, i, 列):
                    for j in range(1, len(列) + 1):
                        ws.cell(i, j).fill = 警示底
        return ws

    wb = Workbook()
    wb.remove(wb.active)
    宽 = {}
    宽.update({'序号': 5, '姓名': 16, '账号': 22, '身份核实': 10, '角色': 16, '风险评分': 10,
               '收(元)': 13, '支(元)': 13, '净流入(元)': 13, '笔数': 7, '上家数': 8, '下家数': 8,
               '首次交易': 17, '末次交易': 17, '洗钱嫌疑': 10, '洗钱线索说明': 30, '特征标签': 26,
               '主要往来对象': 26, '账单文件': 30, '风险分怎么来的': 42, '付钱方': 16,
               '付钱方账号': 20, '收钱方': 16, '收钱方账号': 20, '金额(元)': 14,
               '首次': 17, '末次': 17, '在哪份账单里': 30, '时间': 17, '收/支': 7, '对方': 18,
               '商品/说明': 24, '备注': 24, '单号': 22, '原文件': 30, '第几行': 8,
               '视角': 18, '最大一笔': 12, '对方账号': 20, '账号': 20, '在哪个账单': 30, '第几行': 14, '数据来源': 16,
               '怎么翻回原表': 28, '洗钱线索说明': 30,
               '状态': 8, '类型': 10, '原始行数': 10, '读入行数': 10, '失败原因': 60, '文件': 34})
    写表(wb, '人员名单', 人, 宽,
         ('收(元)', '支(元)', '净流入(元)'),
         高亮=lambda ws, i, 列: (ws.cell(i, 列.index('角色') + 1).value or '').endswith('代理嫌疑')
         or str(ws.cell(i, 列.index('洗钱嫌疑') + 1).value) == '是')
    写表(wb, '重点资金对', 资金对, 宽, ('金额(元)', '最大一笔'))
    写表(wb, '逐笔核对', 逐笔, 宽, ('金额(元)',))
    源 = []
    for 份 in 每份:
        源.append({'文件': 份['文件'].name, '状态': 份['状态'],
                   '类型': 份.get('类型', ''), '原始行数': 份.get('原始行数', ''),
                   '读入行数': 份.get('读入行数', ''), '失败原因': 份.get('原因', '')})
    ws = 写表(wb, '数据来源与没读到的', 源, 宽)
    for i in range(2, ws.max_row + 1):
        if ws.cell(i, 2).value == '失败':
            for j in range(1, 7):
                ws.cell(i, j).fill = 失败底
    说明 = [
        ['这张表怎么来的，请务必看一遍'],
        ['分析时间', datetime.now().strftime('%Y-%m-%d %H:%M')],
        ['分析用的电脑上的哪个文件夹', 结果['ctx']['path']],
        ['读取成功的文件数', sum(1 for s in 源 if s['状态'] == '成功')],
        ['读不出来的文件数', sum(1 for s in 源 if s['状态'] == '失败')],
        ['账单原文交易笔数', int(len(结果['ctx']['tx']))],
        ['进入资金统计的笔数', int(sum(d.get('count', 1)
                                 for _, _, d in 结果['ctx']['analyzer'].G.edges(data=True)))],
        ['涉及账户数', len(人)],
        ['本人交过账单的账户数', sum(1 for p in 人 if p.get('数据来源') == '本人账单')],
        ['姓名已对上的账户数', sum(1 for p in 人
                          if '已核实' in p['身份核实'] or p['身份核实'].startswith('本人交过账单'))],
        ['没配上原文件行号的笔数',
         (int(sum(1 for v in (流水 if 流水 is not None else 结果['ctx']['tx'])['行号'] if v == ''))
          if 流水 is not None and '行号' in 流水.columns else 0)],
        [''],
        ['1. “角色”是线索提示，不是定性结论。定谁是什么人，要靠你自己查证。'],
        ['2. “待核实”表示这个账号没在身份表里查到姓名，需要调实名信息后再填。'],
        ['3. “风险评分”只是排查顺序，分高不等于有罪。'],
        ['4. 每一行都能在“逐笔核对”里翻到原账单的文件夹和行号，不放心就翻原表。'],
        ['5. 没读出来的文件一律列在“数据来源与没读到的”，不会被当成零。'],
    ]
    警告条数 = 0
    if 结果.get('告警'):
        插 = [['★ 本轮有%d条要紧提醒，一条都不许忽略' % len(结果['告警'])]]
        for i, 条 in enumerate(结果['告警'], 1):
            插.append(['第%d条' % i, 条])
        说明[1:1] = 插
        警告条数 = len(插)

    ws2 = wb.create_sheet('先看这张')
    for row in 说明:
        ws2.append(row)
    ws2['A1'].font = Font(bold=True, size=13)
    ws2.column_dimensions['A'].width = 34
    ws2.column_dimensions['B'].width = 70
    for r in range(2, 警告条数 + 2):    # 紧挨着标题，红字加粗，翻到这张就撞见
        for c in (1, 2):
            ws2.cell(r, c).font = Font(bold=True, color='FFCF222E', size=11)
        ws2.cell(r, 2).alignment = Alignment(wrap_text=True, vertical='top')
        ws2.row_dimensions[r].height = 62
    wb.save(输出文件)


_字体提醒过 = False


def 取字体():
    global _字体提醒过
    from matplotlib.font_manager import FontProperties
    文件 = next((f for f in 中文字体候选 if Path(f).exists()), None)
    if 文件 is None and not _字体提醒过:
        _字体提醒过 = True
        print('警告：这台电脑上没找到中文字体，图里的中文可能显示成方框。', file=sys.stderr)
    return (FontProperties(fname=文件) if 文件 else FontProperties())


def 宽度(文, 字号):
    """估算一段字有多宽（单位：点），中文按整宽，字母数字按半宽。"""
    中 = 0
    for ch in 文:
        中 += 1 if ord(ch) > 0x2E80 else 0.55
    return 中 * 字号 * 1.02


def 短名(名, 账号, 已有, 预算=0, 字号=9.0):
    """图上名字要短又要能认人：中文名截 6 个，账号类名字取后 6 位，重名加编号。"""
    名 = str(名 or 账号)
    有中文 = any('\u4e00' <= ch <= '\u9fff' for ch in 名)
    if 有中文:
        短 = 名[:6]
    elif len(名) <= 12:
        短 = 名
    else:
        尾 = 名.split('_', 1)[1] if '_' in 名 else 名[-10:]
        短 = 尾 if len(尾) <= 12 else ('…' + 名[-10:])
    if 预算 and 宽度(短, 字号) > 预算 and len(短) > 2:
        可用 = max(2, int(预算 / (字号 * 1.05)))
        while len(短) > 可用 and len(短) > 2:
            短 = 短[:-1]
        if 宽度(短, 字号) > 预算:
            短 = 短 + '..'
    if not 短:
        短 = 账号[:6]
    第 = 已有.count(短)
    if 第:
        短 = 短 + '·%d' % (第 + 1)
    已有.append(短)
    return 短


def 画流向图(输出文件, 人, 结果, 取边=40, 取点=34, 定名=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import networkx as nx
    字 = 取字体()
    粗 = 取字体()
    图 = 结果['ctx']['analyzer'].G.copy()
    图.remove_edges_from(list(nx.selfloop_edges(图)))
    角色of = {p['账号']: p['角色'] for p in 人}
    流量of = {p['账号']: (p['收(元)'] + p['支(元)']) for p in 人}
    嫌疑 = {p['账号'] for p in 人 if p['洗钱嫌疑'] == '是'}
    钱最大 = max([d['weight'] for _, _, d in 图.edges(data=True)] or [1])
    边 = sorted(图.edges(data=True), key=lambda e: -e[2]['weight'])[:取边]
    G = nx.DiGraph()
    for u, v, d in 边:
        G.add_edge(u, v, weight=d['weight'], count=d.get('count', 1))
    截了 = 0
    if G.number_of_nodes() > 取点:
        留 = sorted(G.nodes, key=lambda n: -流量of.get(n, 0))[:取点]
        截了 = G.number_of_nodes() - len(留)
        边 = [(u, v, d) for u, v, d in 图.edges(data=True) if u in 留 and v in 留]
        边 = sorted(边, key=lambda e: -e[2]['weight'])[:取边]
        G = nx.DiGraph()
        for u, v, d in 边:
            G.add_edge(u, v, weight=d['weight'], count=d.get('count', 1))
    if G.number_of_nodes() == 0:
        return False
    # 分层摆放：上面几层是代理嫌疑，下面是赌客/外围，行内按钱的多少从左到右
    层序 = ['一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑', '赌客线索', '待定外围', '未定级']
    分组 = defaultdict(list)
    for n in G.nodes:
        分组[角色of.get(n, '未定级')].append(n)
    有层的 = [层 for 层 in 层序 if 分组.get(层)]
    # 摆法：一个角色一行，行内让"付钱的在左边、收钱的在右边"，箭头一律往右走，好读。
    # 只有一行时铺在画布正中——以前三个点全趴在最底下那条边上，上面空一大片（真出过）。
    上, 下 = 0.34, -0.34
    行距 = (上 - 下) / (len(有层的) - 1) if len(有层的) > 1 else 0.0
    行高, 位置 = {}, {}
    净额of = {n: float(sum(d.get('weight', 0) for _, _, d in G.out_edges(n, data=True)) -
                       sum(d.get('weight', 0) for _, _, d in G.in_edges(n, data=True)))
              for n in G.nodes}
    for 序, 层 in enumerate(有层的):
        点 = sorted(分组[层], key=lambda n: (-净额of[n], -流量of.get(n, 0)))
        y = (上 - 序 * 行距) if 行距 else (上 + 下) / 2.0
        行高[层] = y
        for i, n in enumerate(点):
            位置[n] = ((i + 0.5) / len(点) - 0.5) * 0.94, y
    人多的一行 = max([len(v) for v in 分组.values()] or [1])
    字号 = 10.5 if 人多的一行 <= 6 else (9.5 if 人多的一行 <= 10 else
            (8.5 if 人多的一行 <= 16 else 7.2))
    # 点不能大过它左右/上下邻居之间的空档，否则糊成一团
    同行最密 = 人多的一行
    空档pt = min(0.94 / 同行最密 * 690.0, (行距 * 0.8) * 415.0) if 行距 else 0.94 / 同行最密 * 690.0
    最大直径pt = max(16.0, 空档pt * 0.78)
    斜写 = 人多的一行 >= 9
    名字预算 = 空档pt * (2.1 if 斜写 else 1.0)
    定名 = 定名 or (lambda 账: (str(账), ''))
    最大流量 = max(list(流量of.values()) + [1])
    # 人本来就少的时候别把圆点画成豆粒，A4 上会空一大片
    点放大 = 2.6 if G.number_of_nodes() <= 6 else (1.6 if G.number_of_nodes() <= 12 else 1.0)
    颜色 = {'一级代理嫌疑': '#c0392b', '二级代理嫌疑': '#e74c3c', '三级代理嫌疑': '#f1c40f',
            '赌客线索': '#8b9aa0', '待定外围': '#c8ccd0', '未定级': '#c8ccd0'}
    fig = plt.figure(figsize=(11.69, 8.27), dpi=200)
    fig.subplots_adjust(left=0.035, right=0.985, top=0.845, bottom=0.135)
    ax = fig.add_subplot(111)
    标了 = []
    for n in G.nodes:
        x, y = 位置[n]
        大 = min((240 + 3600 * min(流量of.get(n, 0) / 最大流量, 1)) * 点放大,
                   最大直径pt ** 2)
        nx.draw_networkx_nodes(G, 位置, nodelist=[n], node_size=[大],
                               node_color=[颜色.get(角色of.get(n, '未定级'), '#c8ccd0')],
                               edgecolors=['#8e0000' if n in 嫌疑 else 'black'],
                               linewidths=[3.0 if n in 嫌疑 else 1.0], alpha=0.95, ax=ax)
        名 = 短名(定名(n)[0], n, 标了, 名字预算, 字号)
        if 斜写:
            偏 = 0.010 + 大 ** 0.5 / 90000.0
            ax.text(x - 大 ** 0.5 / 9000.0 * 0.5, y + 偏, 名, fontproperties=字,
                    fontsize=字号, ha='right', va='bottom', rotation=32, rotation_mode='anchor')
        else:
            偏 = 0.012 + 大 ** 0.5 / 74000.0 * 0.9
            ax.text(x, y + 偏, 名, fontproperties=字, fontsize=字号, ha='center', va='bottom')
    度 = dict(G.degree())
    全部边 = sorted(G.edges(data=True), key=lambda e: -e[2]['weight'])
    大边 = [e for e in 全部边[:10] if e[2]['weight'] >= 0.12 * 钱最大]
    for u, v, d in G.edges(data=True):
        (x1, y1), (x2, y2) = 位置[u], 位置[v]
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle='-|>', color='#666666',
                                    alpha=0.75, lw=max(0.8, 5.0 * d['weight'] / 钱最大),
                                    shrinkA=13, shrinkB=15))
        if (u, v, d) in 大边:
            文 = ('%.1f万' % (d['weight'] / 10000)) if d['weight'] >= 10000 else ('%.0f元' % d['weight'])
            比 = 0.5          # 标在箭头中段，别压到两边的圆点和人名上
            ax.text(x1 + (x2 - x1) * 比, y1 + (y2 - y1) * 比 + 0.014, 文, fontproperties=字,
                    fontsize=8.0, ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='#aaaaaa', alpha=0.95))
    for 层, y in 行高.items():
        ax.text(-0.705, y, 层, fontproperties=字, fontsize=10,
                color='#666666', ha='left', va='center',
                bbox=dict(boxstyle='round,pad=0.2', fc='#f4f6f7', ec='#d5d8dc'))
    from matplotlib.lines import Line2D
    图例 = [Line2D([0], [0], marker='o', color='w', markerfacecolor=c, markeredgecolor='black',
                    markersize=11, label=t)
            for t, c in [('一级代理嫌疑', 颜色['一级代理嫌疑']), ('二级代理嫌疑', 颜色['二级代理嫌疑']),
                         ('三级代理嫌疑', 颜色['三级代理嫌疑']), ('赌客线索', 颜色['赌客线索']),
                         ('待定外围', 颜色['待定外围'])]]
    图例.append(Line2D([0], [0], marker='o', color='w', markerfacecolor='#ddd',
                        markeredgecolor='#8e0000', markeredgewidth=3, markersize=11,
                        label='红圈=命中洗钱线索'))
    ax.legend(handles=图例, loc='upper center', bbox_to_anchor=(0.5, -0.015), ncol=4,
              prop=字, framealpha=0.95, borderpad=0.7, handlelength=0.6, columnspacing=1.6)
    案件 = Path(结果['ctx']['path']).name
    fig.text(0.5, 0.965, '资金流向图　%s' % 案件, fontproperties=粗, fontsize=18, ha='center')
    fig.text(0.5, 0.908,
             '箭头＝钱走的方向　　线越粗钱越多　　圆点越大进出账越多　　共 %d 个账户、%d 条资金往来%s'
             % (G.number_of_nodes(), G.number_of_edges(),
                ('（另有 %d 个资金量小的账户没画，见名单表）' % 截了) if 截了 else ''),
             fontproperties=字, fontsize=11.5, ha='center', color='#333333')
    fig.text(0.012, 0.014, '本图仅为资金流水线索提示，不构成对任何人的定性结论。　生成时间：'
                + datetime.now().strftime('%Y-%m-%d %H:%M'), fontproperties=字, fontsize=8,
                color='#555555')
    if 结果.get('告警'):
        fig.text(0.012, 0.045,
                 '★ 本轮有%d条要紧提醒（详见《3_情况说明.txt》开头）：图里跟洗钱有关的那一项可能没查成，'
                 '没画红圈不等于没有洗钱。' % len(结果['告警']),
                 fontproperties=字, fontsize=9.5, color='#cf222e')
    ax.set_xlim(-0.72, 0.50)
    ax.set_ylim(-0.48, 0.48)
    ax.axis('off')
    plt.savefig(输出文件, dpi=200, bbox_inches='tight')
    plt.close()
    return True



def _时段(起, 止):
    """把起止时间拼成一句话；读不出来就明说，绝不允许印出"至。"这种空档。"""
    起, 止 = str(起 or '').strip(), str(止 or '').strip()
    if 起 and 止:
        return '，时间 %s 至 %s' % (起, 止)
    if 起:
        return '，首笔 %s（末笔时间账单里没读出来）' % 起
    return '，起止时间账单里没读出来（要翻原表核对）'


def 写说明(输出文件, 人, 资金对, 每份, 结果, 流水=None):
    成 = [s for s in 每份 if s.get('状态') == '成功']
    败 = [s for s in 每份 if s.get('状态') == '失败']
    tx = 结果['ctx']['tx']
    流水 = 流水 if 流水 is not None else tx
    图 = 结果['ctx']['analyzer'].G
    有效笔数 = int(sum(d.get('count', 1) for _, _, d in 图.edges(data=True)))
    读到笔数 = int(len(tx))
    差额 = 读到笔数 - 有效笔数
    时刻 = 流水['datetime_parsed'].dropna()
    重点 = [p for p in 人 if p['角色'].endswith('代理嫌疑') or p['洗钱嫌疑'] == '是'][:10]
    本人账单数 = sum(1 for p in 人 if p.get('数据来源') == '本人账单')
    已核实 = sum(1 for p in 人
                 if '已核实' in p['身份核实'] or p['身份核实'].startswith('本人交过账单'))
    待核实 = len(人) - 已核实
    角色统计 = Counter(p['角色'] for p in 人)
    配不上 = 没配上行号的笔数(流水) if '行号' in 流水.columns else 0
    L = []
    L.append('关于%s等账户资金流水的分析说明\n' % Path(结果['ctx']['path']).name)
    if 结果.get('告警'):
        L.append('【本轮有%d条要紧提醒，先看这几条，别直接往报告里抄】' % len(结果['告警']))
        for i, 条 in enumerate(结果['告警'], 1):
            L.append('%d. %s' % (i, 条))
        L.append('')
    L.append('一、数据来源')
    L.append('本次读取账单文件%d个，%d个读出来了、%d个读不出来。账单原文共%d笔交易，'
             '进入资金统计的%d笔%s。'
             % (len(每份), len(成), len(败), 读到笔数, 有效笔数,
                ('（另有%d笔没进入：可能是同一笔钱在双方账单里各记了一次，'
                 '也可能是零钱通、余额宝这类平台内转账和同人不同账号互转，程序按规矩排除了）'
                 % 差额) if 差额 > 0 else ''))
    for s in 败:
        L.append('读不出来的文件：%s，原因：%s（这个文件的内容一点都没进统计，没有当成零处理）'
                 % (s['文件'].name, s.get('原因', '')))
    L.append('涉及账户%d个：本人交过账单的%d个，只在别人账单里露面的%d个；'
             '姓名能直接对上人的%d个，其余%d个要调取实名信息后才能确认是谁。'
             % (len(人), 本人账单数, len(人) - 本人账单数, 已核实, 待核实))
    if len(时刻):
        L.append('分析期间：%s 至 %s；资金进出合计%.2f元（去重后，收和支各算一遍的总数）。'
                 % (时刻.min().strftime('%Y年%m月%d日'), 时刻.max().strftime('%Y年%m月%d日'),
                    float(sum(d.get('weight', 0) for _, _, d in 图.edges(data=True)))))
    if 配不上:
        L.append('注意：有%d笔在名单表里没配上原文件的行号，那几笔要人工翻原账单核对。' % 配不上)
    if 有效笔数 < 30 or len(成) < 3:
        L.append('【样本太小】本次进入统计的只有%d笔、%d份账单。这点数量看不出稳定的资金规律，'
                 '所以"没发现代理或洗钱特征"不能当作排除依据，只能当作还没查完。'
                 % (有效笔数, len(成)))
    L.append('')
    L.append('二、重点人员及依据')
    if not 重点:
        构成 = '、'.join('%s%d人' % (角, 数) for 角, 数 in 角色统计.items())
        L.append('按现有判据逐条比过，本次没有发现代理嫌疑或洗钱线索的账户。'
                 '本次判定构成：%s。' % (构成 or '无'))
    for i, p in enumerate(重点, 1):
        构成 = p.get('风险分怎么来的', '')
        L.append('%d. %s（账号%s，姓名来源：%s）：%s。收%.2f元、支%.2f元，共%d笔，'
                 '上游%d个、下游%d个%s。风险评分%.1f（满分100），主要构成：%s。%s%s'
                 % (i, p['姓名'], p['账号'], p['身份核实'], p['角色'], p['收(元)'], p['支(元)'],
                    p['笔数'], p['上家数'], p['下家数'], _时段(p['首次交易'], p['末次交易']),
                    p['风险评分'], 构成 or '无',
                    ('特征：' + p['特征标签'] + '。') if p['特征标签'] else '',
                    ('洗钱线索：' + p['洗钱线索说明'] + '。') if p['洗钱线索说明'] else ''))
        L.append('   核对方式：见《1_人员名单.xlsx》“逐笔核对”中该账号各行，'
                 '那一行写着原账单文件名和第几行（这个账号的数据来源：%s）。'
                 % p.get('数据来源', ''))
    赌客 = [q for q in 人 if q['角色'] == '赌客线索']
    赌客排序 = sorted(赌客, key=lambda q: -(q['收(元)'] + q['支(元)']))
    if 赌客:
        L.append('')
        L.append('三、参赌人员概况')
        L.append('本次判为“赌客线索”的共%d人，合计进出资金%.2f元。金额最大的前%d人如下'
                 '（完整名单见《1_人员名单.xlsx》“人员名单”表，角色筛“赌客线索”即可）：'
                 % (len(赌客), sum(q['收(元)'] + q['支(元)'] for q in 赌客), min(10, len(赌客))))
        for i, q in enumerate(赌客排序[:10], 1):
            L.append('%d. %s（账号%s，姓名来源：%s）：收%.2f元、支%.2f元，共%d笔%s。'
                     % (i, q['姓名'], q['账号'], q['身份核实'], q['收(元)'], q['支(元)'],
                        q['笔数'], _时段(q['首次交易'], q['末次交易'])))
    L.append('')
    L.append('四、重点资金往来')
    if not 资金对:
        L.append('本次没有能连成一条的资金往来。')
    for p in 资金对[:10]:
        L.append('%s（%s）→ %s（%s）：%s元，%d笔%s。原始记录：%s。'
                 % (p['付钱方'], p['付钱方账号'], p['收钱方'], p['收钱方账号'],
                    format(p['金额(元)'], ',.2f'), p['笔数'],
                    _时段(p['首次'], p['末次']), p['_原始记录']))
    L.append('')
    L.append('五、需要人工核实的事项')
    L.append('1. 姓名一栏只有账号或者写着“账单里的名字”的，都是没在身份表里查到实名，'
             '要调取实名信息后才能落到人。')
    L.append('2. 风险评分只用来安排先查谁、后查谁，分数高低不代表有违法，更不构成定性结论。')
    L.append('3. 上面写的是资金流水线索，最终认定以侦查、检察机关查明的事实为准。')
    L.append('4. 每一条结论在《1_人员名单.xlsx》里都能翻到原账单的文件名、第几行和金额，'
             '不放心就照着翻原表。')
    L.append('5. 风险评分各因素的轻重（资金量、网络位置、关键词、夜间时段、爆发性等）沿用的是上一版'
             '算法自定的权重，没有法律法规依据，也没有做过实证校验，只用来安排先查谁、后查谁，'
             '不作为对任何人的判定。')
    L.append('6. 筛人用的门槛数写在软件旁边的判据表里（case_packs\\wangdu\\03_门槛.csv，'
             '每一行都写着这条是谁定的、依不依据法条），用 Excel 就能改。'
             '两高一部《关于办理网络赌博犯罪案件适用法律若干问题的意见》里的30万元、3万元、120人'
             '那几条是"情节严重"的量刑线，不是筛人的线，本软件没有拿它当筛人标准，'
             '文书里也不要写成"达到30万即构成犯罪"。')
    Path(输出文件).write_text('\n'.join(L), encoding='utf-8')

def main(账单目录, 身份表=None, 输出目录=None):
    账单目录 = Path(账单目录).resolve()
    名 = 账单目录.name
    if 输出目录:
        输出 = Path(输出目录)
    elif 冻结模式:
        # 双击版：结果就放在账单文件夹旁边，不用解释什么是"输出目录"
        输出 = 账单目录.parent / '分析结果' / (名 + '_' + datetime.now().strftime('%Y%m%d_%H%M'))
    else:
        输出 = ROOT / '输出结果' / (名 + '_' + datetime.now().strftime('%Y%m%d_%H%M'))
    输出.mkdir(parents=True, exist_ok=True)
    print('读账单...')
    每份 = 读入账单(账单目录, 身份表)
    print('跑分析...')
    结果 = 跑分析(账单目录, 身份表)
    for 条 in (结果.get('告警') or []):
        print('!! 要紧提醒：' + 条)
    流水 = 补行号(结果, 每份)          # 账号用分析机那一套，顺便把原文件第几行配上
    明细 = 索引明细(流水)
    定名 = 起名(结果['ctx']['identity'], 名字库(流水))
    人 = 人员表(结果, 定名, 流水)
    资金对 = 资金对表(结果, 明细, 定名=定名)
    重点 = [p['账号'] for p in 人 if p['角色'].endswith('代理嫌疑') or p['洗钱嫌疑'] == '是']
    重点 += [p['账号'] for p in 人 if p['账号'] not in 重点][:15]
    逐笔 = 逐笔表(流水, 重点[:20], 定名)
    写Excel(输出 / '1_人员名单.xlsx', 人, 资金对, 逐笔, 每份, 结果, 流水)
    画流向图(输出 / '2_资金流向图.png', 人, 结果, 定名=定名)
    写说明(输出 / '3_情况说明.txt', 人, 资金对, 每份, 结果, 流水)
    print('输出目录：', 输出)
    for f in sorted(输出.iterdir()):
        print('  ', f.name, f.stat().st_size, '字节')
    return 输出


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
