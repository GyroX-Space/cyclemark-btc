# CMCI 第一批真实数据接入报告 v0.1

运行日期：2026-11-28  
方案依据：《CMCI 第一批真实数据接入计划 v0.1》  
数据库：`data/cmci/cmci.db`（迁移 v6）

## 1. 本轮完成情况

| 批次 | 内容 | 状态 |
|---|---|---|
| D1 | FRED/ALFRED 宏观数据（10 项） | 已接入（月度 vintage 快照） |
| D2 | BTC/ETH 日线行情 | 已接入（Yahoo Finance 参考序列；Kraken 文件导入器已就绪） |
| D3 | BTC 链上与供给 | 已接入（Blockchain.com，日频） |
| D4 | 稳定币供应 | 已接入（DefiLlama） |
| D5 | 美国现货 BTC ETF 资金流与 AUM | 已接入（TFTC，CC BY 4.0） |
| D6 | 数据集、回放、审计 | 已完成（`CMCI-CORE-2015` v2，已封存） |

执行命令：

```bash
python scripts/cmci_first_batch.py --batches d2,d3,d4,d5,derived
FRED_API_KEY=... python scripts/cmci_first_batch.py --batches d1,derived
python scripts/cmci_build_core.py
```

## 2. 实际覆盖

| 指标 | 起点 | 终点 | 观测数 | 说明 |
|---|---|---|---|---|
| FED_BALANCE_SHEET | 2014-01-01 | 2026-11-25 | 674 | 周频，143 个 vintage |
| FED_FUNDS_RATE | 2014-01-01 | 2026-11-26 | 4,713 | 日频，143 个 vintage |
| US_10Y_YIELD | 2014-01-02 | 2026-11-25 | 3,226 | 日频，143 个 vintage |
| US_10Y_REAL_YIELD | 2014-01-02 | 2026-11-25 | 3,226 | 日频，143 个 vintage |
| USD_BROAD_INDEX | 2014-01-01 | 2026-11-20 | 15,517 | 日频，94 个 vintage，修订频繁 |
| VIX | 2014-01-02 | 2026-11-26 | 3,283 | 日频，143 个 vintage |
| HY_CREDIT_SPREAD | 2023-11-28 | 2026-11-26 | 786 | 仅 37 个 vintage，ALFRED 历史受限 |
| US_YIELD_CURVE_10Y2Y | 2014-01-02 | 2026-11-27 | 3,227 | 日频，143 个 vintage |
| US_CPI | 2014-01-01 | 2026-10-01 | 755 | 月频，142 个 vintage |
| US_UNEMPLOYMENT | 2014-01-01 | 2026-10-01 | 254 | 月频，142 个 vintage |
| BTC_CIRCULATING_SUPPLY | 2015-01-01 | 2026-11-27 | 4,349 | Blockchain.com |
| BTC_ISSUANCE | 2015-01-02 | 2026-11-27 | 4,348 | 由流通量差分 |
| BTC_HASHRATE | 2015-01-01 | 2026-11-26 | 4,345 | Blockchain.com |
| BTC_DIFFICULTY | 2015-01-01 | 2026-11-26 | 4,345 | Blockchain.com |
| BTC_MINER_REVENUE | 2015-01-01 | 2026-11-26 | 4,348 | Blockchain.com |
| BTC_NETWORK_ACTIVITY | 2015-01-01 | 2026-11-26 | 4,345 | Blockchain.com |
| BTC_UNIQUE_ADDRESSES | 2015-01-01 | 2026-11-26 | 4,339 | 代理指标 |
| BTC_NETWORK_USAGE | 2015-01-01 | 2026-11-26 | 4,345 | L3 代理，复用链上交易数 |
| STABLECOIN_TOTAL_SUPPLY | 2017-11-29 | 2026-11-28 | 3,287 | DefiLlama，USD 计价 |
| STABLECOIN_SUPPLY_CHANGE | 2017-11-30 | 2026-11-28 | 3,286 | 由总供应差分 |
| BTC_SPOT_ETF_NET_FLOW | 2024-01-11 | 2026-11-25 | 738 | TFTC |
| BTC_SPOT_ETF_AUM | 2025-05-06 | 2026-11-25 | 393 | TFTC 仅近期提供 AUM |
| BTC_USD_OHLCV | 2014-09-17 | 2026-11-28 | 4,456 | Yahoo，交易所参考序列 |
| BTC_VOLUME | 2014-09-17 | 2026-11-28 | 4,456 | 单一交易场所口径 |
| BTC_RETURN | 2014-09-18 | 2026-11-28 | 4,455 | 由收盘价计算 |
| BTC_REALIZED_VOL | 2014-10-17 | 2026-11-28 | 4,426 | 30 日年化实现波动 |
| BTC_DRAWDOWN | 2014-09-17 | 2026-11-28 | 4,456 | 由收盘价计算 |
| ETH_USD_OHLCV | 2017-11-09 | 2026-11-28 | 3,307 | Yahoo，未覆盖 2015–2017 |

