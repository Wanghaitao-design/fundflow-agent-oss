#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民警会点的那条路：开窗口 → 选账单文件夹 → 点开始 → 出三样东西。

这条以前没人跑到过（跑分和命令行自检都不经过窗口），2026-11-11 加。
需要图形环境；本机上用 xvfb-run 跑：

    xvfb-run -a .venv/bin/python -X utf8 agent/verify/gui_path_selftest.py [账单文件夹]

规矩：只许"必须不崩 + 必须命中"，不许把已知 bug 当应该发生的事。
"""
import sys
import time
import tempfile
import traceback
from pathlib import Path

根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(根))
sys.path.insert(0, str(根 / 'agent'))

import tkinter as tk                                     # noqa: E402
from tkinter import ttk                                  # noqa: E402
import officer_app                                       # noqa: E402


def 造账单(目录: Path):
    from openpyxl import Workbook
    目录.mkdir(parents=True, exist_ok=True)
    行 = ['交易时间', '交易对方账号', '交易对方', '收/支', '金额', '商户单号', '支付方式', '商品', '备注']
    份 = {
        'syn_bill_A001_微信.xlsx': [('2026-03-01 20:11:00', 'B002', 'B002', '收入', 600.0, 'T1', '零钱', '合成', '合成充值'),
                                    ('2026-03-02 21:05:00', 'B002', 'B002', '收入', 600.0, 'T2', '零钱', '合成', '合成充值'),
                                    ('2026-03-03 22:30:00', 'C009', 'C009', '支出', 1800.0, 'T3', '零钱', '合成', '合成结算')],
        'syn_bill_B002_微信.xlsx': [('2026-03-01 20:11:00', 'A001', 'A001', '支出', 600.0, 'T1', '零钱', '合成', '合成充值'),
                                    ('2026-03-02 21:05:00', 'A001', 'A001', '支出', 600.0, 'T2', '零钱', '合成', '合成充值')],
    }
    for 名, 数据 in 份.items():
        本 = Workbook()
        页 = 本.active
        页.append(行)
        for r in 数据:
            页.append(list(r))
        本.save(目录 / 名)
    return 目录


def 等(窗, 判断, 秒=240):
    截止 = time.time() + 秒
    while time.time() < 截止:
        窗.根.update()
        if 判断():
            return True
        time.sleep(0.05)
    return False


def main():
    账单 = Path(sys.argv[1]) if len(sys.argv) > 1 else 造账单(Path(tempfile.mkdtemp(prefix='gui_path_')) / '账单')
    if not 账单.is_dir():
        print('FAIL 账单文件夹不存在：', 账单)
        return 1
    窗 = officer_app.窗口(tk, ttk)
    失败 = []
    # 1) 窗口必须建得起来，按钮必须在
    钮 = getattr(窗, '开始钮', None)
    if 钮 is None:
        print('FAIL 窗口建起来了但找不到"开始"按钮')
        return 1
    # 2) 把文件夹路径填进输入框（等价于民警点"选择账单文件夹"）
    窗.路径框.delete(0, 'end')
    窗.路径框.insert(0, str(账单))
    # 3) 点开始
    钮.invoke()
    if not 等(窗, lambda: not 窗.任务中):
        失败.append('点了开始后 4 分钟还没跑完')
    状态 = 窗.状态.cget('text')
    结果 = Path(窗.结果目录) if 窗.结果目录 else None
    if '出错' in 状态 or '出错' in 窗.文本.get('1.0', 'end'):
        失败.append('窗口里报了错：\n' + 窗.文本.get('1.0', 'end'))
    if 状态 != '做完了':
        失败.append('状态应该是"做完了"，实际是「%s」' % 状态)
    if not 结果 or not 结果.is_dir():
        失败.append('没有结果目录')
    else:
        缺 = [f for f in ('1_人员名单.xlsx', '2_资金流向图.png', '3_情况说明.txt') if not (结果 / f).is_file()]
        if 缺:
            失败.append('结果目录缺：' + '、'.join(缺))
    窗.根.destroy()
    if 失败:
        print('FAIL 民警那条路走不通：')
        for f in 失败:
            print('  -', f)
        return 1
    print('PASS 窗口→选文件夹→点开始→三样产物齐（结果在 %s）' % 结果)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('FAIL 跑这个自检自己崩了：')
        print(traceback.format_exc())
        sys.exit(1)
