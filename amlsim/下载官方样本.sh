#!/usr/bin/env bash
# 把 IBM 官方 AMLSim 仓库里现成的三份合成账单样本抓到 样本/ 下。
# 为什么用官方样本而不是自己跑 Java：AMLSim 主程序是 Java + Maven，还依赖 mason、webgraph，
# 这台机器装不动；而 IBM 已经把自己跑出来的 2 万账户结果放在仓库 sample/ 里，
# 里面 nodes.csv 直接带 isFraud（谁是罪犯）和 fraudStep（第几步参与手法）——标准答案就在里面。
# 出处：https://github.com/IBM/AMLSim （sample/20K_*.tgz，仓库 master 分支，2026-11-11 抓取）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p 样本
base="https://cdn.jsdelivr.net/gh/IBM/AMLSim@master/sample"
declare -A sha=(
  [20K_fanin200]=e2479ab7a1ecfcd369a7738c855364825561bf9d888d2ad53174e0ed10fd1f1b
  [20K_cycle200]=da85ffd26f2c0a082f69b038a9bb5ebd2b6e9c0df15707381aeddcfcb572ae20
  [20K_fanin200cycle200]=f187bc5784223cdee137ac603164f7183fd58f114090f39e2a12543b6bf48319
)
for name in "${!sha[@]}"; do
  if [ ! -s "样本/$name.tgz" ] || ! echo "${sha[$name]}  样本/$name.tgz" | sha256sum --quiet --check -; then
    echo "下载 $name"
    curl -sSL --retry 3 -o "样本/$name.tgz" "$base/$name.tgz"
    echo "${sha[$name]}  样本/$name.tgz" | sha256sum -c -
  fi
  [ -d "样本/$name" ] || tar xzf "样本/$name.tgz" -C 样本
done
echo "样本就绪：" && ls 样本
