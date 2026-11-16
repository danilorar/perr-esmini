# 149 个 TASC 场景的漏检敏感性实验 / Dropout sensitivity across 149 TASC scenarios

## 实验范围与模型 / Experiment design and model

**中文。** 2026-11-13 的批量实验覆盖 7 个 Cut-in、110 个 Rear-end car–car 和 32 个 Rear-end car–cyclist。HiDrive 和 esmini 原生 AEB 在每个场景使用 seed 0–99，各跑 7 个漏检条件，共 208,600 次。每个场景和控制器另跑一次无漏检注入基准，共 298 次。两套批量均通过场景、条件和 seed 的完整性校验，失败数为 0。

**English.** The 2026-11-13 batch covered 7 cut-in, 110 rear-end car–car and 32 rear-end car–cyclist TASC scenarios. HiDrive and esmini native AEB each ran seeds 0–99 under seven dropout conditions per scenario, for 208,600 runs. One no-injection reference per scenario and controller added 298 runs. Exact scenario, condition and seed coverage was verified for both controllers, with zero failed runs.

| 条件 / Condition | 漏检概率设定 / Miss probability setting | 连续漏检平均时长设定 / Mean miss duration setting |
| --- | --- | --- |
| IID | 每个感知帧独立以 10% 漏检 / 10% per independent sensor frame | 由帧周期和概率决定 / Implied by frame period and probability (55.6 ms) |
| 固定 Markov / Fixed Markov | 10% 稳态漏检比例 / 10% stationary miss fraction | 0.1, 0.5, 1.0 s |
| 空间 Markov / Spatial Markov | 10% 基础漏检比例 / 10% base miss fraction | 0.1, 0.5, 1.0 s 基准值 / Reference values |

**中文。** 空间 Markov v1 按目标使用当前感知帧的中心距离、相对自车航向的方位角和上一感知帧的检测状态。超过 20 m 或绝对方位角 5° 后，局部稳态漏检比例分别每米增加 0.0025、每度增加 0.005，上限为 0.5。超过阈值也会同时降低进入漏检和恢复检出的概率，两项衰减系数分别为每米和每度 $\ln(2)/10$。因此，固定几何下的平均漏检时长可以超过表中的基准值。模型在目标列表层注入假阴性。完整公式、默认值和单次运行命令见[模型说明](DETECTION_SPATIAL_V1.md)。

**English.** Spatial Markov v1 uses each target's current centre-to-centre range, bearing relative to ego heading and previous sensor frame's detection state. Beyond 20 m or 5° absolute bearing, the local stationary miss fraction increases by 0.0025 per extra metre and 0.005 per extra degree, up to 0.5. Excess range and bearing also slow both entry into a miss and recovery, with exponential decay coefficients of $\ln(2)/10$ per metre and per degree, respectively. The mean miss duration at fixed geometry can therefore exceed the reference value in the table. The model injects false negatives at the object-list level. See the [model guide](DETECTION_SPATIAL_V1.md) for the equations, defaults and single-run command.

## 原生 AEB 场景适配与数据流 / Native AEB adaptation and data flow

**中文。** 旧场景适配器要求航向近似平行，并要求轨迹沿初始航向的投影单调前进。这项检查拒绝了 100 个场景，包括全部 7 个 Cut-in。实验运行器允许平面、直立轨迹改变航向，保留高度、俯仰和横滚检查。自车沿源场景的空间路径按弧长推进，AEB 输出控制自车减速和前进距离。目标继续按源场景的时序轨迹运动。这一改动让 149 个场景均通过运行预检。新旧运行器在原先支持的三个场景上，对 IID 和三档固定 Markov 的 12 次抽查均得到一致的真值、感知、控制、指标及回放文件。

**English.** The legacy adapter required near-parallel headings and monotonic progress projected along the initial heading. This check rejected 100 scenarios, including all seven cut-ins. The experiment runner accepts changes in heading on planar, upright trajectories and retains the height, pitch and roll checks. Ego follows the source path by arc length, with AEB controlling ego deceleration and distance travelled. The target follows the source timed trajectory. All 149 scenarios passed the updated runner's preflight. In three previously supported scenarios, 12 spot checks covering IID and all three fixed Markov settings yielded identical truth, perception, control, metric and replay files.

