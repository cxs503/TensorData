# TensorData 质量审计报告（A+B）— mission m14503

- **仓库**：`cxs503/TensorData`，worktree `/root/tp-agent/work/m14503`，分支 `agent/m14503`
- **审计基线**：`main` HEAD = `fe09270608e49b675e36e81185959fde781defeb`（2026-11-10 22:25 +0800，"docs: document repository license and asset scope"），仓库共 119 次提交、4,667 行受跟踪代码/文档
- **审计者**：audit2-ab（独立审计席位，本单不修改任何产品代码）
- **审计日期**：2026-11-11
- **方法**：① 全仓静态盘点（git ls-files + 逐文件精读核心模块）；② **真跑**——自带独立运行时夹具（非仓内测试）驱动真实 FastAPI 应用 35 步；库级探针验证引擎 5 条不变量；并发竞态复现器 15 轮×12 线程；SDK 对真实 uvicorn 服务端到端；Alembic 迁移与 ORM 零漂移比对；③ 与**独立实现的正解（oracle）**逐项对照，而不是与仓库自测互相印证。
- **本报告所有数字都来自 `artifacts/` 下的 JSON 工件或 `file:line` 指针，无手抄。**

---

## 0. 结论摘要（一句话）

TensorData 是一个**小而真实的**数据资产治理服务：4 个核心能力（资产/工件注册与内容寻址、质量引擎、数据集不可变清单+准入闸门、溯源与血缘）**全部是真实可执行代码**，我独立复算/独立复现全部通过，定级 **L3（系统集成）**，测试套件 29 项全绿。但它有 **3 个实质性缺口**：① 准入闸门与内容下载都**信任数据库元数据而不复核真实字节**（事后篡改可被准入并原样下发，同时 ETag 仍声明原始 sha256）；② 数据集准入**不检查权利状态**（`unknown`/`review_required` 资产可入清单，只有 `prohibited` 被拦）；③ 并发同内容上传会因 `UNIQUE(asset_id,sha256)` 冲突泄漏 **HTTP 500**。此外 `docs/quality/scientific-profiles.md`（133 行，含 4 大领域 19 条规则清单）是**纯设计文档、零实现**（运行时 `profile=timeseries` 直接 422），是本赛季最典型的"报告≠功能"膨胀项。

---

## ① 资产盘点（分类清单 + 行数）

统计口径：`git ls-files | xargs wc -l`（LICENSE 191 行不计入），总计 4,667 行。

