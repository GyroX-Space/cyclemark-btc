# CMCI 技术设计 v0.1

| 项目 | 内容 |
| --- | --- |
| 适用需求 | CMCI-DATA-01 v0.1、CMCI 独立研究项目总纲 v0.1 |
| 文档性质 | 编码前技术设计（对应需求书第十六节） |
| 版本 | v0.1 |
| 状态 | 已确认，作为 P0-1 起各批次实现依据 |

本设计只回答“如何实现”，不改变需求中的时间真实性、用途隔离、历史可追溯与 append-only 约束。若实现与需求冲突，以需求为准并回写本文件。

## 1. 数据库选型与核心实体关系

| 项目 | 决策 |
| --- | --- |
| 语言 | Python 3.11+ |
| 存储 | SQLite（标准库 `sqlite3`，WAL 模式），单文件 `data/cmci/cmci.db` |
| 访问层 | 自建轻量仓储层 `src/cmci/`，不引入 ORM |
| 时间存储 | 统一 `TEXT`，ISO-8601 UTC，形如 `2024-01-31T00:00:00Z` |
| 迁移 | `schema_migrations` 表 + 幂等 DDL；每批次新增编号脚本 |

选择理由：第一阶段为历史研究数据，量级在百万行级；SQLite 支持事务、部分索引、触发器，可满足 append-only 与回放要求，且不引入运维负担。仓储层与方言相关 SQL 集中在 `db.py`，后续迁移 PostgreSQL 时只替换该层与 DDL 类型。

核心实体（P0-1 建立，其余批次增量）：

```text
data_sources ──< indicator_sources >── indicators ──< indicator_versions
                                            │
                                    operation_logs（全局追加日志）

后续批次：ingestion_jobs → raw_records → observations → observation_revisions
          research_projects → research_datasets → dataset_versions → dataset_members
          replay_jobs / source_snapshots / data_quality_checks / audit_jobs / audit_results
```

关系约束：

- `indicators.indicator_code` 全局唯一，创建后不可修改（改代码即新指标）。
- `indicator_sources` 记录主/备来源与生效区间；同一指标同一时刻最多一个启用的主来源（部分唯一索引）。
- 来源切换通过关闭旧映射（写 `effective_to_utc`）并新增映射完成，不覆盖历史。

## 2. 原始数据与标准化数据存储

| 层 | 方案 |
| --- | --- |
| 原始数据 | `raw_records` 保存元数据、`content_hash`、`payload`（文本/JSON）与 `payload_path` |
| 大文件 | 超过 256 KB 的原始响应写入 `data/cmci/raw/<YYYY>/<MM>/<batch_id>/`，表中只存相对路径与哈希 |
| 幂等 | `(source_id, indicator_id, content_hash)` 唯一，重复接入识别为 duplicate，不覆盖 |
| 标准化 | `observations` 每条观测一行，`revision_id` 指向 `observation_revisions` 链 |
| 修订 | 不 UPDATE 旧值；新增 `revision_id` 更大的记录，旧记录保留 |

原始层只追加：应用层不提供 UPDATE/DELETE，数据库触发器拒绝修改 `raw_records` 的业务列。

## 3. 时间字段与历史版本

标准化观测必须同时具备四个时间：

| 字段 | 含义 |
| --- | --- |
| `observation_period_start` / `observation_period_end` | 数据描述的时间区间 |
| `release_time` | 来源发布该数据的时间 |
| `available_time` | CMCI 系统实际取得该数据的时间（回放唯一依据） |
| `vintage_time` | 该版本形成/发布的时间 |

规则：

- `available_time` 由系统写入时间确定，不允许人工改写为更早时间。
- 来源未提供 `release_time` 或 `vintage_time` 时，写 `NULL` 并在 `time_precision_status` 标记 `partial` / `assumed`，不得自行编造。
- 指标字典与观测均保留 `timezone`（来源时区）与 UTC 存储值。
- 修订形成版本链：同一 `(indicator_id, observation_period)` 下，`vintage_time` 递增；查询“某时点版本”取 `available_time <= T` 中最新 `vintage_time`。
- `indicator_versions`、`observation_revisions`、`operation_logs` 由触发器禁止 UPDATE/DELETE。

### 3.1 已知未来事件

`known_future_events` 独立建表：`event_type`、`event_known_time`、`event_effective_time`、`event_source`、`known_future_event=1`。回放时单独读取，禁止与价格、成交量等未来结果混表。

## 4. L5 三分区与 embargo 校验

分区登记在 `dataset_members`：`(dataset_version_id, indicator_id, usage_partition, time_start, time_end, embargo_before, embargo_after, partition_version)`。embargo 单位为天，登记在成员上；L1–L4 成员使用 `not_applicable`，L5 成员只能使用 `training` / `identification` / `validation`（数据库触发器与 `ResearchDatasetService` 双重校验）。

校验算法（P0-3 已实现，`src/cmci/datasets.py`）：

