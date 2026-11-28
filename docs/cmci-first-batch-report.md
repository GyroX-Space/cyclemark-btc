# CMCI 第一批真实数据接入报告 v0.1

运行日期：2026-11-28  
方案依据：《CMCI 第一批真实数据接入计划 v0.1》  
数据库：`data/cmci/cmci.db`（迁移 v6）

## 1. 本轮完成情况

| 批次 | 内容 | 状态 |
|---|---|---|
| D1 | FRED/ALFRED 宏观数据（10 项） | 连接器与登记已完成，**待 `FRED_API_KEY` 后执行** |
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
| L1 全部 10 项 | — | — | 0 | 等待 FRED API Key |

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

- 数据集：`CMCI-CORE-2015`，版本 v2，状态 `sealed`
- 分区：
  - `training`：2015-01-01 – 2019-09-30
  - `identification`：2020-01-01 – 2022-09-30
  - `validation`：2023-01-01 – 2026-11-28
  - 相邻分区隔离期 90 天
- 分区哈希：`1b471f06…41cea0a`
- 回放时点：2018-06-01（14,070 行）、2021-06-01（29,071 行）、2024-06-01（45,667 行），均按 `available_time` 还原
- 质量审计：0 违规；前视审计：503 项检查、0 违规

注：v1 因首版分区窗口未留足隔离期而放弃，未封存；v2 为当前有效版本。

## 5. 已知限制

1. L1 宏观数据尚未接入，因此当前数据集不含宏观层，不能开始任务二的正式检验。无 Key 的 `fredgraph.csv` 不返回历史 vintage（`vintage_date` 参数被忽略），无法替代 ALFRED。
2. Yahoo 的 ETH 历史仅到 2017-11，且成交量为单一交易场所口径。
3. ETF AUM 从 2025-05 才有完整数据；ETF 净流入从 2024-01-11 开始，属于结构性新变量，不能向前补零。
4. Blockchain.com 图表没有官方发布时间，采用保守 T+1 可得时间，精度为日期级。
5. 稳定币供应是存量，变化不等同于交易所资金流入。
6. L3 注意力、ETH 使用、Dominance、市场广度尚未接入，不阻塞首批核心数据集。

## 6. 下一步

1. 提供 FRED API Key，执行 D1 并生成包含 L1 的 v3 数据集。
2. 如有 Kraken 完整历史文件，替换/补强 BTC、ETH 行情。
3. 在 v3 上开始任务二的三类关系检验与任务三的 BTC 周期底表。