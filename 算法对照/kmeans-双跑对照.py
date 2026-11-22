#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一份卷子、同一套参数，只换聚类那一步：老 sklearn 版 vs 新 numpy 手写版，并排出数。

为什么要有这个文件：2026-11-12 决定把层级聚类从 sklearn 换成 numpy 手写
（理由详单见旁边 双跑结果-2026-11-12.md）。换算法不能只说一句"换了"，
得把两份成绩单一起摆出来，谁也不许只印好看的那张。

跑法（在项目根目录）：
    env MPLCONFIGDIR=/tmp/mplcache <venv>/python -X utf8 算法对照/kmeans-双跑对照.py
结果写到 算法对照/双跑对照-<日期>.json，同时打一张对照表。

注意：这里只换 _kmeans_numpy 这一个函数，其他参数、判据、卷子、种子都不动，
所以两份成绩的差就是聚类的差。
归属：langouste（这个文件夹里的东西都是我写的）。
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
sys.argv = [sys.argv[0]]

from sklearn.cluster import KMeans                       # 只在这个对照脚本里出现，分析机里已经没有了
from sklearn.preprocessing import StandardScaler
import gambling_analysis as ga
from evaluate import PARAMETERS, evaluate, load_scenario

NAME = ['s30_clean_full_dev', 's30_noise_full_dev', 's30_noise_missing_dev',
        's100_clean_full_dev', 's100_noise_full_dev', 's500_noise_full_dev',
        's30_innocent_full_dev', 's500_innocent_full_dev',
        's100_noise_missing_holdout', 's500_clean_full_holdout']

numpy版 = ga._kmeans_numpy
记账 = []


def sklearn版(X, k, seed=42, n_init=10, max_iter=300, tol=1e-4):
    """把换掉之前那行原样搬回来：StandardScaler + KMeans(random_state=42, n_init=10, max_iter=300)。"""
    Xs = StandardScaler().fit_transform(np.asarray(X, dtype=np.float32))
    km = KMeans(n_clusters=k, random_state=seed, n_init=n_init, max_iter=max_iter).fit(Xs)
    return km.labels_.astype('int64'), float(km.inertia_)


def 跑一遍(实现):
    ga._kmeans_numpy = 实现
    out = {}
    for name in NAME:
        r, _行 = evaluate(load_scenario(name), json.loads(PARAMETERS.read_text(encoding='utf-8')))
        分布 = {}
        for 格 in r.get('tier_confusion') or []:
            分布[str(格['predicted'])] = 分布.get(str(格['predicted']), 0) + 格['count']
        out[name] = {'accounts': r['accounts'],
                     'tier': [r['tier_correct'], r['tier_valid'], r['tier_accuracy']],
                     'TP_FN_FP_TN': [r['TP'], r['FN'], r['FP'], r['TN']],
                     'recall': r['laundering_recall'], 'fpr': r['false_positive_rate'],
                     '判出的层级分布': 分布}
    return out


旧 = 跑一遍(sklearn版)
ga._kmeans_numpy = numpy版
新 = 跑一遍(numpy版)

合计 = {'sklearn': [0, 0], 'numpy': [0, 0]}
print()
print(f"{'卷子':30} {'层级判对/可评 老→新':30} {'判对率 老→新':22} {'TP/FN/FP/TN 老→新':30} {'误报率 老→新'}")
for name in NAME:
    o, n = 旧[name], 新[name]
    合计['sklearn'] = [合计['sklearn'][0] + o['tier'][0], 合计['sklearn'][1] + o['tier'][1]]
    合计['numpy'] = [合计['numpy'][0] + n['tier'][0], 合计['numpy'][1] + n['tier'][1]]
    print(f"{name:30} {str(o['tier'][:2]) + ' → ' + str(n['tier'][:2]):30} "
          f"{str(o['tier'][2]) + ' → ' + str(n['tier'][2]):22} "
          f"{str(o['TP_FN_FP_TN']) + ' → ' + str(n['TP_FN_FP_TN']):30} "
          f"{o['fpr']} → {n['fpr']}")
print(f"{'十份合计（判对/可评）':30} {合计['sklearn'][0]}/{合计['sklearn'][1]} → {合计['numpy'][0]}/{合计['numpy'][1]}")
合计行 = f"十份合计：sklearn {合计['sklearn'][0]}/{合计['sklearn'][1]}，numpy {合计['numpy'][0]}/{合计['numpy'][1]}"
print(合计行)

合并 = {'说明': '同一份卷子同一套参数，只换聚类实现；sklearn 列是换掉之前的算法',
        'sklearn': 旧, 'numpy': 新}
落 = ROOT / '算法对照' / f'双跑对照-{date.today().isoformat()}.json'
合并['十份合计'] = 合计
落.write_text(json.dumps(合并, ensure_ascii=False, indent=1), encoding='utf-8')
print('写好了：', 落)