| 分类 | 文件 | 行数 | 说明 |
|---|---|---|---|
| **核心算法/功能模块** | `tensordata/quality/{base,engine,registry}.py` | 384 | 质量引擎骨架：单遍流式度量（SHA-256/尺寸）、`RuleContext` 惰性 memo 扫描、规则崩溃隔离、profile 注册表 |
| 核心算法（规则库） | `tensordata/quality/rules/{csv_structure,integrity}.py` | 256 | 10 条真实规则：`file.non_empty` / `size_matches_metadata` / `sha256_matches_metadata`；`tabular.header_present` / `rows_present` / `row_width` / `missing_cells` / `duplicate_rows` / `csv_parseable` / `csv_summary` |
| 核心算法（profile） | `tensordata/quality/profiles/{general,tabular}.py` | 66 | 2 个 profile 组合（general 3 条 / tabular 10 条） |
| **API 接口层** | `tensordata/main.py` + `schemas.py` | 774 | **16 个 `/api/v1` 端点** + `/health`；请求/响应 pydantic 契约 |
| **持久化** | `models.py` + `db.py` + `config.py` | 160 | 6 张表（data_assets / data_artifacts / datasets / dataset_versions / provenance_records / quality_reports） |
| **迁移** | `migrations/**` + `alembic.ini` | 248 | 0001_initial / 0002_quality_reports，含 downgrade |
| **SDK** | `client.py` + `__init__.py` | 108 | 同步 httpx 客户端，9 个方法 |
| **测试代码** | `tests/*.py`（6 文件） | 844 | 29 个用例（test_quality_engine 13 / test_quality_reliability 6 / test_agent_provenance_schema 4 / test_api 3 / test_client 2 / test_migrations 1） |
| **文档报告** | `docs/**`、README、AGENTS、LICENSE_SCOPE、rights/README | 1,069 | 12 篇 md，**行数最大单一类别** |
| **治理工具（非服务）** | `scripts/check_rights_manifests.py` + `rights/manifest.schema.json` + 模板 | 390 | 离线权利清单校验器（真实逻辑，但**未接入 API**） |
| **CI / 打包** | `.github/workflows/*.yml`、pyproject、Dockerfile | 107 | 2 条流水线（pytest+ruff；权利清单校验） |
| **占位实现（stub/TODO/空壳）** | — | **0** | 全仓 `grep TODO|FIXME|NotImplemented|...` 仅命中 `db.py:11` 的 `class Base: pass`（ORM declarative base，正常写法）与 `base.py:160` 的 `@abstractmethod ...`（抽象方法签名），**无死骨架、无硬编码假数据** |
| **重复实现** | 见下 | ~40 | ① tabular profile 重新实例化 general 的 3 条规则而非复用 `GENERAL_PROFILE.rules`（`profiles/tabular.py:27-31` 与 `profiles/general.py:11-15` 逻辑重复）；② 允许的 profile 名单在三处重复定义：`schemas.py:158` Literal、`quality/registry.py` 注册表、`main.py:362-367` 闸门推导 |
| **未接入模块** | 见下 | ~108 + 390 | ① `tensordata/client.py`（SDK）在仓内无任何调用方/无真实服务端测试（test_client 全部用 `httpx.MockTransport`）；② `scripts/check_rights_manifests.py` + `rights/schema` 只在 CI 跑，`tensordata/` 运行时代码零引用（`grep rights/manifests tensordata/` = 0 命中）→ 权利清单与资产库是**两套互不连通的体系**；③ `quality.measure_file` / `QUALITY_RULESET_VERSION` 仅导出无调用 |

---

## ② 功能真实性审查（六问表）

六问：Q1 代码入口？ Q2 真执行计算？ Q3 接入主程序？ Q4 实际输入输出？ Q5 完整运行案例？ Q6 独立基准验证？