**中文。** 原生 AEB 是 esmini v3.8.1 ALKS R157SM 的 ReferenceDriver AEB 组件，使用 1.5 s TTC 参数和 8.3385 m/s² 制动减速度参数。理想传感器每 0.05 s 提供一帧目标列表。空间组使用源自仿真真值的目标几何调用同一个 Python 插件，只删除列表中被标记为漏检的目标。IID 和固定 Markov 沿用 C++ 漏检实现。控制器每 0.01 s 使用准确自车状态和缓存的感知列表，碰撞用仿真真值评估。HiDrive 通过 pipeline 桥接应用检测模型，使用该桥接的目标列表。

**English.** Native AEB is the ReferenceDriver AEB component of esmini v3.8.1 ALKS R157SM, configured with a 1.5 s TTC parameter and an 8.3385 m/s² braking deceleration parameter. The ideal sensor produces an object list every 0.05 s. In the spatial groups, the same Python plugin uses simulation geometry to select misses, and the runner deletes only flagged targets from the sensor list. IID and fixed Markov use the existing C++ dropout implementation. At each 0.01 s control step, the controller receives exact ego state and the cached observation list. Collision evaluation uses simulation truth. HiDrive applies the detection model to the object list provided by the pipeline bridge.

## 碰撞与实际漏检比例 / Collisions and observed miss fractions

**中文。** 下表排除 8 个在 $t=0$ 已接触的场景。每个控制器、每个漏检条件的碰撞率分母为 14,100。两套无漏检注入基准各保留 141 个场景。实际漏检比例为注入漏检帧数除以进入各自漏检模块的有效目标帧数。无注入的原生基准仍使用理想传感器的视场和量程。

**English.** The table excludes eight scenarios with contact at $t=0$. Each dropout condition has a collision-rate denominator of 14,100 per controller. Each no-injection reference retains 141 scenarios. Observed miss fractions divide injected misses by the eligible target frames entering each controller's dropout module. The no-injection native reference retains the ideal sensor's field of view and range.

| 条件 / Condition | HiDrive 碰撞 / Collisions | 原生 AEB 碰撞 / Native AEB collisions | HiDrive 实际漏检 / Observed misses | 原生 AEB 实际漏检 / Native AEB observed misses |
| --- | ---: | ---: | ---: | ---: |
| 无漏检注入 / No injection | 39/141 (27.66%) | 98/141 (69.50%) | — | — |
| IID | 4,019 (28.50%) | 9,843 (69.81%) | 9.98% | 9.96% |
| 固定 Markov / Fixed Markov 0.1 s | 4,123 (29.24%) | 9,873 (70.02%) | 10.05% | 10.18% |
| 固定 Markov / Fixed Markov 0.5 s | 4,553 (32.29%) | 10,010 (70.99%) | 11.29% | 11.38% |
| 固定 Markov / Fixed Markov 1.0 s | 4,829 (34.25%) | 10,108 (71.69%) | 12.24% | 12.11% |
| 空间 Markov / Spatial Markov 0.1 s | 4,124 (29.25%) | 9,876 (70.04%) | 13.95% | 11.96% |
| 空间 Markov / Spatial Markov 0.5 s | 4,639 (32.90%) | 10,027 (71.11%) | 15.11% | 13.02% |
| 空间 Markov / Spatial Markov 1.0 s | 4,904 (34.78%) | 10,127 (71.82%) | 15.87% | 13.70% |

**中文。** 两种 Markov 的碰撞率都随设定时长增加。空间 Markov 1.0 s 相对 IID 在 HiDrive 增加 885 次碰撞，在原生 AEB 增加 284 次，主要来自 Rear-end car–car（分别增加 722 次和 260 次）。从固定 Markov 换成同档 1.0 s 空间 Markov 时，HiDrive 有 220 个场景–seed 对仅空间组碰撞，145 对仅固定组碰撞。原生 AEB 对应为 49 对和 30 对。空间组的实际漏检比例也更高，因而观察到的差异同时包含漏检比例和时间连续性的影响。

