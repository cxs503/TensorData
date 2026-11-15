# m22061 PROD-PV 试点独立审查报告

**审查者**: qwen3.6-plus (independent_qa)  
**被审分支**: agent/m22061 (TensorData)  
**被审 commit**: 18559035a5d8eb108055619f36191523e1a9364d  
**审查日期**: 2026-11-16  
**依据**: TensorBench `docs/SCENARIO_ACCEPTANCE_FRAMEWORK.md` §3.4 六查  

---

## ① 案例介绍（物理背景/几何/参数表）

本试点针对 **KCS (KRISO Container Ship)** 预注册数据包（EX1 阶段）进行列级数据质量验收。KCS 是国际船模试验池会议 (ITTC) 的标准船模，用于阻力/推进性能基准研究。

**输入文件**（SHA-256 钉扎，permission_basis=internal_consent）：

| 文件 | SHA-256 | 行数 | 数值列 |
|---|---|---|---|
| `envelope_v1.csv` | `c6b14731…8bfcd` | 117 (13 变体 × 9 Fn 点) | 12 |
| `table_v1.csv` | `9126738f…b6ab56` | 9 (单变体 Fn 网格) | 17 |

**关键几何参数**（来自 envelope）：Lpp=230m, B=32.2m, T=10.8m, Cb=0.6509, S=9424 m², ρ=1025 kg/m³, ν=1.19e-6 m²/s。

**验收链**：TensorData PV #7 (foundation) → #8 (physics CSV validator) → #9 (unit normalization) → 新增 `tensordata.quality.fields` (列字段/单位自动识别)。

---

## ② 怎么做的（方法/流程/关键设置/工具链）

按 SCENARIO_ACCEPTANCE_FRAMEWORK.md §3 六步执行，本审查覆盖全部六查：

1. **① artifact_identity**：独立用 `sha256sum` 重算两 CSV 文件指纹，与任务给定指纹比对；重算 evidence_manifest.json 中 20 个交付物的 SHA-256。
2. **② criteria_frozen_before_run**：从 `criteria_freeze.json` 提取 criteria 对象，用 TensorBench `canonical_sha256` 约定（sort_keys / 无空白 / UTF-8）重算哈希，验证与存储值一致；确认 `frozen_at` 早于报告 `created_at`。
3. **③ evidence_traceability**：抽样 10 列（V_kn, Rt_kN, Pe_kW, iE_deg, V_ms, RF_kN, Fn, CF, S, one_plus_k），逐列验证 `basis` 数组可检索、`si_scale` 数值可手算复现。
4. **④ independent_rerun**：在审查者环境中完整重跑 `python3 scripts/pv_pilot_ex1_kcs.py`，验证 11/11 判据通过、overall=inconclusive（正确——作者不自签）。
5. **⑤ failure_record**：核对 `failure_records.json` 含 3 条 gap 记录；4 例负向注入（物理越界、profile 单位错标、列名单位错标、未知率闸门）全部检出。
6. **⑥ regression_scope**：TensorData 全量 pytest 96 项 0 fail。

**工具链**：Python 3.11.6, pytest 9.2.0, TensorData quality engine, matplotlib (Agg backend)。

---

## ③ 计算结果（全部程序化注入）

### 3.1 六查逐项结果

| 六查项 | 判定 | 关键证据 |
|---|---|---|
| ① artifact_identity | **pass** | 2 CSV 指纹匹配；20 交付物 SHA-256 全验证通过 |
| ② criteria_frozen_before_run | **pass** | criteria_sha256 重算匹配；frozen_at < created_at |
| ③ evidence_traceability | **pass** | 10 列抽样 basis 可检索；si_scale 来源可追溯 |
| ④ independent_rerun | **pass** | 11/11 判据通过；29 数值列 100% 识别；unknown=0% |
| ⑤ failure_record | **pass** | 3 gap 记录如实；4 负向注入全检出 |
| ⑥ regression_scope | **pass** | pytest 96 passed, 0 failed |

### 3.2 逐列字段/单位判定（抽样验证）

| 列 | 字段 | 源单位 | SI 单位 | si_scale | 置信度 | basis |
|---|---|---|---|---|---|---|
| V_kn | V | knot | m/s | 0.5144444444 | high | symbol_table, unit_suffix:kn, magnitude, cross_column |
| Rt_kN | Rt | kn | N | 1000.0 | high | symbol_table, unit_suffix:kN, magnitude |
| Pe_kW | Pe | kw | W | 1000.0 | high | symbol_table, unit_suffix:kW, magnitude |
| iE_deg | iE | deg | rad | 0.01745329252 | high | symbol_table, unit_suffix:deg, magnitude |
| V_ms | V | m/s | m/s | 1.0 | high | symbol_table, unit_suffix:ms, magnitude, cross_column |
| Fn | Fn | 1 | 1 | 1.0 | medium | symbol_table, canonical_unit_assumed, magnitude |
| CF | CF | 1 | 1 | 1.0 | medium | symbol_table, canonical_unit_assumed, magnitude |
| S | S | m2 | m2 | 1.0 | medium | symbol_table, canonical_unit_assumed, magnitude |
| RF_kN | Rf | kn | N | 1000.0 | high | symbol_table, unit_suffix:kN, magnitude |
| one_plus_k | one_plus_k | 1 | 1 | 1.0 | medium | symbol_table, canonical_unit_assumed, magnitude |

