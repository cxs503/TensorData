# PV 阶段3 试点：KCS EX1 预注册数据文件的逐列字段/单位验收（TensorData PV 链实跑）

- scenario_id: `pv-kcs-ex1-20261115-prereg-column-acceptance`
- usage_declaration: Real research-data acceptance workflow: the ship-performance platform's registered EX1/KCS prereg exports (13-variant resistance envelope + nominal Fn table) are accepted at column level by the TensorData PV chain before downstream use (CFD benchmarking, training-set admission, paper re-computation). Passing means: every numeric column is identified with a physically dimensioned unit and SI conversion factor, structure/axis/unit/range checks pass on the real bytes, and injected defects are detected. It does not mean the Holtrop-Mennen resistance values match towing-tank measurements.
- permission_basis: `internal_consent`
- product: `tensordata-physics-dataset-validator 0.2.0` (PV chain #7 foundation / #8 csv-validator / #9 unit-normalization + new column inference)
- reviewed/declared commit: `ce4a0d1661bdbd23420c506fecec3d3123cbf250`

## ① 案例介绍（物理背景 / 几何 / 参数）

被验收的对象是船舶总体性能平台 **EX1「水池锚定」战役** 的 KCS 预注册数据文件（`docs/prereg/ex1_kcs/`，已注册 v1、append-only）：Holtrop–Mennen 公式链在 Fn 网格上生成的**名义阻力/有效功率表**（`table_v1.csv`）与 **13 个变体包络**（`envelope_v1.csv`，用于自查任意 Fn 点的 min/max 由哪个变体给出）。这是真实科研数据文件，不是测试样例：验收它等于验收“平台产出的数据表能否被下游（CFD 对标 / 训练集准入 / 审稿复算）直接接手”。

物理背景：KCS（KRISO Container Ship）为公开标模，本包只用主尺度与船型系数作输入，阻力值由 Holtrop–Mennen (1982/1984) 公式链给出，属**盲预测注册**（不读取任何水池试验阻力值）。几何与假设参数（由 `params_v1.json` 程序化读取，零手抄）：

| 参数 | 值 |
|---|---|
| `case` | KCS |
| `version` | v1 |
| `reg_date` | 2026-11-01 |
| `geometry_inputs.Lpp` | 230.0 |
| `geometry_inputs.Lwl` | 232.5 |
| `geometry_inputs.B` | 32.2 |
| `geometry_inputs.T` | 10.8 |
| `geometry_inputs.D` | 19.0 |
| `geometry_inputs.volume` | 52030.0 |
| `geometry_inputs.Cb` | 0.6509 |
| `geometry_inputs.Cm` | 0.9849 |
| `geometry_inputs.Cwp` | 0.763 |
| `geometry_inputs.lcb` | -1.48 |
| `geometry_inputs.S_published` | 9424.0 |
| `assumptions.Abt` | 10.0 |
| `assumptions.hB` | 5.0 |
| `assumptions.At` | 0.0 |
| `assumptions.Cstern` | 0.0 |
| `assumptions.rudder_area` | 45.0 |
| `geometry_checks.Cb_reported` | 0.6509 |
| `geometry_checks.Cb_from_volume_Lpp` | 0.6504985947329991 |
| `geometry_checks.Cb_rel_dev` | 0.0006166926824411472 |
| `geometry_checks.Cb_from_volume_Lwl` | 0.6435039861874831 |
| `geometry_checks.Cp` | 0.660879277083968 |
| `geometry_checks.Cb_from_CpCm` | 0.6509 |
| `geometry_checks.L_over_nabla13` | 6.1608867749791125 |
| `geometry_checks.S_published` | 9424.0 |
| `geometry_checks.S_holtrop_formula` | 9108.65769594547 |
| `geometry_checks.L_R` | 70.54354707346765 |
| `geometry_checks.iE_deg` | 13.904320695720699 |
| `geometry_checks.L3_over_nabla` | 241.5544517586008 |
| `geometry_checks.B_over_L` | 0.138494623655914 |
| `geometry_checks.one_plus_k` | 1.1361724011759158 |
| `geometry_checks.CA` | 0.0003195429574984702 |
| `geometry_checks.rho` | 1025.0 |
| `geometry_checks.nu` | 1.19e-06 |
| `geometry_checks.g` | 9.80665 |
| `geometry_checks.knot` | 0.514444 |
| `water.rho` | 1025.0 |
| `water.nu` | 1.19e-06 |
| `water.temperature_C` | 15 |
| `md5_rule` | body = text after BODY-START newline; md5(body_utf8) |
| `python` | 3.11.6 (main, May  9 2024, 00:00:00) [GCC 12.3.0 20230508 (Anolis OS 12.3.0-2)] |

## ② 怎么做的（方法 / 流程 / 关键设置 / 工具链）

按 `TensorBench docs/SCENARIO_ACCEPTANCE_FRAMEWORK.md` §3 六步执行，本单覆盖 ①②③⑥，④⑤（独立复核、置 `scenario_validated`）由**他人**完成，本单禁止自审：

1. **① scenario 规格**：真实输入逐一钉 SHA-256（任务给定指纹），`permission_basis=internal_consent`；指纹不符即 honest-FAIL（脚本在第一步就 `return 2`）。
2. **② criteria_freeze**：验收判据先行写入 `criteria_freeze.json`，用 TensorBench `criteria.canonical_sha256` 同一口径（sort_keys / 无空白 / UTF-8）哈希，`frozen_at` 早于报告 `created_at`；运行中不得放宽。
3. **③ 逐列字段识别 + 单位判定**（本单补的缺口）：既有 PV 链（#8 `physics_csv`）只能验证**人工声明**的 profile，不能回答“这列是什么量、什么单位”。新增 `tensordata.quality.fields`：符号表 + **大小写敏感**单位后缀表 + 量纲一致性 + 量级合理性 + 跨列冗余五项证据，输出每列 `field/quantity/source_unit/canonical_unit/si_scale/confidence/basis`，可反向生成 physics profile 交回既有链复检。
4. **③ 质量检查实跑**：结构（`QualityEngine` tabular profile：解析/表头/列宽/缺格/重复行）、轴单调（`Fn` 严格递增）、单位（`unit_consistency`，含 SI 换算）、物理范围（`physical_bounds`，换算到 SI 后判定）。
5. **④-pre 负向实测**：副本注入 1 行物理越界值（Rt 取负）与 1 处单位错标（kN→knot，既做 profile 级也做列名级），要求 validator/识别器**必须检出**。
6. **⑥ 失败/未测记账**：未测项（独立复核、`scenario_validated`、模型精度对标）按 §5 字段格式写入 `failure_records.json`（category=gap），不升级为 pass。

关键设置：`unknown_rate` 上限 10%；跨列速度一致性与功率恒等式容差 1e-6；隐含密度离散度 <1e-3；密度窗口 [900,1100] kg/m³。工具链：Python 3.11.6、TensorData 质量引擎、matplotlib（PNG 内嵌）。

## ③ 计算结果（全部程序化注入）

### 3.1 逐列字段 / 单位判定

**envelope_v1.csv** — 数值列 12，识别 12，unknown 0.0%（列出：无），单位冲突 无。

| 列 | 字段 | 物理量 | 源单位 | 规范 SI 单位 | SI 换算系数 | 置信度 |
|---|---|---|---|---|---|---|
| `Fn` | Fn | Froude number | 1 | 1 | 1 | medium |
| `V_kn` | V | ship speed | knot | m/s | 0.5144444444 | high |
| `Re` | Re | Reynolds number | 1 | 1 | 1 | medium |
| `CF` | CF | friction resistance coefficient | 1 | 1 | 1 | medium |
| `one_plus_k` | one_plus_k | form factor (1+k) | 1 | 1 | 1 | medium |
| `CR` | CR | residuary resistance coefficient | 1 | 1 | 1 | medium |
| `CA` | CA | correlation allowance coefficient | 1 | 1 | 1 | medium |
| `Ct` | Ct | total resistance coefficient | 1 | 1 | 1 | medium |
| `Rt_kN` | Rt | total resistance | kn | N | 1000 | high |
| `Pe_kW` | Pe | effective power | kw | W | 1000 | high |
| `iE_deg` | iE | waterline entrance half-angle | deg | rad | 0.01745329252 | high |
| `S` | S | wetted surface area | m2 | m2 | 1 | medium |

**table_v1.csv** — 数值列 17，识别 17，unknown 0.0%（列出：无），单位冲突 无。

| 列 | 字段 | 物理量 | 源单位 | 规范 SI 单位 | SI 换算系数 | 置信度 |
|---|---|---|---|---|---|---|
| `Fn` | Fn | Froude number | 1 | 1 | 1 | medium |
| `V_kn` | V | ship speed | knot | m/s | 0.5144444444 | high |
| `V_ms` | V | ship speed | m/s | m/s | 1 | high |
| `Re` | Re | Reynolds number | 1 | 1 | 1 | medium |
| `CF` | CF | friction resistance coefficient | 1 | 1 | 1 | medium |
| `one_plus_k` | one_plus_k | form factor (1+k) | 1 | 1 | 1 | medium |
| `CR` | CR | residuary resistance coefficient | 1 | 1 | 1 | medium |
| `CA` | CA | correlation allowance coefficient | 1 | 1 | 1 | medium |
| `Ct` | Ct | total resistance coefficient | 1 | 1 | 1 | medium |
| `Rt_kN` | Rt | total resistance | kn | N | 1000 | high |
| `Pe_kW` | Pe | effective power | kw | W | 1000 | high |
| `RF_kN` | Rf | friction resistance | kn | N | 1000 | high |
| `Rw_kN` | Rw | wave resistance | kn | N | 1000 | high |
| `RB_kN` | RB | bulbous-bow resistance | kn | N | 1000 | high |
| `Rtr_kN` | Rtr | transom resistance | kn | N | 1000 | high |
| `RA_kN` | RA | air resistance | kn | N | 1000 | high |
| `S` | S | wetted surface area | m2 | m2 | 1 | medium |

### 3.2 质量检查状态（真实输入）

| 文件 | 结构检查 | physics 校验 overall | 检查项/状态 |
|---|---|---|---|
| `envelope_v1.csv` | passed | passed | dataset.finite_values=passed; dataset.units_resolvable=passed; dataset.physical_bounds=passed |
| `table_v1.csv` | passed | passed | dataset.finite_values=passed; dataset.units_resolvable=passed; dataset.physical_bounds=passed; dataset.axis_monotonic.Fn=passed |

覆盖的检查类别（实跑）：physical_bounds, structure, unit_consistency。

### 3.3 物理自洽（独立于 profile 的交叉验证）

| 量 | 数值 |
|---|---|
| 由 Rt = 0.5·ρ·Ct·S·V² 反演的密度均值 | 1025.0000 kg/m³ |
| 反演密度相对离散度（全 Fn 网格） | 2.218e-16 |
| Pe = Rt·V 最大相对偏差 | 0.000e+00 |
| V_kn×0.514444 与 V_ms 最大相对偏差 | 8.639e-07 |

### 3.4 负向实测

| 注入 | 检出 | validator overall | 关键状态 |
|---|---|---|---|
| out_of_range_value | 检出 | failed | failed |
| unit_mislabel_in_profile | 检出 | failed | failed |
| unit_mislabel_in_column_name | 检出 | n/a | n/a |
| unknown_rate_gate | 检出 | n/a | 0.11764705882352941 |

## ④ 结果图

- `figs/fig1_column_identification.png` — Per-column field identification with the SI conversion factor (envelope_v1.csv). Blue = identified with resolved unit; the kN/knot case discrimination is what makes Rt_kN -> N (1e3) and V_kn -> m/s (0.5144) correct.
- `figs/fig2_physics_closure.png` — Left: nominal Rt against the registered 13-variant envelope. Right: water density implied by Rt = 0.5 rho Ct S V^2 — a constant density across the Froude grid is independent proof that the kN/knot unit resolution is right.

## ⑤ 注意点（踩过的坑 / 局限 / 适用范围）

1. **`_kN` vs `_kn` 大小写陷阱**：`Rt_kN` 是千牛（力），`V_kn` 是节（速度）。既有 `units.normalize_unit` 会把两者都规范化成 `kn`（力），若按后缀直接查表，速度列会被判成力。本实现**在规范化之前**按大小写敏感后缀表分派，节只以 `knot`/`kt` 进入注册表，并保留 `kn`=千牛的既有语义（不改既有行为，加测试锁定）。
2. **`_ms` 后缀**：本平台导出约定为 m/s，不是毫秒；按 m/s 解释并在 basis 中留痕。
3. **符号歧义**：`S`（湿表面积 vs 秒/盐度）、`B`（船宽 vs 其他）、`T`（吃水 vs 推力）属于单字母歧义符号，仅精确大小写匹配，置信度降为 medium 并给出 basis，不冒充 high。
4. **无后缀列只能给规范单位假设**（basis `canonical_unit_assumed`，置信度 medium）：如 `Fn`、`CF` 无量纲，`S` 未标单位。这类“假设”必须由领域 owner 复核，不能当作已声明。
5. **未知率闸门是硬闸**：17 列里改名 2 列即 11.8% > 10%，闸门失败——说明阈值在当前列数下很紧，列数少的表更容易触发。
6. **范围判据依赖单位可归一**（既有 #9 语义）：单位不可换算时 `physical_bounds` 给 inconclusive，绝不 passed；负向实测 #2 正是这一路径。
7. **适用范围**：CSV 适配器一次性载入内存（大表需流式）；只覆盖本域字段表，其他学科（耐波/操纵/结构）字段需扩 `FIELDS` 并给出各自的物理范围依据。
8. **本单不做的事**：不改 `scenario_validated`、不自审、不评估 Holtrop–Mennen 与水池试验的精度（那是模型验收，不是数据验收）。

## ⑥ 误差判定（逐项，显式回答“是否 <3%”）

| 关键量 | 基准 | 实测偏差 | <3%？ |
|---|---|---|---|
| `V_kn→m/s` 换算 | `V_ms`（同表冗余列） | 8.639e-07 相对 | 是（0.00009%） |
| `Pe` 有效功率 | `Rt·V` 定义式 | 0.000e+00 相对 | 是（0.00000%） |
| 隐含密度恒定性 | 常数密度假设 | 2.218e-16 相对 | 是（0.00000%） |
| Cb（体积/Lpp 反算 vs 报告值） | 报告值 0.6509 | 6.167e-04 相对 | 是（0.0617%） |
| 湿表面积 S（Holtrop 公式 vs 公开值 9424 m²） | 公开值 | -3.35% 相对 | **否（>3%，但 <15% 可接受判据）** |
| 模型阻力 vs 水池试验 | 无（本单不含试验基线） | — | **无法判定**：本单验收数据文件质量，模型精度须另立 EFD 对标场景（误差 >15% 不可接受） |

说明：几何量 S 的 Holtrop 公式值相对公开值偏差超过 3%（该偏差在 prereg 包内即为已知假设，属几何经验式固有误差，判据允许 <15%），其余**有基准**的数据质量量误差均远小于 3%；**无基准**项（Holtrop–Mennen 阻力 vs 实测）如实声明“未测”，不写成通过；scenario 级验收裁定为 `inconclusive`（待独立复核）。

## 六维价值记录（成本实数）

| 维度 | 记录 |
|---|---|
| 场景价值 | 真实科研数据文件（KCS EX1 预注册包）逐列验收，可直接交下游/审稿复算 |
| 能力增量 | 新增 `tensordata.quality.fields`：字段识别 + 单位判定 + SI 系数 + 未知率闸门 |
| 证据强度 | 输入指纹；两种独立物理闭合；4 类检查实跑；4 例负向注入全检出 |
| 成本（墙钟） | 3.45 s |
| 成本（CPU） | 1.88 s；读取 30228 B / 126 行 / 2 文件 |
| 未测/欠账 | 独立复核（④）、`scenario_validated`（⑤）、模型精度对标（⑥ 已记账） |

---

机器可读：`artifacts/pv-pilot/ex1_kcs/pilot_report.json`（overall_status=`inconclusive`）、`criteria_freeze.json`、`column_report.json`、`metrics.json`、`negative_cases.json`、`evidence_manifest.json`、`failure_records.json`；TensorBench 收集器 bundle 见 `runs/pv-pilot-ex1-kcs/collector/` 与 `collector_summary.json`（作者不自造收集器 bundle）。