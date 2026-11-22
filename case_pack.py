#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案由包读取器。

分析机里原本写死的词表和门槛数字，全部改从这里读。
包目录：case_packs/<包名>/01_词表.csv 和 03_门槛.csv
两份表都是 Excel 双击就能改的 CSV。

规矩：
  · 词表里"状态"不是"已有"的那一行，不加载（那是待补的建议）
  · 门槛表最后一列"可改参数"写成 名字=值;名字=值，这一列才是机器读的
  · 同名参数允许在几行里重复，但值必须一模一样，否则直接报错停下
  · 表读不到就报错，不退回用代码里的旧数字——免得悄悄用了一份没人核对的词表
  · **import 本模块不读表**（2026-11-12 改）：谁第一次真用到才读，读过的复用。
    以前模块末尾有一句 PACK = CasePack()，import 的当口就去找表，表一缺整个模块
    import 失败——打成 exe 就是"双击闪一下没了"，民警连报错都看不见。
  · 表在哪儿：默认本文件旁边的 case_packs/；也可以设环境变量 FUNDFLOW_CASE_PACKS
    指到别处，或者在 import 之后直接改本模块的 PACKS（officer_app 就靠这个让
    "民警拿 Excel 改软件旁边的表、下次打开就生效"这句话成立）
"""
from pathlib import Path
import csv
import os

ROOT = Path(__file__).resolve().parent


def _默认表目录():
    """环境变量指了就用指的地方，没用就取本文件旁边的 case_packs/。"""
    指 = (os.environ.get('FUNDFLOW_CASE_PACKS') or '').strip()
    return Path(指).expanduser().resolve() if 指 else ROOT / 'case_packs'


PACKS = _默认表目录()
DEFAULT_PACK = os.environ.get('FUNDFLOW_CASE_PACK', 'wangdu')


class CasePackError(FileNotFoundError):
    """判据表缺失或改坏了。

    故意继承 FileNotFoundError：以前写 except FileNotFoundError 的地方照样接得住，
    外层（officer_app / 打包入口 / mcp 工具）不管接哪个都不会漏。
    """


class CasePack:

    def __init__(self, name=None, packs_dir=None):
        self.name = name or DEFAULT_PACK
        # 每次现读模块变量 PACKS：这样 officer_app 在 import 之后改路径仍然生效
        目录 = Path(packs_dir) if packs_dir is not None else Path(PACKS)
        self.dir = 目录 / self.name
        if not self.dir.is_dir():
            raise CasePackError(
                f'找不到案由包：{self.dir}\n'
                f'  判据表（什么算线索、门槛多少）应当放在 {目录}{os.sep}{self.name}{os.sep} 下面，'
                f'里面至少要有 01_词表.csv 和 03_门槛.csv。\n'
                f'  读的是哪份表由这些决定：环境变量 FUNDFLOW_CASE_PACKS={os.environ.get("FUNDFLOW_CASE_PACKS") or "(没设，用默认)"}、'
                f'包名 FUNDFLOW_CASE_PACK={DEFAULT_PACK}、或者代码里改 case_pack.PACKS。')
        self.words_by_group = self._read_words()
        self.params = self._read_params()

    # ── 词表 ────────────────────────────────────────────────
    def _read_words(self):
        rows = self._csv('01_词表.csv')
        groups = {}
        for row in rows:
            name = row['词类'].strip()
            if row['状态'].strip() != '已有':
                continue
            words = [w.strip() for w in row['词'].split('/') if w.strip()]
            if not words:
                raise CasePackError(f'词表第 {name} 行是空的：{self.dir / "01_词表.csv"}')
            groups[name] = words
        if not groups:
            raise CasePackError(
                f'{self.name} 包里一条词表都没加载，检查状态列是不是都写了"已有"：{self.dir}')
        return groups

    # ── 门槛数字 ─────────────────────────────────────────────
    def _read_params(self):
        rows = self._csv('03_门槛.csv')
        key = '可改参数'
        params = {}
        for row in rows:
            raw = (row.get(key) or '').strip()
            if not raw:
                continue
            for item in raw.split(';'):
                item = item.strip()
                if not item:
                    continue
                if '=' not in item:
                    raise CasePackError(
                        f'{row["门槛名"]} 的参数写法不对：{item}，要写成 名字=值（{self.dir}）')
                k, v = item.split('=', 1)
                k, v = k.strip(), v.strip()
                try:
                    value = int(v) if v.lstrip('-').isdigit() else float(v)
                except ValueError:
                    raise CasePackError(f'{row["门槛名"]} 的参数 {k} 的值不是数：{v}（{self.dir}）')
                if k in params and params[k] != value:
                    raise CasePackError(
                        f'参数 {k} 被改成了两个不同的值：{params[k]} 和 {value}（包 {self.name}，表在 {self.dir}）')
                params[k] = value
        if not params:
            raise CasePackError(
                f'{self.name} 包的门限表"可改参数"这一列是空的：{self.dir / "03_门槛.csv"}')
        return params

    def _csv(self, filename):
        path = self.dir / filename
        if not path.is_file():
            raise CasePackError(f'案由包 {self.name} 缺文件：{path}')
        try:
            with path.open(encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise CasePackError(f'{path} 是空文件')
                return [{(k or '').strip(): (v or '').strip() for k, v in row.items()}
                        for row in reader]
        except UnicodeDecodeError as 错:
            raise CasePackError(f'{path} 不是 UTF-8 编码的表，用 Excel 另存为 CSV UTF-8 再存回去：{错}')

    # ── 给外面用 ─────────────────────────────────────────────
    def words(self, *groups):
        """按词类取词，多个词类会拼成一份去重后的列表（保持原顺序）。"""
        out = []
        for g in groups:
            if g not in self.words_by_group:
                raise KeyError(f'案由包 {self.name} 的词表里没有「{g}」这一类')
            out.extend(self.words_by_group[g])
        return list(dict.fromkeys(out))

    def num(self, key):
        if key not in self.params:
            raise KeyError(f'案由包 {self.name} 的门限表里没有参数「{key}」')
        return self.params[key]

    def describe(self):
        return (f'案由包 {self.name}：{len(self.words_by_group)} 组词 '
                f'{sum(len(v) for v in self.words_by_group.values())} 条，'
                f'{len(self.params)} 个门槛数')


# ── 用到才读，读过的复用。import 这个模块不会走到下面任何一行 ──────────────
_缓存 = {}


def get_pack(name=None):
    """取案由包：第一次用时读表，之后复用同一份。表读不出来抛 CasePackError。"""
    key = name or DEFAULT_PACK
    if key not in _缓存:
        _缓存[key] = CasePack(key)
    return _缓存[key]


def 清缓存():
    """改过 case_pack.PACKS 或换过环境变量之后调一下，强制重读。"""
    _缓存.clear()


# 这里原来是 PACK = CasePack()——import 当口就读表，exe 里表没打进包就当着面炸。
# 2026-11-12 删掉，改由 gambling_analysis 在 import 时 try/except 调 get_pack()。

if __name__ == '__main__':
    包 = get_pack()
    print(包.describe())
    for g, ws in 包.words_by_group.items():
        print(f'  {g}: {len(ws)} 条 -> {" / ".join(ws[:4])} ...')
    for k, v in 包.params.items():
        print(f'  {k} = {v}')
