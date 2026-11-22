#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 IBM AMLSim 官方样本切成能进分析机的小卷子。

为什么要有这个：手上没有真实脱敏账单（2026-11-11 确认），拿 IBM 开源 AMLSim 的官方输出
样本当替身考场的原料。它的好处是**标准答案是 IBM 配置文件写死的**（nodes.csv 里的
isFraud / fraudStep），不是我自编的。

产出：amlsim/产物/<样本>_n<账号数>_s<种子>/
  dataset/syn_bill_<账号>_微信.xlsx   每账户一份账单，列名和 main 的出题机完全一致
  truth.json                          标准答案（只有这里能出现 isFraud）
  结构提示.json                        我从资金方向推出来的分组，**不是标准答案**

硬规矩：isFraud、fraudStep 一个字都不许进账单（备注统一写「AMLSim合成交易」）。
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / '样本'
OUT = HERE / '产物'
VERSION = 'amlsim-exam-v1'

# AMLSim 只有步数（1..149），没有日期。这两条是**假设**，说明里必须写死。
BASE_TIME = pd.Timestamp('2026-01-01 00:00:00')
HOURS_PER_STEP = 1

REMARK = 'AMLSim合成交易'
FRAUD_SHARE = 0.20      # 罪犯账户占比：真案子不会两成的人都有问题，这里是为了有得考
MIN_FEEDERS = 5         # 当"归集中心"的门槛：至少几个罪犯账户直接给它打过钱

