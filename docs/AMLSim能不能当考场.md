# AMLSim 能不能当我们的考场（实测结论）

不是看介绍写的，是把仓库拉下来看了它到底吐什么文件。
仓库：IBM/AMLSim，412 星，Apache-2.0 授权（可以商用可以改，注明即可），
最后一次提交 2025-09-17，没归档。

## 它吐出来的东西（原样抄字段名）

交易表 tx.csv：
    TXN_ID, ACCOUNT_ID, COUNTER_PARTY_ACCOUNT_NUM, TXN_SOURCE_TYPE_CODE,
    tx_count, TXN_AMOUNT_ORIG, start, end
账户表 accounts.csv：
    ACCOUNT_ID, PRIMARY_CUSTOMER_ID, init_balance, start, end,
    country, business, suspicious, isFraud, modelID
答案表 alerts.csv：
    ALERT_KEY, ALERT_TEXT, ACCOUNT_ID, CUSTOMER_ID, EVENT_DATE,
    CHECK_NAME, Organization_Type, Escalated_To_Case_Investigation
剧本 alertPatterns.csv：
    type 只有 fan_in / fan_out / cycle 三种，is_sar=True/False

## 能当考场的地方（真有价值）

- 答案是天生的：accounts.csv 每行直接写着 suspicious / isFraud，
  alerts.csv 写着"这笔属于哪种手法、哪天发生的"。不用我们自己编剧本自己打分。
- 三种手法 fan_in（多人归集）/ fan_out（层层分发）/ cycle（转一圈回来），
  正好对得上我们的 G08 多人汇给一个人、G03 往上领额度往下发、G10 一条线中转。
- 能批量造：仓库自带 1K / 10K / 100K / 1M / 10M 几档规模，正好测我们
  "人越多判得越准、30 人就抓瞎"这个毛病能改善多少。

## 它考不到的地方（必须说死，不然是给自己挖坑）

- **没有姓名**。只有 ACCOUNT_ID 数字编号。我们的核心产出是"人员名单"，
  它这边没有"人"，只有编号。
- **没有备注**。所以我们那 29 个赌博词、31 个境外词，一条都考不到。
- **日期是"第几天"的整数**（start=1，end=50），不是真实时刻。
  我们的"收到钱 24 小时内转出""5 分钟内 5 笔""跨几天"这些判据，
  在它给的时间精度下根本没法判。
- **没有代理层级这个概念**。它只有 fan_in/fan_out 这种图形，
  我们最值钱、也最容易挨问的"一级二级三级代理怎么分"，它一个字都验不了。
- **没有中文表头**。微信/支付宝/各家银行账单怎么认，它一句都帮不上，
  而那正是我们最该考的科目。

## 所以结论是这样

AMLSim 能当**半张考卷**：只考图结构那几迹象（归集、分发、过路、循环），
而且必须先写一层转换，把它的 tx.csv 伪装成我们的内部表格式，
日期要自己从"第几天"放大成真实时刻。

**不能把它当成绩单一等奖**：格式识别、同人多卡归并、代理层级这三件
我们真正的价值所在，它一样都考不到。谁要说"接了 AMLSim 就有准确率了"，
那个准确率也只覆盖半张卷子。

## 建议怎么用

1. 先写转换层：tx.csv + accounts.csv → 我们内部统一格式（半天到一天的活）
2. 只让它考 G03 / G06 / G08 / G10 四条迹象，成绩单上写清楚"仅图结构四项"
3. 另外半张卷子还是得我们自己出：把现有出题机生成的假账单，
   输出成工行/农行/支付宝/微信四种表头，缺列、加脏行、拆多 sheet，
   专门考格式识别和同人归并
4. Kaggle 上那几套（Elliptic 是虚拟币交易图、PaySim 是海外支付模拟）
   字段同样对不上中文账单，优先级排在上面两件事后面，不急着注册
