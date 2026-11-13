# 交差审计 · m17253 / GAP-CAD-T2-SHIPD-5415（TensorData）

**审计单** m17270 ｜ **被审单** m17253（status=succeeded）｜ **裁判基准** `tensor_benchmark_cases`
｜ **裁定** L2（独立功能实现），未达 L3/L4 ｜ **verdict_by** board-audit

## ① 案例介绍

mission m17253 的目标是"现成金矿开采"：把 ShipD（Bagazinski & Ahmed 2023，30 000 条设计向量 × 45 参数，
附公开网格生成器）与 DTMB 5415（Zenodo 19222008，9 001×27 阻力/耐波数据库）两套现成几何数据资产接入
TensorData，并给出"几何可用性"门禁（而不是字节完整性校验）。

审计对象是**交差三件套是否真存在**：run_artifacts 文件、benchmark ref vs got 数值、repro_cmd 可执行；
以及报告六段是否齐备。审计方法是**独立重建执行路径**：不用交付方的数字，自己在 `/tmp` 副本里重跑、
自己写一份独立 STL 体积积分器重算、自己探测 ASCII/Binary 判型。

物理/几何基准（外部锚，来自交付工件 `geometry_gate.json` 的 documented_reference）：
DTMB 5415 Lpp=142.0 m，B=18.867 m，
T=6.157 m，Δ=8399.4 t，
模型比尺 24.825175。

## ② 怎么做的（审计流程）

1. 取证：`artifacts/GAP-CAD-T2-SHIPD-5415` 下 shipd/（qa_summary/qa_records/qa_per_hull）与 dtmb5415/
   （geometry_gate/surrogate_baseline/train_ready_manifest），加 `data/derived/shipd_stl`（76 个二进制 STL）。
2. 一致性：把 qa_records.json（100 条）与人工可读表 qa_per_hull.csv（73 行）逐条对齐。
3. 独立重算：用审计方自写的散度定理体积积分器（`struct` 直读 STL，不 import `tensordata`）重算
   20 条船的体积，与记录中的解析积分体积对照，并核对 sha256 与三角面数。
4. 独立重跑：在 `/tmp` 副本里按 manifest 的 repro_cmd 用同 seed 重跑 100 条船，比对 `sample_indices` 与全部统计量。
5. 缺陷探测：手写最小合法 ASCII 四面体 STL，直接调用交付的 `read_stl`；再跑交付的 pytest 套件（补齐
   `alembic.ini`，避免副本缺件误伤 migrations 测试）。
6. 落库：`tensor_benchmark_cases` 该 anchor 行数 = 0（**board 未登记基准**）。

## ③ 计算结果（程序化注入，零手抄）

| 项 | 数值 |
|---|---|
| ShipD pilot 规模 / 通过 | 100 条抽样 → 53 通过（53.00%），seed 20261113 |
| volume_full_rel_err mean / p95 / max | 8.575e-04 / 2.008e-03 / 5.458e-03 |
| volume_wl_rel_err mean / p95 / max | 6.885e-03 / 1.694e-02 / 1.356e-01 |
| beam_rel_err max | 2.463e-03 |
| depth_rel_err max | 5.766e-08 |
| cb（设计吃水）范围 | mean 0.4178，max 0.9053 |
| 审计独立重算体积（20 条船）最大相对差 | 4.114e-03；sha256 全对=True；面数全对=True |
| 独立重跑 100 条船 | n_passed=53，pass_rate=0.53，sample_indices 与统计量**逐位相同** |
| qa_records / qa_per_hull.csv 行数 | 100 / 73（差 27 = reconstruction_error 船） |
| naive CSV 通过率 vs 真值 | 72.60% vs **53.00%** |
| DTMB5415 设计空间几何门 | 100 配置 → 通过 45（45.00%），失败原因全为 `beam_rel_vs_baseline>0.02` |
| DTMB5415 ridge 基线（5 折，X=[9001, 27]） | Cw R²=0.037, 0.574, 0.331；9 目标最大 R²=0.767 |
| 交付单测 | pytest rc=1：红 = test_placeholder_mesh_is_rejected, test_closed_high_resolution_mesh_passes（共 2 个，全部集中在 test_hull_mesh_profile.py） |
| ASCII STL 探针 | ascii → fmt=`binary`, ok=False, err=`ValueError: binary STL size inconsistent with declared triangle count`；binary → ok=True |
| 落库状态 | 分支 `agent/m17253` head=`fe09270`，领先基线 0 个 commit，未提交/未跟踪项 13 |

## ④ 结果图

![fig1](figs/fig1_volume_selfconsistency.png)
*图 1 网格体积与解析积分体积的相对差分布（73 条有网格的船），红虚线=2% 门限。分布集中在 1e-3 量级，说明"网格重建"与"参数化解析积分"两条独立路径互相闭合。*