| 能力 | Q1 入口 | Q2 真计算 | Q3 接入 | Q4 输入→输出 | Q5 运行案例 | Q6 独立验证 | 判定 |
|---|---|---|---|---|---|---|---|
| **质量引擎（流式度量+规则执行）** | `quality/engine.py:57-63`（measure_file）、`:96-113`（规则循环+崩溃隔离） | ✅ 真读字节、真算 SHA-256/CSV 统计 | ✅ `main.py:57` `QUALITY_ENGINE` → `POST /artifacts/{id}/quality-checks` (`main.py:245-300`) | CSV/二进制 → report(status/findings/summary) | ✅ `artifacts/audit_runtime_m14503.json` S4/S5/S6/S16 | ✅ 与审计方**独立 CSV 实现**逐项相等（S4/S5 match=true）；8.4 MiB 分块哈希 = hashlib（engine probe）；20 万行重复数 199,000 全对（`exact=true`） | **真功能** |
| **CSV 结构规则（10 条）** | `quality/rules/csv_structure.py:36-163`、`rules/integrity.py:13-64` | ✅ 单遍解析 + 12 字节行摘要做重复判定（`base.py:95-123`） | ✅ 由 tabular profile 组合 | 见上 | ✅ S5 脏样本命中 3 条 finding（row_width/missing_cells/duplicate_rows，计数 1/1/1 与 oracle 全等） | ✅ oracle 对照 + 规模探针（`peak_rss_delta_mb=0.0`，5.3 万行/s） | **真功能** |
| **规则崩溃隔离（D2）** | `engine.py:100-110` | ✅ 抛出规则的异常被转成 `rule.execution_failed` error finding | ✅ | 崩溃规则 → report=failed | ✅ `artifacts/audit_engine_probe_m14503.json["crashing_rule"]` = failed | ✅ 审计方注入 `RuntimeError` 规则验证（非仓内测试自证） | **真功能** |
| **资产/工件注册 + 内容寻址** | `main.py:74-217`（create/list/get/upload/list/download） | ✅ 分块写盘 + SHA-256 + `storage_root/sha[:2]/sha` 布局 + 路径逃逸防护（`main.py:222-224`） | ✅ 服务主路径 | 文件字节 → 工件元数据+内容回读 | ✅ S2/S3（sha256 与独立计算一致、回读字节一致、幂等命中原 id） | ✅ 下载字节 vs 独立 hashlib 比对通过 | **真功能** |
| **数据集不可变清单 + 准入闸门** | `main.py:305-424`（版本创建）、`:341-395`（闸门） | ✅ 规范 JSON（sort_keys+紧凑分隔符）→ SHA-256；闸门 4 项检查 | ✅ | 成员集 → 不可变 manifest + digest | ✅ S8/S13/S14 五条闸门路径 | ✅ 审计方**独立复算** canonical digest 与返回值全等（`digest_reproducible=true`） | **真功能（有缺口，见 §0②）** |
| **溯源记录 + actor 归属** | `main.py:449-511` | ✅ 引用存在性校验、校验和比对、`_actor_provenance` 保留字防护、agent 三要素必填（`schemas.py:127-137`） | ✅ | 活动 → 记录 | ✅ S10 六条路径（含 422/409/422） | ✅ 运行时逐条验证（含反例） | **真功能** |
| **血缘图遍历** | `main.py:515-581` | ✅ 迭代不动点闭包（3 节点链 + 外部引用） | ✅ | 工件 id → 节点/活动/外部引用 | ✅ S11：3 artifacts / 2 activities / 1 external ref | ✅ 审计方构造链路后核对节点数 | **真功能（无分页，见 roadmap 自认）** |
| **Python SDK** | `tensordata/client.py` 全文件 | ✅ 真 httpx 调用 + 结构化错误 | ⚠️ 仓内**无调用方**；仓内测试全是 MockTransport 假服务 | 方法调用 → HTTP | ✅ 审计方**起了真 uvicorn** 跑通 6 步（`artifacts/audit_sdk_live_m14503.json`） | ✅ 真实服务端到端（首次得到这一证据） | **真功能，集成证据本次补齐**；且缺 download/get/list 方法 |
| **权利清单校验器** | `scripts/check_rights_manifests.py` | ✅ 真校验（status 枚举、approved 的证据链 8 项） | ❌ **未接入 API/数据库** | manifest json → OK/ERROR 列表 | ✅ 审计方注入坏清单 → 10 条 ERROR、exit=1 | ✅ 负向实测 | **真工具，未集成** |
| **Alembic 迁移** | `migrations/versions/000{1,2}*.py` | ✅ 真实建表 | ✅ 容器入口 `alembic upgrade head` | schema | ✅ `test_migrations` + 审计方 `alembic upgrade head`/`check` | ✅ **零漂移**：`alembic check` = "No new upgrade operations detected"，ORM↔DB 列集合完全一致 | **真功能** |
| **scientific profiles（timeseries/scientific_field/mesh/multimodal）** | `docs/quality/scientific-profiles.md` | ❌ 无代码 | ❌ | ❌ | ❌ | ❌ 运行时 `profile="timeseries"` → **422 literal_error**（S7） | **非功能（L0 文档）** |

---

## ③ 成熟度判级（逐模块落表）