说明：

- L5 通过 Yahoo 参考序列接入，`measurement_scope` 明确标记为单一交易场所，不是全市场指数；Kraken 完整 OHLCVT 导入器已实现，提供文件后可用 `--kraken-btc/--kraken-eth` 替换。
- 所有历史观测都写入 `available_time`、`vintage_time`、`ingested_at`、`available_time_precision` 与 `available_time_method`。非 FRED 序列采用保守可得时间（T+1 或 T+2 日终），精度为 `date`。
- L3 的搜索热度、ETH 网络使用，以及 BTC Dominance、市场广度仍为 `unavailable`，未用不可靠数据填充。

## 3. 治理与授权登记

已登记 7 个数据源及其授权条款：

| 数据源 | 内部研究 | 商业使用 | 再发布 | 署名 |
|---|---|---|---|---|
| FRED/ALFRED | 允许 | 不允许 | 不允许 | 需要 |
| Blockchain.com | 允许 | 不允许 | 不允许 | 需要 |
| DefiLlama | 允许 | 不允许 | 不允许 | 需要 |
| TFTC | 允许 | 允许（CC BY 4.0） | 允许 | 需要 |
| Yahoo Finance | 允许 | 不允许 | 不允许 | 需要 |
| Kraken | 允许 | 不允许 | 不允许 | 需要 |
| CMCI Derived | 允许 | 不允许 | 不允许 | 不需要 |

指标层记录 `source_grade`、`measurement_scope`、`proxy_flag`、`license_status`、`coverage_status`；治理表与授权表均为 append-only。

## 4. D6 数据集与审计

- 数据集：`CMCI-CORE-2015`，版本 v3，状态 `sealed`
- 分区：
  - `training`：2015-01-01 – 2019-09-30
  - `identification`：2020-01-01 – 2022-09-30
  - `validation`：2023-01-01 – 2026-11-28
  - 相邻分区隔离期 90 天
- 分区哈希：`54f8739e…29e4b56`
- 回放时点：2018-06-01（18,995 行）、2021-06-01（39,960 行）、2024-06-01（61,798 行），均按 `available_time` 还原
- 质量审计：41 项检查、0 违规；前视审计：506 项检查、0 违规

注：v1 因首版分区窗口未留足隔离期而放弃；v2 为仅含 L2–L5 的版本；v3 加入 L1 宏观 vintage，是当前有效版本。

## 5. 已知限制

1. FRED 宏观 vintage 采用月末快照（每指标约 142–143 个版本），月内发布的数据可能最多延迟约 30 天才被记为可得；精度为日期级。
2. HY_CREDIT_SPREAD 的 ALFRED 历史版本仅从 2023-11 起可得，已按实际覆盖标记为 `partial_coverage`，不能用于 2015–2023 的历史检验。
3. USD_BROAD_INDEX 修订频繁，15,517 条观测中包含多版本，使用时必须按 `available_time` 取当时版本。
4. Yahoo 的 ETH 历史仅到 2017-11，且成交量为单一交易场所口径。
5. ETF AUM 从 2025-05 才有完整数据；ETF 净流入从 2024-01-11 开始，属于结构性新变量，不能向前补零。
6. Blockchain.com 图表没有官方发布时间，采用保守 T+1 可得时间，精度为日期级。
7. 稳定币供应是存量，变化不等同于交易所资金流入。
8. L3 注意力、ETH 使用、Dominance、市场广度尚未接入，不阻塞首批核心数据集。

## 6. 下一步

1. 在 v3 上完成“共同驱动 / 资本竞争”的正式检验；需要补充股票等传统风险资产数据，不能仅凭价格相关性推断资金迁移。
2. 如有 Kraken 完整历史文件，替换/补强 BTC、ETH 行情。
3. 将 L3 注意力与市场广度纳入后续批次。