![fig2](figs/fig2_independent_volume.png)
*图 2 审计方独立重算体积 vs 记录中的解析积分体积（1:1 线）。8/8 船贴在 1:1 线上，最大相对差 4.11e-03——交付数字不是编的。*

![fig3](figs/fig3_population_gap.png)
*图 3 `qa_records.json`（100 条）与人工可读表 `qa_per_hull.csv`（73 行）的种群差：27 条 reconstruction_error 船在 CSV 中被静默丢弃。*

## ⑤ 注意点（踩到的坑 / 局限 / 适用范围）

- **交付定义缺陷（P1，功能性）**：`tensordata/geometry/stl.py:99 _detect_format` 先读 5 字节，
  `head == b"solid" and b"
" not in head` 对**所有 ASCII STL** 恒真（5 字节里不可能有换行），于是 ASCII 全部被判为 binary，
  接着 `_parse_binary` 以"size inconsistent with declared triangle count"报错。后果：hull-mesh 剖面**拒绝一切合法 ASCII STL**，
  而 mission result 把两个红灯归因为"合成网格构造缺陷"（归因错误，实际是读入层缺陷）。修复面很小（先读 80+4 字节再按长度判型）。
- **交付证据表缺陷（P2）**：`scripts/shipd_geometry_qa.py:316` `if "checks" not in r: continue` 让 CSV 丢掉重建失败的船，
  且表头无说明 → 拿着 CSV 算通过率会得到 **72.60%**，而真值是 **53.00%**。
- **未落库（P1，流程）**：分支 `agent/m17253` head=`fe09270` 与基线同点，13 项 M/??；
  GitHub 上不存在这批交付，`/root/tensor-ecosystem/TensorData` main 无 `tensordata/geometry`、无 `hull_mesh.py`。
- **规模局限**：只开采 100/30000 条 ShipD 船，ShipD 的 Cw 目标列未算（管线就绪）；DTMB5415 侧只做了设计空间几何门 +
  ridge"可学性下限"基线（R² 不是性能声明），没有阻力求解器对照。
- **适用范围**：hull-mesh 剖面的阈值（≥1000 面、y=0 对称）是船体取向的，直接套到非船几何会误判；DTMB5415 载荷是
  开放半船点云，闭合流形/块系数/吃水被交付方明确标为 NOT_MEASURABLE（这点是诚实且正确的）。

## ⑥ 误差判定（关键量 vs 基准，逐项）

| 关键量 | 基准来源 | 误差 | 是否 <3% |
|---|---|---|---|
| 网格体积（20 条船，审计独立重算） | 参数化解析积分体积 | max 4.114e-03 | **是** |
| volume_full_rel_err（100 条船） | 解析积分体积 | max 5.458e-03 | **是** |
| volume_wl_rel_err（100 条船） | 设计吃水以下解析积分 | max 1.356e-01（p95 1.694e-02） | **否**（max 超 3%，13.56%；p95 满足） |
| 主尺度 beam/depth（100 条船） | 参数化设计值 | max 2.463e-03 / 5.766e-08 | **是** |
| 复现性（100 条船重跑） | 交付记录 | sample_indices、check_statistics 逐位相同 | **是**（0 偏差） |
| board 登记基准（GAP-CAD-T2-SHIPD-5415） | `tensor_benchmark_cases` | 行数 = 0 | **无法判定**（无基准可比，故不申报 L4） |

**判定**：几何自洽性与复现性达标（<3%，甚至 1e-3），但 (a) `volume_wl` 尾部超 3%（个别船水线切割不稳），
(b) board 未给该 anchor 登记任何 benchmark case，因此本单**不存在**"got vs ref vs tolerance"三段式裁判输入，
L4（基准验证）不予认定；L3（系统集成）亦不认定——profile 在 registry 里接上了 QualityEngine，
但交付未提交、平台侧 `/quality-checks` 未实跑。**功能实质 = L2**。

## 裁定与建议

- **L2（confirmed 候选）**：真代码（STL 解析/体积与等深积分/绕向修复/剖面规则 383+328+52 行）+
  入口 + 可复现工件，审计独立重算与独立重跑均对上。
- 不认定 L3/L4/L5，理由见上表；`m17253` 的 succeeded 只覆盖"pilot 打通"，不覆盖"30 000 船开采"。
- **返修优先级**：① ASCII 判型缺陷（带 2 个红测）② CSV 静默丢行 ③ 提交落库 ④ 为 anchor 登记 benchmark case
  （否则任何同类单都不可能到 L4）⑤ 扩到 30 000 船的 Cw 开采。