| # | 模块 / scope | 级别 | 判据与证据指针 |
|---|---|---|---|
| 1 | `quality-engine`（引擎+10 规则+2 profile） | **L3** | 真算法 + 接入服务的 `POST .../quality-checks`；独立 oracle 逐项相等（S4/S5）、分块哈希=hashlib、20 万行 199,000 重复全对、崩溃规则不得通过、未知 profile 抛错。**L4 未成立**：无基准语料、无假阳/假阴率、无与工业校验器（如 frictionless/great-expectations）的对照误差分析 |
| 2 | `asset-artifact-registry`（资产/工件/内容寻址/下载） | **L3** | S2/S3 全绿；sha256 与独立计算一致；路径逃逸防护；幂等命中原 id。缺陷：并发 500（见 P3） |
| 3 | `dataset-version-gate`（不可变清单+准入闸门） | **L3** | 独立复算 digest 全等；5 条闸门路径实测（缺报告/错 profile/失败报告/prohibited → 422，通过 → 201）。缺口：不复核字节（P1）、不看权利（P2） |
| 4 | `provenance-lineage` | **L3** | 记录 6 条路径 + 3 节点链遍历实测；actor 三要素强制 |
| 5 | `sdk-client` | **L3**（本次审计补齐集成证据） | 对**真实 uvicorn** 端到端跑通（`audit_sdk_live_m14503.json`）；仓内原证据仅 MockTransport |
| 6 | `persistence-migrations` | **L3** | upgrade/downgrade 往返 + `alembic check` 零漂移 + ORM 列集合一致。PostgreSQL 路径**未验证**（本机 psycopg3 在 loong64 上报 TypeError，环境限制，见 §4） |
| 7 | `test-suite`（验证基础设施） | **L2** | 29 项全绿、断言 invariants 而非仅执行（如 `test_engine_package_does_not_import_fastapi`、迁移往返）；但**缺口 4 类**：事后篡改准入、并发上传、上传大小上限、分页边界 |
| 8 | `rights-manifest-validator`（脚本+schema+CI） | **L2** | 真校验逻辑 + 负向 10 ERROR；与资产库零连通 → 不构成系统集成 |
| 9 | `governance-docs`（12 篇 md） | **L0** | 文档成果，不计功能；内含 2 处过时陈述（见 P8） |
| 10 | `scientific-profiles`（timeseries/field/mesh/multimodal 设计） | **L0** | 纯设计文档，代码零行，运行时 422（S7） |
| 11 | `docker-packaging` | **L1** | Dockerfile 存在但本机无 docker（`docker unavailable`），**未执行**，不判 L2 |

**L 分布**：L3 = 6 项 · L2 = 2 项 · L1 = 1 项 · L0 = 2 项 · L4/L5 = **0**。
**可验证功能交付（L≥2）= 8/11（73%）**；若把"文档当交付"剔除，本仓**没有任何一项达到 L4**——这与仓库自我定位（README "Not production-ready"、roadmap 大量 `[ ]`）是**一致且诚实的**，审计未发现虚报功能等级的声明。

---

## ④ Top 问题（严重度排序，含复现）

### P1【高·完整性】闸门与下载都信任元数据，事后篡改不被发现，且响应头"声称作假"
- 机理：闸门只比对 `QualityReport.artifact_sha256 == DataArtifact.sha256`（`main.py:368-378`），两者都是上传时写入的静态元数据；`download_artifact` 也直接 `FileResponse` 磁盘文件并声明 `ETag`/`X-Content-SHA256 = artifact.sha256`（`main.py:228`），**从不校验实际字节**。
- 复现（`artifacts/audit_runtime_m14503.json` → `S9_tamper_after_pass`）：干净 CSV → tabular passed → 直接把磁盘文件覆盖为 `a,b,c\n9,9,9\n` → 再次创建 dataset version 得 **201 准入**；再下载得**篡改后的字节**，而 `X-Content-SHA256` 仍为原始摘要（`content_matches_header_digest=false`）。
- 影响：本平台的核心承诺（字节 ↔ sha256 ↔ 报告）只在**上传瞬间**成立。对"可复现科研数据"场景是**结构性失效**：报告声称的数据与磁盘上的数据可以长期不一致而无任何告警。
- 缓解建议（不属本单实施范围）：闸门与下载前流式重算 SHA-256（8.4 MiB 实测 <1 s 量级），或在 manifest 中记录 `mtime/inode` 并对下载做校验后才发头。

### P2【高·治理】数据集准入零权利检查：`unknown` / `review_required` 资产可入清单
- 机理：闸门只拦 `rights_status == "prohibited"`（`main.py:357-361`）。`AssetCreate` 的 Literal 又**禁止**生产者直接给 `approved`（`schemas.py:20`），而全仓**没有任何审批端点**把 `review_required` 提升为 `approved`；`lifecycle_state` 也恒为 `quarantine`（无状态迁移端点）。
- 复现：`S8_gate_admits_passing` → 资产权利状态 `review_required`、生命周期 `quarantine`，dataset version 返回 **201**，manifest 里 `rights_status_at_snapshot="review_required"`、`lifecycle_state_at_snapshot="quarantine"`。
- 影响：`dataset version` 是"质量合格快照"，**不是**"权利已清"。README 对此诚实披露，但下游（TensorPhysics/TensorLBM 训练集）若把 201 当"可训练"会越权使用。建议闸门增 `rights_status in {approved}` 且 `lifecycle_state == published`（与 roadmap M2 的 `[ ]` 项对齐）。

