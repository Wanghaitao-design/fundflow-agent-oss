#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洗钱加分行号：有源码和没源码两条读法必须给出一样的行号。

为什么要有这个文件：打包出来的 exe 里没有 .py 源码，
`tools/detect_laundering.py` 原来只会 `inspect.getsourcelines` 读源码，
一到了 exe 里就 `OSError: could not get source code`，
整个洗钱检测没跑成，Excel 名单里"洗钱嫌疑"那一栏直接把这个软件搞崩
（2026-11-12 第 4 次 Windows 打包就是这么失败的）。
现在多了条"读字节码"的路，这个自检保证两条路不会各说各话。

跑法：python agent/verify/洗钱加分行自检.py　（退出码 0 才算过）
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent' / 'mcp_server'))
sys.path.insert(0, str(ROOT))

import importlib

import gambling_analysis as ga                        # noqa: E402
# tools/__init__.py 里有个同名的函数，会把模块名盖掉，所以按完整模块名取
importlib.import_module('tools')
观测 = importlib.import_module('tools.detect_laundering')

失败 = []


def 检查(条件, 说):
    print(('　PASS　' if 条件 else '　FAIL　') + 说)
    if not 条件:
        失败.append(说)


def main():
    import types
    # 平时传进来的是"挂在某个分析机上的方法"，这里没真数据，套一个空壳当绑定的方法用
    方法 = types.MethodType(ga.GamblingAnalyzer._detect_money_laundering, object())

    源码行, 源码说法 = 观测.找加分行(方法)
    检查(len(源码行) == 6, '读源码：找到 6 处加分行 %s' % 源码行)

    字节行 = 观测._加分行从字节码(方法)
    检查(字节行 == 源码行, '读字节码：行号和读源码完全一致 %s' % 字节行)

    # 装作这台电脑上没有源码（就是 exe 里的处境），必须还能读出同样的行号、不许崩
    原函数 = inspect.getsourcelines

    def 装没源码(*a, **k):
        raise OSError('could not get source code')
    inspect.getsourcelines = 装没源码
    try:
        兜底行, 兜底说法 = 观测.找加分行(方法)
    except BaseException:
        兜底行, 兜底说法 = None, '崩了'
        检查(False, '没有源码时不许崩（这条是第 4 次打包失败的真原因）')
    finally:
        inspect.getsourcelines = 原函数
    检查(兜底行 == 源码行, '没有源码时：靠字节码读出同样的 6 行（读法：%s）' % 兜底说法)

    # 加分行的行号必须真是源码里那几行 `l_score += `
    原文 = (ROOT / 'gambling_analysis.py').read_text(encoding='utf-8').splitlines()
    对 = all('l_score' in 原文[行 - 1] and '+=' in 原文[行 - 1] for 行 in 源码行)
    检查(对, '这些行号回到 gambling_analysis.py 里逐行核过，确实写着 l_score +=')

    print('')
    if 失败:
        print('洗钱加分行自检：FAIL（%d 条）' % len(失败))
        return 1
    print('洗钱加分行自检：ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
