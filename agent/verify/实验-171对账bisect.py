# -*- coding: utf-8 -*-
"""实验-171对账 bisect 版（2026-11-27 清欠账①，配合 实验-171对账.py）：

把历史上任一时期的 gambling_analysis.py 拿来冒充当前模块，在同一份
s500_innocent_full_dev 卷上数「老办法点出几个代理嫌疑」。
279c200（11-11，复核代码还没进）实测 = 173 → 结论见 docs/口径.md 勘误块：171 作废。

用法：
  python agent/verify/实验-171对账bisect.py <旧版 gambling_analysis.py 路径>
旧版文件用 git show 拉（注意 PowerShell 的 > 重定向会写成 UTF-16，Python 读不了）：
  cmd /c "git show 279c200:gambling_analysis.py > ga_old.py"
"""
import importlib.util
import json
import sys
from pathlib import Path

GA_PATH = Path(sys.argv[1])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent' / 'range'))
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 用旧文件冒充 gambling_analysis，早于一切下游 import
spec = importlib.util.spec_from_file_location('gambling_analysis', GA_PATH)
old_ga = importlib.util.module_from_spec(spec)
sys.modules['gambling_analysis'] = old_ga
spec.loader.exec_module(old_ga)

from common import CACHE, ga                                       # noqa: E402
from generator import generate, load_scenario                      # noqa: E402
from tools import scan_dataset, build_fund_graph, classify_tiers   # noqa: E402

assert ga is old_ga, 'ga 被下游重新导入成别的了'

AGENT = ('一级代理嫌疑', '二级代理嫌疑', '三级代理嫌疑')
产物 = generate(**load_scenario('s500_innocent_full_dev'))
真值 = json.loads(Path(产物['标准答案路径']).read_text(encoding='utf-8'))
答案层级 = {a['合成ID']: (a.get('层级标签') or '') for a in 真值['accounts']}
有复核 = hasattr(ga, 'AGENT_MIN_INFLOW')
if 有复核:   # 老办法 = 四条代理固定线关掉
    for 名, 值 in {'AGENT_MIN_INFLOW': 0.0, 'AGENT_MIN_IN_DEG': 0.0,
                   'AGENT_MIN_IN_DAYS': 1.0, 'AGENT_MIN_OUT_DEG': 0.0}.items():
        setattr(ga, 名, 值)


def 完整(result):
    路径 = result['artifacts'].get('完整结果')
    return json.loads(Path(路径).read_text(encoding='utf-8')) if 路径 else result


扫描 = 完整(scan_dataset(产物['数据集目录']))
编号 = 扫描['结论']['dataset_id']
build_fund_graph(编号)
判定 = 完整(classify_tiers(编号, {}))['结论'].get('判定', [])
点出 = [x['账号'] for x in 判定 if x['层级'] in AGENT]
真代 = {a for a, 层 in 答案层级.items() if '代理嫌疑' in 层}
print(f'RESULT {GA_PATH.name} 复核参数={"有" if 有复核 else "无"} '
      f'点出 {len(点出)} 人｜真代理混入 {len(set(点出) & 真代)}')