### P3【中·可用性】并发同内容上传泄漏 HTTP 500（未处理 UNIQUE 冲突）
- 机理：`upload_artifact` 是 check-then-insert：先 `SELECT` 同 (asset,sha256)（`main.py:156-171`），再 `INSERT`（`main.py:173`），唯一的 `UNIQUE(asset_id, sha256)` 冲突（`models.py:35`）未被捕获。
- 复现（`artifacts/audit_race_m14503.json`，15 轮×12 线程）：多轮出现 1–3 个 **500**（本轮共 **11 次 / 180 请求**，5 轮出现失败），失败为 `sqlalchemy.exc.IntegrityError`；数据未损坏（最终该资产仍只有 1 行工件）。
- 影响：Agent 批量并发登记同一数据集时随机 5xx；无幂等键，重试语义不明确。
- 建议：`except IntegrityError` → 回滚后重查并返回既有工件（200）。

### P4【中·策略】99.5% 重复行仍判 `passed`
- 复现（`audit_engine_probe_m14503.json`）：20 万行里 199,000 行是重复行，`duplicate_rows` 属 warning 级 → `report_status="passed"` → 可入数据集。
- 影响：质量闸门的"passing"被重定义成"无 error"，退化数据可合法进入训练清单。建议 profile 增加阈值参数（如 duplicate_ratio > 0.1 → error），且参数需快照进 summary（该设计已在 `scientific-profiles.md` 提出问题 #3，未实现）。

### P5【中·契约】SDK 覆盖不全且仓内仅假服务验证
- `TensorDataClient` 只有 9 个方法，缺 `get_asset` / `list_assets` / `list_datasets` / `get_dataset_version` / `list_provenance` / **下载工件内容**（`sdk_has_download=false`）；`tests/test_client.py` 两个用例全部对 `httpx.MockTransport` 假服务断言 → 契约漂移零防护（本次审计用真 uvicorn 补齐，见 `audit_sdk_live_m14503.json`）。

### P6【低·契约】幂等上传返回 201
去重命中既有工件时仍返回 `201 Created`（S3），客户端无法区分"新建"与"复用"；建议 200 或 409。

### P7【低·安全】API key 明文等值比较、单一全局身份、`/health` 暴露版本
`main.py:64` 用 `!=` 比较（非常量时间）；无按 Agent 的作用域（roadmap M2 `[ ]` 已认领）。风险低（内网单租户），但审计需要留痕。

### P8【低·文档】同一份文档自相矛盾
`docs/api/quickstart.md:101` 与 `:144` 仍写"lineage 遍历 / 可执行质量报告未实现"，而同文档 `:152-182` 已给出两功能的调用示例，代码也真实存在（S11/S12）。建议删改过时段落，避免审计与用户误判。

---

## ⑤ "曾声称为功能、实为文档/测试/预设"的膨胀清单