### 3.3 物理自洽交叉验证

| 量 | 数值 | 判定 |
|---|---|---|
| 反演密度均值 | 1025.0000 kg/m³ | 在 [900, 1100] 窗口内 |
| 密度相对离散度 | 2.22e-16 | ≤ 1e-3 ✓ |
| Pe = Rt·V 最大相对偏差 | 0.000e+00 | ≤ 1e-6 ✓ |
| V_kn→m/s 与 V_ms 最大相对偏差 | 8.64e-07 | ≤ 1e-6 ✓ |

### 3.4 负向注入检出记录

| 注入类型 | 检出 | validator overall | 关键状态 |
|---|---|---|---|
| out_of_range_value (Rt_kN 取负) | ✓ | failed | physical_bounds=failed |
| unit_mislabel_in_profile (Rt_kN: kn→knot) | ✓ | failed | units=failed, bounds=inconclusive |
| unit_mislabel_in_column_name (Rt_kN→Rt_kn) | ✓ | n/a | unit_conflict: force vs velocity |
| unknown_rate_gate (2/17 列改名) | ✓ | n/a | unknown_rate=0.1176 > 0.1 |

### 3.5 质量检查状态

| 文件 | 结构 | 有限值 | 单位可解 | 物理范围 | 轴单调 |
|---|---|---|---|---|---|
| envelope_v1.csv | passed | passed | passed | passed | — |
| table_v1.csv | passed | passed | passed | passed | passed (Fn) |

---

## ④ 结果图

- **fig1_column_identification.png** — 每列字段识别与 SI 换算系数柱状图（envelope_v1.csv）。蓝色=已识别且单位已解析；kN/knot 大小写区分是 Rt_kN→N (1e3) 和 V_kn→m/s (0.5144) 正确的关键。
- **fig2_physics_closure.png** — 左：标称 Rt 与 13 变体 envelope 对比；右：由 Rt = 0.5·ρ·Ct·S·V² 反演的水密度——Fn 网格上密度恒定是 kN/knot 单位解析正确的独立证明。

---

## ⑤ 注意点（踩过的坑/局限/适用范围）

1. **`_kN` vs `_kn` 大小写陷阱**：`Rt_kN` 是千牛（力），`V_kn` 是节（速度）。实现中在规范化之前按大小写敏感后缀表分派，正确处理了这一歧义。审查确认：`_UNIT_SUFFIXES` 字典中 `"kN": "kn"` (力) 和 `"kn": "knot"` (速度) 是两条独立条目，不会冲突。
2. **负向#2 的 inconclusive 语义**：当 Rt_kN 的单位被错标为 knot 时，`units_resolvable` 返回 failed（量纲不兼容），而 `physical_bounds` 返回 **inconclusive**（不是 passed）。这是 #9 修复的正确行为——单位不可换算时绝不给 passed。
3. **S 的 Holtrop 公式偏差**：-3.35% 超过 3% 阈值但在 <15% 可接受范围内。这是几何经验公式的固有误差，已如实记录为 honest limitation。
4. **无 EFD 基线**：本试点验收数据文件质量，不涉及模型阻力与水池试验的精度对标。
5. **scenario_validated 未设置**：作者正确遵守了不自签的规则，overall_status=inconclusive。本审查通过后，该状态可由平台更新。

---

## ⑥ 误差判定（逐项，显式回答"是否 <3%"）

| 关键量 | 基准 | 实测偏差 | <3%？ |
|---|---|---|---|
| V_kn→m/s 换算 | V_ms（同表冗余列） | 8.64e-07 相对 | **是**（0.00009%） |
| Pe 有效功率 | Rt·V 定义式 | 0.000e+00 相对 | **是**（0.00000%） |
| 隐含密度恒定性 | 常数密度假设 | 2.22e-16 相对 | **是**（0.00000%） |
| Cb（体积/Lpp 反算 vs 报告值） | 报告值 0.6509 | 6.17e-04 相对 | **是**（0.0617%） |
| 湿表面积 S（Holtrop vs 公开值 9424 m²） | 公开值 | -3.35% 相对 | **否**（>3%，但 <15% 可接受） |
| 模型阻力 vs 水池试验 | 无（本单不含试验基线） | — | **无法判定**：本单验收数据文件质量 |

---

## 审查结论

**verdict: pass**

六查全部通过，无阻塞条件。作者实现正确、证据完整、负向测试覆盖充分、回归范围无退化。`scenario_validated` 可由平台在收到本审查回执后设置为 `true`。

### 缺陷清单（非阻塞建议）

| 严重度 | 问题 | 建议 |
|---|---|---|
| low | `failure_records.json` 中 `evidence_refs` 的 SHA-256 是运行中间态的哈希（markdown 重写前），与最终文件哈希不同 | 可在 finalize 阶段刷新这些引用哈希 |
| low | TensorBench collector 在分支未推送时缺少 `commit.sha` 和 `pull_request` 字段 | 属平台侧限制，已在 failure_records 中记账 |
| info | 单字母符号（S, B, T）置信度为 medium，需领域 owner 复核 | 已在 pilot report 注意点中声明 |

---

*审查回执: `artifacts/pv-pilot/ex1_kcs/review_receipt.json`*  
*审查报告: `docs/reviews/m22061-PV-REVIEW.md`*