**English.** For both controllers, collision rates rose as the nominal mean duration increased in each Markov model. Spatial Markov at 1.0 s produced 885 more HiDrive collisions and 284 more native AEB collisions than IID. Rear-end car–car contributed most of the increase, with 722 and 260 additional collisions, respectively. Comparing fixed and spatial Markov at 1.0 s on matched scenario–seed pairs, HiDrive had 220 spatial-only and 145 fixed-only collisions. Native AEB had 49 spatial-only and 30 fixed-only collisions. The spatial groups also had a higher observed miss fraction, so the difference combines the effects of miss prevalence and persistence.

## 解读范围 / Interpretation

- **Cut-in。** 原生 AEB 的 7 个 Cut-in 在全部条件下均为零理想传感器目标帧。2 个在 $t=0$ 即接触。其余 5 个在无注入基准的采样窗口内，目标参考点始终处于传感器前向 ±30° 视场外。每个原生 AEB 漏检条件均有 500/700 次碰撞，计入初始接触。HiDrive 每个漏检条件均有 700/700 次碰撞，无注入基准为 7/7。两套结果对这批 Cut-in 的漏检模型区分度有限。

  **Cut-in.** The ideal sensor produced zero target frames in all seven native AEB cut-ins under every condition. Two scenarios started in contact. In the other five, the target reference point stayed outside the forward ±30° field of view at sampled times in the no-injection reference. Each native AEB condition had 500/700 collisions including initial contacts. HiDrive had 700/700 in every dropout condition and 7/7 in the reference. Collision counts provide little discrimination among dropout models for these cut-ins.
- **场景质量。** 两套运行器均在 146 个场景记录道路末端几何长度警告，相关运行完成并计入汇总。32 个 Rear-end car–cyclist 样本沿用 TASC 分类，源场景中的目标类别均编码为 `car`。

  **Scenario quality.** Both runners logged an end-of-road geometry length warning in 146 scenarios. Those runs completed and are included. The 32 rear-end car–cyclist cases retain their TASC labels, and their target category in OpenSCENARIO is encoded as `car`.
- **比较口径。** 对漏检效应使用同一控制器、同一场景、同一 seed 的配对结果。HiDrive 与原生 AEB 的目标列表来源和无注入基准不同。参数是仿真假设，结果表示这批场景下的闭环敏感性。

  **Comparison scope.** Compare dropout conditions within a controller using matched scenarios and seeds. HiDrive and native AEB use different sources for their object lists and have different no-injection baselines. The parameters are simulation assumptions and the results describe closed-loop sensitivity in this scenario set.

## 运行记录 / Run records

**中文。** 此批实验基于提交 `0feeb56` 的模型实现和本地导入的 149 场景登记表。批量以 HiDrive 和原生 AEB 为运行对象。完整运行资产位于课程工作区的结果目录 `results/detection_all_149_100seeds.EvBhrf`，包括 `run_batch.py`、原生运行器、配置溯源和逐帧数据库。仓库中的三场景配置用于小批量运行。

**English.** The batch used the model implementation at commit `0feeb56` and the locally imported 149-scenario registry. The batch controllers were HiDrive and native AEB. The course workspace's `results/detection_all_149_100seeds.EvBhrf` directory holds the runner scripts, native runner, provenance records and frame-level databases. The repository's three-scenario grid supports smaller runs.

| 归档文件 / Archived file | 内容 / Contents |
| --- | --- |
| `overall_summary.csv`, `category_summary.csv`, `scenario_summary.csv` | 全场景、分类和逐场景汇总 / Overall, category and per-scenario summaries |
| `paired_comparison.csv` | 相同场景及 seed 的配对计数 / Counts for matched scenario–seed pairs |
| `all_runs.csv`, `no_injection_reference.csv` | 逐次漏检实验和无注入基准 / Individual dropout runs and no-injection references |
| `verification.json`, `native_parity.json`, `scenario_warnings.csv` | 覆盖校验、原生运行器抽查和道路警告 / Coverage, native runner parity and road warnings |