| 项 | 声称形态 | 实况 | 证据 | 处理 |
|---|---|---|---|---|
| `scientific-profiles`（timeseries / scientific_field / mesh / multimodal） | 133 行文档含 4 领域 19 条规则 ID、扫描契约（`SeriesScan`/`FieldScan`/`MeshScan`/`MultimodalCheckContext`）、试点排序 | **0 行实现**。注册表只有 `general`/`tabular`（`registry.py:21-27`）；`QualityCheckCreate.profile` Literal 只有两值（`schemas.py:158`） | 运行时 `profile="timeseries"` → **422**（`S7_profile_timeseries_not_supported`）；`UnknownProfileError` 消息列出 `['general','tabular']` | 如实记 **L0**；文档已自带 "proposed/draft rule inventories" 措辞，若任何战役报告把它计为"科学数据质量能力"即属膨胀 |
| `rights` 治理闭环 | `rights/README.md` + `manifest.schema.json`(253 行) + 校验脚本 + CI 工作流，读起来像"权利治理已就绪" | 校验器真实有效（负向 10 ERROR），但**与 API/DB 完全不通**：`grep` 显示 `tensordata/` 里零引用；API 侧无审批端点 | `scripts/check_rights_manifests.py` 负向实测；S2 自审批被拒 422 但也没有合法审批通道 | 记 **L2 工具 / 未集成**；"证据支撑的权利批准"= roadmap `[ ]`，勿计入功能 |
| `Python SDK for Agent workflows`（README 首屏） | 读作"Agent 侧全流程 SDK" | 真实现，但覆盖 9/16 端点，缺下载与全部读接口；仓内证据仅假服务 | `audit_sdk_live_m14503.json["sdk_methods"]` | 记 **L3**（本次补真服务证据），但 README 宜标注"子集" |
| `SQLite/PostgreSQL URL 支持`（roadmap M1 `[x]`） | 勾选完成 | 仅 SQLite 被我跑通；PostgreSQL 路径在本机无法验证（psycopg3 在 loong64 上 `TypeError: cannot use a string pattern on a bytes-like object`，卡在 SQLAlchemy 取服务器版本号） | 本报告 §4；`migrations/env.py:16` | 记 **部分已验证**，建议在 x86 CI 加 PG 服务后再打勾 |
| `Docker-based local development`（roadmap `[x]`） | 勾选完成 | Dockerfile 存在，本机无 docker，**未执行** | `docker info` → unavailable | 记 **L1**，未验证即不改判 |
| 测试"覆盖质量闸门" | 29 测试全绿 | 绿是真绿，但**四类关键反例无测试**：事后篡改准入、并发上传、上传大小上限、分页边界（本次由审计侧夹具覆盖） | `grep` 测试清单 vs `audit_runtime` S9/S15/S17/S2 | 记 **L2**，建议把审计夹具中的 4 个场景回灌成仓内回归测试 |

> 反向核查：未发现"硬编码期望值假装算法"的模块——所有质量数字都由真实字节计算，且与审计方独立实现对得上；未发现 `NotImplementedError` 空壳。

---

## ⑥ 复现与工件索引

| 工件 | 内容 | 复现命令（worktree 内） |
|---|---|---|
| `artifacts/audit_runtime_m14503.py` + `.json` | 35 步真实 API 场景（含 18 项约定状态矩阵） | `python artifacts/audit_runtime_m14503.py` |
| `artifacts/audit_engine_probe_m14503.py` + `.json` | 库级 5 条不变量：分块哈希、崩溃隔离、warning 语义、未知 profile、20 万行规模/内存 | `python artifacts/audit_engine_probe_m14503.py` |
| `artifacts/repro_upload_race.py` + `audit_race_m14503.json` | 并发上传 500 复现（15×12） | `python artifacts/repro_upload_race.py` |
| `artifacts/audit_sdk_live_m14503.py` + `.json` | SDK ↔ 真 uvicorn 端到端 | `python artifacts/audit_sdk_live_m14503.py` |
| `artifacts/make_figures_m14503.py` + `fig{1..5}_*.png` | 本报告全部图（数字直读上述 JSON） | `python artifacts/make_figures_m14503.py` |
| 仓内测试 | 29 用例 | `TENSORDATA_API_KEY=ci-test-key pytest -q` → **29 passed**；`ruff check .` → clean |

**未执行项（honest）**：
1. Docker 构建/运行（本机无 docker daemon）。
2. PostgreSQL 后端端到端（psycopg3/loong64 环境缺陷，非本仓代码问题；建议 x86 CI 补 PG job）。
3. Python 3.12（CI 目标版本）——本机 3.11.6 全绿，3.12 未跑。
4. 真实科研数据（船体 CSV/场数据）——仓内与环境中均无真实载荷，全部使用合成样本；因此"领域有效性"无从判定，本报告不下领域结论。
5. 未做渗透测试/负载测试（仅并发 12 线程量级）。

---

## ⑦ 判级落表（已写入 `tensor_maturity_verdicts`，`verdict_by='audit2-ab'`, `mission_id=14503`）

见 `artifacts/verdicts_m14503.json`（11 行，与上表一一对应，evidence 均含 file:line 或运行工件指针）。