# IBM/AMLSim master 分支 sample/ 目录，抓下来的包逐个校验
SHA256 = {
    '20K_fanin200': 'e2479ab7a1ecfcd369a7738c855364825561bf9d888d2ad53174e0ed10fd1f1b',
    '20K_cycle200': 'da85ffd26f2c0a082f69b038a9bb5ebd2b6e9c0df15707381aeddcfcb572ae20',
    '20K_fanin200cycle200': 'f187bc5784223cdee137ac603164f7183fd58f114090f39e2a12543b6bf48319',
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_sample(sample):
    """包还在的话校验一次，防止样本被换掉而没人发现。"""
    tar = SAMPLES / (sample + '.tgz')
    if tar.exists() and SHA256.get(sample) and sha256(tar) != SHA256[sample]:
        raise SystemExit(f'样本包校验不过，别用：{tar}')
    if not (SAMPLES / sample / 'nodes.csv').exists():
        raise SystemExit('没有解开的样本，先跑 amlsim/下载官方样本.sh')


def load(sample):
    d = SAMPLES / sample
    nodes = pd.read_csv(d / 'nodes.csv')
    tx = pd.read_csv(d / 'transactions.csv')
    fraud = set(int(x) for x in nodes.loc[nodes.isFraud == 1, 'nodeid'])
    return nodes, tx, fraud


def aid(node):
    return f'syn{node:06d}'


def choose_fraud(fraud, tx, seed, target):
    """挑几个"归集中心"+ 它们的直接付款方 + 中心往上的收款方，构成罪犯分组。

    AMLSim 样本里没有"第几个剧本"这一列，罪犯子图又互相连通（探过：1799 个罪犯在一个
    连通块里），所以只能这样取。分组是我推的，不是 IBM 给的。
    """
    sub = tx[tx.sourceNodeId.isin(fraud) & tx.targetNodeId.isin(fraud)]
    payers, collects = {}, {}
    for center, grp in sub.groupby('targetNodeId'):
        payers[int(center)] = sorted(set(int(x) for x in grp.sourceNodeId))
    for boss, grp in sub.groupby('sourceNodeId'):
        collects[int(boss)] = sorted(set(int(x) for x in grp.targetNodeId))

    centers = sorted((c for c, ps in payers.items() if len(ps) >= MIN_FEEDERS),
                     key=lambda c: (-len(payers[c]), c))
    rng = random.Random(seed)
    rng.shuffle(centers)

    picked, groups = set(), []
    for center in centers:
        if len(picked) >= target:
            break
        if center in picked:
            continue
        room = target - len(picked)
        if room < 3:
            break
        ps = [p for p in payers[center] if p not in picked]
        rng.shuffle(ps)
        crew = ps[:min(len(ps), max(2, room - 2))]
        if len(crew) < 2:
            continue
        boss = next((b for b in collects.get(center, []) if b not in picked), None)
        members = {center, *crew, *([boss] if boss else [])}
        picked |= members
        groups.append({'归集中心': aid(center), '直接付款方': [aid(p) for p in crew],
                       '中心往上的收款方': aid(boss) if boss else None,
                       '成员': sorted(aid(m) for m in members)})
    return picked, groups


def choose_clean(fraud, tx, seed, target, balls=2):
    """挑清白账户：整份样本里跟任何罪犯都没有一笔往来，并且要成团（一人多笔才像真账单）。

    成团的做法：从清白池里选几个起点，按 BFS 往外长 2-4 个邻居，长出一片社区。
    这样每个账户都有往来，起点账户还会出现"很多人给他转钱"的样子——
    而 IBM 写明它不是罪犯，这正是专门用来量冤枉率的结构性陷阱，不是我编的。
    """
    clean = (set(int(x) for x in tx.sourceNodeId) | set(int(x) for x in tx.targetNodeId)) - fraud
    touched = set(int(x) for x in tx.loc[tx.targetNodeId.isin(fraud), 'sourceNodeId']) \
        | set(int(x) for x in tx.loc[tx.sourceNodeId.isin(fraud), 'targetNodeId'])
    pool = sorted(int(x) for x in clean - touched)
    sub = tx[tx.sourceNodeId.isin(pool) & tx.targetNodeId.isin(pool)]
    neighbors = {}
    for src, grp in sub.groupby('sourceNodeId'):
        neighbors.setdefault(int(src), set()).update(int(x) for x in grp.targetNodeId)
        for dst in grp.targetNodeId:
            neighbors.setdefault(int(dst), set()).add(int(src))
    rng = random.Random(seed + 1)
    hubs = sorted((x for x in neighbors if len(neighbors[x]) >= 4), key=lambda x: (-len(neighbors[x]), x))
    rng.shuffle(hubs)

    picked = set()
    for hub in hubs:
        if len(picked) >= target:
            break
        if hub in picked:
            continue
        frontier, picked = [hub], picked | {hub}
        while frontier and len(picked) < target:
            nxt = []
            for node in frontier:
                mates = [x for x in sorted(neighbors[node]) if x not in picked]
                rng.shuffle(mates)
                for x in mates[:rng.randint(2, 4)]:
                    if len(picked) >= target:
                        break
                    picked.add(x)
                    nxt.append(x)
            frontier = nxt
    return picked


def build(sample, accounts, seed):
    check_sample(sample)
    nodes, tx, fraud = load(sample)
    want_fraud = max(6, round(accounts * FRAUD_SHARE))
    fraud_sel, groups = choose_fraud(fraud, tx, seed, want_fraud)
    clean_sel = choose_clean(fraud, tx, seed, accounts - len(fraud_sel))
    selected = fraud_sel | clean_sel

    keep = tx[tx.sourceNodeId.isin(selected) & tx.targetNodeId.isin(selected)]
    # 清白池是按"整份样本里没碰过罪犯"筛的，所以留下的边只可能同侧
    mixed = keep[(keep.sourceNodeId.isin(fraud_sel) | keep.targetNodeId.isin(fraud_sel))
                 & (keep.sourceNodeId.isin(clean_sel) | keep.targetNodeId.isin(clean_sel))]
    assert mixed.empty, '卷子不该把清白账户和罪犯账户直接连起来'

    ledger = {n: [] for n in selected}
    serial = 0
    for row in keep.sort_values(['time', 'sourceNodeId', 'targetNodeId']).itertuples():
        src, dst, value, step = int(row.sourceNodeId), int(row.targetNodeId), float(row.value), int(row.time)
        serial += 1
        stamp = BASE_TIME + pd.Timedelta(hours=(step - 1) * HOURS_PER_STEP + (serial * 7) % 60)

        def row_for(other, direction):
            return {'交易时间': stamp.strftime('%Y-%m-%d %H:%M:%S'), '交易对方账号': aid(other),
                    '交易对方': aid(other), '收/支': direction, '金额': round(value, 2),
                    '商户单号': f'AML-{seed}-{serial:06d}', '支付方式': '零钱',
                    '商品': REMARK, '备注': REMARK}

        ledger[src].append(row_for(dst, '支出'))
        ledger[dst].append(row_for(src, '收入'))

    dropped = sorted(aid(n) for n, rows in ledger.items() if not rows)
    for node in dropped:
        ledger.pop(node)
    return nodes, ledger, selected, fraud_sel, groups, dropped, len(keep)


def write_case(sample, accounts, seed):
    sys.path.insert(0, str(HERE.parent / 'agent' / 'range'))
    from generator import write_json, write_xlsx  # 复用 main 的写法：列名、字节稳定都跟自家卷子一致

    nodes, ledger, selected, fraud_sel, groups, dropped, kept_tx = build(sample, accounts, seed)
    name = f'{sample}_n{accounts}_s{seed}'
    root = OUT / name
    dataset = root / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    for old in dataset.glob('*.xlsx'):
        old.unlink()

    info = nodes.set_index('nodeid')[['isFraud', 'fraudStep']]
    files = []
    for node in sorted(ledger):
        write_xlsx(dataset / f'syn_bill_{aid(node)}_微信.xlsx', ledger[node])
        files.append(f'syn_bill_{aid(node)}_微信.xlsx')

    truth = {
        'metadata': {
            'generator_version': VERSION, 'sample': sample, 'seed': seed,
            'sample_sha256': SHA256.get(sample),
            'source': 'https://github.com/IBM/AMLSim/tree/master/sample（master 分支，2026-11-11 抓取）',
            '账号数': len(ledger), '丢弃空账单': dropped, '交易笔数': kept_tx,
            '罪犯账户数': len([n for n in ledger if n in fraud_sel]),
            '假设1': f'AMLSim 只有步数没有日期，按 1 步={HOURS_PER_STEP} 小时映射，整卷跨约 6 天',
            '假设2': '金额照抄样本原值（中位数 252、最大 600），没换算成人民币量级',
            '假设3': '清白账户在整份样本里与任何罪犯账户都无往来，所以这份卷子比真案子干净',
            '层级真值': '没有。IBM 样本只标是不是参与洗钱剧本，不标一级/二级/三级，层级准确率对这份卷子不适用',
        },
        'accounts': [{'合成ID': aid(n), '合成名': f'合成账户{aid(n)}',
                      '角色标签': 'AMLSim剧本账户' if n in fraud_sel else 'AMLSim清白账户',
                      'isFraud': int(info.loc[n, 'isFraud']),
                      'fraudStep': int(info.loc[n, 'fraudStep']),
                      '层级标签': None, '洗钱相关': bool(info.loc[n, 'isFraud'])}
                     for n in sorted(ledger)],
    }
    write_json(root / 'truth.json', truth)
    write_json(root / '结构提示.json', {
        '警告': '这是 langouste 从资金方向推出来的分组，不是 IBM 的标注，不能当层级标准答案，只能人工核对用',
        'sample': sample, 'seed': seed, '分组': groups})
    print(f'{name}: 账号 {len(ledger)}（剧本内 {truth["metadata"]["罪犯账户数"]}）'
          f' 交易 {kept_tx} 笔 丢弃空账单 {len(dropped)}')
    return root


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', default='20K_fanin200cycle200', choices=sorted(SHA256))
    ap.add_argument('--accounts', type=int, action='append', default=None)
    ap.add_argument('--seed', type=int, default=11)
    args = ap.parse_args()
    for n in (args.accounts or [30, 100, 500]):
        write_case(args.sample, n, args.seed)