1. 同一 `dataset_version` 内取同一 `indicator_id` 的所有成员。
2. 对任意两条分区不同的成员，比较区间：重叠即冲突；相邻时要求间隔不小于 `max(前一段.embargo_after, 后一段.embargo_before)` 天。该规则比“仅 identification/validation”更严格，同时阻止训练区间与识别区间泄漏。
3. 冲突即拒绝写入，并返回冲突对、重叠区间与需要的 embargo 天数（`PartitionConflictError.conflicts`）。
4. 版本封存使用 `dataset_versions.status='sealed'` + `sealed_at_utc`（不再单独维护 `locked` 标志）。封存后成员行不可增删改（触发器强制），分区修改必须新建 `dataset_version`；旧版本标为 `superseded`，新版本记录 `replaces_version_id` 与 `change_reason`，并置 `invalidates_independent_validation=1`，明确原验证集失去独立验证资格。
5. 所有分区变更写入 `operation_logs`；封存时保存成员集合的确定性 `partition_hash` 快照。
6. `dataset_members` 为 append-only；封存版本禁止新增成员由数据库触发器兜底，服务层先抛出可读错误。

指标字典层面强制：`layer='L5'` 的指标必须有非空 `usage_partition_policy`，由数据库 CHECK 约束与仓储层双重校验。

## 5. 历史回放查询逻辑

给定 `T`、数据集版本、指标集合：

```sql
-- 每个 (indicator_id, observation_period) 取 T 时刻可得的最高版本
SELECT o.*
FROM observations o
JOIN (
  SELECT indicator_id, observation_period_start, observation_period_end,
         MAX(vintage_time) AS vintage
  FROM observations
  WHERE indicator_id IN (...)
    AND available_time <= :T
  GROUP BY indicator_id, observation_period_start, observation_period_end
) latest
  ON o.indicator_id = latest.indicator_id
 AND o.observation_period_start = latest.observation_period_start
 AND o.observation_period_end = latest.observation_period_end
 AND o.vintage_time = latest.vintage
WHERE o.available_time <= :T;
```

回放输出写入 `replay_jobs`，包含 `replay_result_hash`：对结果按 `(indicator_id, period, vintage, value, source_id)` 排序后规范化 JSON 做 SHA-256，保证相同输入可复现。

`known_future_events` 不进入上述查询，单独返回并标注 `known_future_event=true`。

索引：`(indicator_id, available_time)`、`(indicator_id, observation_period_start)`、`(available_time, vintage_time)`。

## 6. 数据接入任务调度

- 每次接入生成 `ingestion_jobs` 记录（`job_id`、来源、指标、时间范围、条数统计、状态、错误日志）。
- 调度方式：Linux `cron`（项目既定原则：不使用 GitHub Actions 执行业务操作），入口脚本 `scripts/cmci_ingest.py`。
- 任务幂等：以 `(source_id, indicator_id, content_hash)` 去重；重复运行不重复写入。
- 失败重试：单任务最多重试 3 次，退避后置 `failed`，不影响其他指标任务。
- 禁止无新信息写入：来源返回内容哈希未变时记录 `no_change`，不产生新观测版本。

## 7. 凭证与原始文件安全

- API 凭证只从环境变量读取（`.env` 已被 git 忽略），日志与报告中一律脱敏。
- 凭证不写入 `data_sources` 普通字段；`data_sources.auth_type` 只记录认证方式，不记录密钥。
- 原始文件目录权限限制为运行账户，站点与静态目录不映射该路径。
- 导出接口不返回凭证、内部路径或完整原始 payload，除非显式审计导出。

## 8. 审计报告实现

- 审计任务 `audit_jobs` 预登记：时间范围、抽样数 `N`、抽样种子、审计方案版本。
- 抽样使用固定种子 + 可复现随机数，抽样时点列表一并保存。
- 逐时点执行回放，检查每条输入记录的 `available_time`、`vintage_time`、`revision_id`。
- 违规分三类：未来数据（`available_time > T`）、事后修订值（版本晚于 T）、未来市场结果混入。
- 输出 `audit_results`：`checked_record_count`、`violation_count`、`violation_details`、`audit_result ∈ {passed, failed, inconclusive}`，并附报告哈希。
- 任何无法解释的违规即 `failed`；审计人独立于数据构建者，签名与时间入档。

## 9. 数据量与性能初步估算

| 项目 | 估算 |
| --- | --- |
| 指标数 | 第一阶段 150–250 个 |
| 观测行数 | 200 指标 × 10 年日频 ≈ 73 万；加宏观月/季频与衍生数据，上限按 500 万行设计 |
| 回放查询 | 单指标 10 年日频约 3650 行，索引下毫秒级 |
| 原始文件 | 首批数据源预计 < 2 GB |
| 结论 | SQLite 足够；当观测行数 > 2000 万或出现并发写入需求时迁移 PostgreSQL |

## 10. 批次实施与验收映射

| 批次 | 本设计对应章节 | 验收映射（需求书第十五节） |
| --- | --- | --- |
| P0-1 | 1、3、4（字典侧） | A 全部；C 部分 |
| P0-2 | 2、3、6 | B 全部；C 全部 |
| P0-3 | 4 | D 全部 |
| P0-4 | 5 | E 全部 |
| P0-5 | 8、9 | F 全部；G 全部 |

## 11. 决策记录

| 编号 | 决策 | 理由 |
| --- | --- | --- |
| D-01 | 第一阶段使用 SQLite，不引入 ORM | 零外部依赖、可移植、满足回放性能 |
| D-02 | `indicator_code` 创建后不可变 | 保证历史引用稳定，变更即为新指标 |
| D-03 | 不自动填充缺失值，不自动插值 | 需求 7.3 硬约束 |
| D-04 | 分区冲突在写入时拒绝，而非事后报告 | 防止污染已登记研究数据集 |
| D-05 | 调度使用服务器 cron，不使用 GitHub Actions | 项目既定运维原则 |