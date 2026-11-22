#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""簇号对照：同一份真实特征矩阵，老 sklearn 的 KMeans 和新 numpy 手写版分出来的是不是同一堆点。

簇号本身没有语义（同一堆叫 0 还是叫 3 无所谓），所以比的是：
  · 惯性 inertia（越小越紧凑）——两版差多少；
  · "换着叫簇号之后仍落在同一堆"的点占多少——100% 就是分毫不差。

这是 2026-11-12 换聚类实现时留下的证据，跑法（项目根目录）：
    env MPLCONFIGDIR=/tmp/mplcache <venv>/python -X utf8 算法对照/簇号对照.py
归属：langouste。这个脚本是**对照用的脚手架**，不参与分析机运行，
所以它 import sklearn 是有意的：分析机里没有 sklearn 由 p1_smoke 那条契约看着。
"""
import contextlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
sys.argv = [sys.argv[0]]

from sklearn.cluster import KMeans                       # noqa: E402  只在这里出现，分析机里没有
from sklearn.preprocessing import StandardScaler
import gambling_analysis as ga                           # noqa: E402
from common import CACHE                                 # noqa: E402
from generator import generate, load_scenario            # noqa: E402
from tools import build_fund_graph, classify_tiers, scan_dataset  # noqa: E402

for 卷 in ['s30_noise_full_dev', 's100_noise_full_dev', 's500_noise_full_dev']:
    参数 = load_scenario(卷)
    with contextlib.redirect_stdout(io.StringIO()):
        产物 = generate(**参数)
        did = scan_dataset(产物['数据集目录'])['结论']['dataset_id']
        build_fund_graph(did)
        classify_tiers(did)
        a = CACHE[did]['analyzer']
        深度 = a._compute_topo_depth()
        名单 = list(a.nodes)
        X = a._build_feature_matrix(名单, 深度)
    k = 5 if len(名单) >= 30 else (4 if len(名单) >= 15 else 3)
    新标签, 新惯性 = ga._kmeans_numpy(ga._zscore(X), k)
    老 = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300).fit(
        StandardScaler().fit_transform(np.asarray(X, dtype=np.float32)))
    配 = Counter(zip([int(x) for x in 老.labels_], [int(x) for x in 新标签]))
    同堆 = 0
    for x in range(k):
        行 = {b: n for (aa, b), n in 配.items() if aa == x}
        if 行:
            同堆 += max(行.values())
    print(f'{卷}: 账号 {len(名单)} 簇数 k={k} | sklearn 惯性 {老.inertia_:.1f} | '
          f'numpy 惯性 {新惯性:.1f}（差 {新惯性 - 老.inertia_:+.2f}） | '
          f'换着叫簇号仍同堆 {同堆}/{len(名单)} = {round(100 * 同堆 / len(名单), 1)}%')
