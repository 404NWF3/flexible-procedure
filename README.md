# Flexline · 柔性生产线决策仿真

基于 **SimPy** 复现《案例二十二：多品种小批量柔性生产线调度优化》，采用“工件 → 工位 → 单台机床”结构，提供可重复实验、原始记录和中文 HTML 面板。模型时间统一为**分钟**。

## 直接运行

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。运行时仅依赖 SimPy；HTML 不使用 CDN、外部字体或前端构建工具。

```bash
uv sync
uv run soft-procedure serve
```

浏览器打开 **http://127.0.0.1:8765**。首次启动计算新版任务书的 4 个核心方案 × 10 次重复；“配置与运行”会真实调用 Python/SimPy，完成后同时更新图表与 `outputs/`。仅监听本机地址。按 `Ctrl+C` 停止。

只生成可离线打开的 HTML：

```bash
uv run soft-procedure experiments --scenario-set core --replications 10 --seed 42
# 如需保留原有五组对照：
uv run soft-procedure experiments --scenario-set current --replications 10 --seed 42
open outputs/dashboard.html   # macOS；其他系统直接用浏览器打开此文件
```

离线 HTML 可以切换方案、查看图表、筛选工位、播放产线状态并导出数据；重新计算需要本地服务。不要把 HTML 里的回放当成新一轮实验。

单次运行与自定义参数：

```bash
uv run soft-procedure run --scenario baseline --seed 42 --output outputs/single
uv run soft-procedure experiments --config examples/custom.json --replications 10 --output outputs/custom
uv run soft-procedure serve --port 8766
uv run python -m unittest discover -s tests -v
```

没有 uv 时，也可在 Python 虚拟环境中 `python -m pip install -e .`，再运行 `soft-procedure serve`。

## SUFE CLI 校园工具

[sufe-cli](https://github.com/ChengJiale150/sufe-cli) `0.7.8` 已作为项目开发依赖安装，版本记录在 `pyproject.toml` 和 `uv.lock`。在本项目目录执行：

```bash
uv sync --locked
uv run sufe --version

# 在新环境中安装所需浏览器（当前环境已安装）
uv run python -m playwright install chromium

# 首次使用由本人完成登录，推荐选择 manual 浏览器登录
uv run sufe auth

# 登录后查看课程
uv run sufe canvas course list
```

四个 Agent Skills 位于 `.agents/skills/`：`sufe-base`、`sufe-canvas`、`sufe-score`、`sufe-lclibrary`。技能来自上游提交 `156c3ad544a0a87d929e9e5dc03b57a70a0c62f7`，其中 `sufe-base` 补充了本项目的 uv 命令与检查约定；其余内容保持上游原样。

上游 `sufe install` 会向用户全局技能目录写入文件，因此本项目采用独立安装浏览器和项目技能的方式。`uv run sufe doctor` 也检查全局技能目录，可能报告全局技能缺失；应另核对本项目的 `.agents/skills/`。浏览器与登录状态仍需正常。登录配置由 CLI 保存在用户目录 `~/.sufe-cli/`。

## 代码组织

```text
src/soft_procedure/
├── config.py             # 路线、产品比例、参数校验与明确的建模假设
├── randomness.py         # 稳定随机流；按工件编号和工序绑定加工样本
├── policies.py           # FIFO、同类优先、超时优先
├── model/
│   ├── job.py            # 工件及逐工序时间记录
│   ├── station.py        # 有限缓冲、待入队请求、原子派工
│   ├── machine.py        # 单台机床换模、加工、维修、占机阻塞
│   ├── source.py         # 外生批次到达与独立投料
│   └── simulation.py     # 装配环境、连接路线、运行一次
├── metrics.py            # 时间积分、未完成样本、守恒检查
├── economics.py          # 完工收入、运行成本、增量投资与简单回收期
├── experiments.py        # 核心方案与对照方案、配对重复、95% t 区间
├── export.py             # JSON、CSV 与自包含 HTML 导出
├── server.py             # 本地 GET /api/results、POST /api/run
├── cli.py                # 命令行入口
└── web/                  # HTML 模板、CSS 与原生 JavaScript
tests/                    # 手算契约、随机复现、接口与导出测试
examples/custom.json      # 只覆盖需要变动的配置
analysis.ipynb            # 读取逐轮结果与重新核算的可选分析本
outputs/                  # 已生成的面板与实验记录
docs/
├── case22_parameter_contract.md  # Arena/SimPy统一参数契约
├── case22_economic_accounting.md # 运行费、设备折旧、回收期和口径待确认项
├── case22_simio_preliminary_run_analysis_20261023.md # 新机器状态截图的初步解释
├── case22_project_status_20261023.md # 仓库资料索引与项目进度
├── case22_comprehensive_review_20261023.md # Simio材料与优化结果综合审阅
└── case22_arena_repair_log.md    # Arena修复登记与验收条件
```

Python 调用接口：

```python
from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.experiments import run_core_experiments, run_experiments

result = run_simulation(SimulationConfig(), seed=42)
print(result["summary"])

suite = run_core_experiments(SimulationConfig(), replications=10, seed=42)
```

`Station.put(job)` 只在工件真正进入缓冲后触发；`Station.request_job(machine)` 在完成原子分配后返回工件。`Machine` 在交接事件成功前一直占机。`Simulation._transfer` 唯一负责推进工序索引和登记成品。

## 案例参数

| 产品 | 比例 | 售价 / 元每件 | 路线（加工均值 / min） |
|---|---:|---:|---|
| P1 | 30% | 200 | M1(5) → M2(8) → M3(6) → M4(4) → M5(3) |
| P2 | 25% | 180 | M1(4) → M3(7) → M4(5) → M5(6) |
| P3 | 25% | 250 | M2(6) → M3(5) → M5(8) |
| P4 | 20% | 300 | M1(3) → M4(9) → M5(4) |

M1–M5 的机床数为 `2 / 1 / 2 / 1 / 2`。加工时长为正态分布，标准差为均值的 10%；非正样本重新抽样。到达间隔 `EXPO(10)`，批量为离散均匀 `5…20`，每工位缓冲 50 件。不同产品换模 15 分钟。MTBF 6000 分钟，维修 `EXPO(240)`。观察 2400 分钟，默认 10 次重复，种子 42–51。

文档补充了 **50 万元/台**的机床购置成本和 **100 元/h** 的运行成本。默认运行成本仅按**每台机床实际加工与换模时间**计费，维修、阻塞与空闲均不计费。各台机床的计费时长相加后乘以费率，成本随实际工作量变化。

## 成本与收益

经济核算复用原有完工事件与状态时间，不改变到达、加工、故障、换模、阻塞或调度规则。主界面的“成本与收益”页展示产品收入、成本计算、核心方案经营贡献和 M4 投资回收分析；“配置与运行”可修改四种售价、购置单价、运行费率和计费口径。

- **销售收入**：`Σ(各产品窗口内成品数 × 该产品售价)`。假设完工即全部售出；在制品、线外待投料不确认收入。使用实际产出结构，不用到达比例估算收入。
- **运行成本**：默认 `Σ(各机床加工分钟数 + 换模分钟数) / 60 × operating_cost_per_hour`，维修、阻塞与空闲不计费。模型内部时间为分钟，核算时除以 60；未结束的加工/换模只计至观察截止。
- **经营贡献**：`销售收入 − 运行成本`。未提供材料、人工、库存持有、额外维修费、折旧、税费等数据，因而不能当作完整净利润。
- **设备价值**：`配置机床数 × machine_purchase_cost`，单独披露。基准现有机床视为已购置，不在本期经营贡献中重复扣除。
- **新增投资**：`相对当前基准新增的机床数 × 购置单价`。默认 M4 扩容为 500,000 元。
- **简单回收期**：`新增投资 / 配对平均经营贡献增量`，单位为“个观察期”；再乘 `horizon / 60` 可得累计工作小时。仅在投资与贡献增量均为正时计算。增量非正显示“无法回收”，无新增投资显示“无需新增购机”。区间跨 0 或仅一次重复时保留方向未确认提示。
- **首期增量现金**：`配对平均经营贡献增量 − 新增购机款`，假设成品收入与运行费均在当期收付。未将全部设备购置价值误计为运行费。

回收期是均值之比，假定后续每期重复相同经营贡献，未考虑贴现、设备寿命或从空系统起步造成的爬坡差异。没有将短期仿真外推为已验证的长期回收结果。消除换模、无故障仍是理想对照，其实施费用未知。

配置新增字段（旧配置文件不填写时采用案例默认值）：

```json
{
  "product_prices": {"P1": 200, "P2": 180, "P3": 250, "P4": 300},
  "machine_purchase_cost": 500000,
  "operating_cost_per_hour": 100,
  "operating_cost_basis": "machine_active"
}
```

| `operating_cost_basis` | 计费小时数 | 适用口径 |
|---|---|---|
| `machine_active` | 所有机床实际加工与换模时间之和 / 60 | 默认；维修、阻塞、空闲不计费 |
| `machine_calendar` | 所有机床全部状态时间之和 / 60 | 可选的每台机床全时计费对照 |
| `line_calendar` | 观察时长 / 60 | 整线固定费率，不乘机床数、不任意分摊至单台 |

金额参数必须为有限非负数，售价字典须完整提供 P1–P4。单次结果、重复实验统计、时间采样、HTTP API、离线 HTML 和 CSV 使用同一套经济核算数据；结果结构升级为 `schema_version: 2`。

## 补充假设与边界

这些是实现口径，不是原文全部明确规定的条件：

1. 空系统开始，无预热期；2400 分钟为累计工作时间，不模拟夜间。首批在第一个指数间隔后到达，每件独立抽产品，允许混合批次。
2. 每台机床有独立模具和故障状态；首次装模免费，故障不令整个工位停机。故障间隔补充为指数分布，只消耗加工与换模时间；维修后续做，无共享维修工约束。
3. 工位间运输为零。下游满载时采用“加工后阻塞”；线外毛坯单独等待，外生到达过程不中断。
4. **缓冲准入按请求时刻 FIFO**，线外毛坯与上游转入共用待入队队列，不设优先级。FIFO/同类优先/超时优先只选择已进入缓冲的工件。因此在高到达负荷下，M2 的 P3 入口可能使来自 M1 的 P1 长时间阻塞，并影响其他产品的供给。投料优先级是后续可单独研究的决策，不隐含在同类优先中。
5. 采用 `[0, horizon)` 窗口，截止时刻的普通事件不执行；工作恰好耗尽故障额度时先完成工作，下一段有效工作前维修。符合 [SimPy 终止时间语义](https://simpy.readthedocs.io/en/stable/topical_guides/environments.html)。
6. 同类优先可能让其他产品久等；另提供 `aging`（等待超过 `aging_threshold` 后按 FIFO 优先）供自定义基准使用。

## 实验方案

| ID | 对基准的唯一修改 |
|---|---|
| `baseline` | 当前基准配置，默认 FIFO |
| `m4_extra` | M4 增加 1 台机床 |
| `same_family` | 使用同类优先 |
| `no_setup` | 换模时间变为 0 |
| `no_failure` | 关闭故障 |

首轮核心实验采用 FIFO/同类优先 × M4=1/2 台四个方案：`baseline`、`m4_extra`、`same_family`、`same_family_m4_extra`。`same_family_m4_extra` 的配对基准是 `same_family`，用于单独识别同类优先下的 M4 增机效果。

同一轮不同方案共享外生到达清单；加工时长按“种子 + 工件编号 + 工序”固定，不随派工顺序变化。故障与维修随机流按机床名称固定；新增机床有自己的流。每轮种子递增，各次运行重建环境及所有状态。

产量差值先逐轮相减，再计算均值和双侧 95% Student-t 区间；百分比为“配对平均差值 / 基准平均产量”。若区间跨 0，不将变化方向解释为已确认。1 次重复没有可估计的区间；面板与实验入口支持 1–30 次重复。

默认种子 42–51、当前建模假设下，核心四方案的复现结果：

| 方案 | 平均成品 / 件 | 相对基准的配对平均差值 / 件 | 差值 95% CI / 件 |
|---|---:|---:|---:|
| 基准 | 339.3 | — | — |
| M4 增加机床 | 338.8 | −0.5 | [−1.6, 0.6] |
| 同类优先 | 448.9 | +109.6 | [86.4, 132.8] |
| 同类优先 + M4 增机 | 448.8 | −0.1（相对同类优先） | [−0.3, 0.1] |

这些数值用于复现检查，依赖上面的投料、阻塞与故障假设；M4 增机的配对区间跨 0，不能据此确认扩容有效。经营贡献应按实际完工产品收入减去所选运行费口径计算，不可直接用产量变化替代经济收益。完整经济汇总、配对差值和资本支出明细见 `work_outputs/formal_core_20261023_rerun/`。

同一批种子的经济汇总（运行费按默认机床加工+换模口径；金额为元/仿真观察期）：

| 方案 | 销售收入 | 运行费 | 经营贡献 | 配对经营贡献增量 | 增量 95% CI |
|---|---:|---:|---:|---:|---|
| 基准 FIFO，M4=1 | 83,581.00 | 15,413.31 | 68,167.69 | — | — |
| FIFO，M4=2 | 83,449.00 | 15,409.80 | 68,039.20 | −128.49 | [−506.70, 249.72] |
| 同类优先，M4=1 | 110,643.00 | 15,338.38 | 95,304.62 | +27,136.93 | [21,040.39, 33,233.47] |
| 同类优先，M4=2 | 110,639.00 | 15,442.41 | 95,196.59 | −108.04（相对同类优先） | [−199.18, −16.90] |

这组结果只代表当前 2400 分钟观察窗及成本假设；M4 加机的配对经营贡献增量没有显示正向改善，且同类优先下的区间低于 0。新增设备价值仍单独列为资本投资；在 2400 分钟与现实生产周的映射确认前，不把观察期回收估算换算成现实周数。

## 指标与记录

- 成品：仅计完成全部工艺的工件；`已到达 = 成品 + 线内在制 + 线外待投料`。
- 平均完成周期：外部到达到完成，含线外等待，只含已完成件。另保留从投料到完成的流动时间。不是所有到达件的无偏交期估计。
- 队列等待：入缓冲到被分配机床，不含换模与维修；未派工件另报数量和已等待时长，不当作 0。跨轮显示各轮样本均值的平均值；无样本轮数可从 JSON 的 `n` 核对。
- 加工利用率：实际加工时间 /（机床数量 × horizon）。换模、维修、阻塞、空闲分别计时，五种状态总和为 100%。
- 经济口径：收入按 P1/P2/P3/P4 = 200/180/250/300 元计；运行费默认按加工+换模实际运行小时 × 100 元计算，另支持机床全时和整线全时口径；购置投资单列。`operating_contribution` 只扣已知运行费，不含折旧等未确认成本，也不等同净利润。新增设备折旧示例与回收期边界见 [`docs/case22_economic_accounting.md`](docs/case22_economic_accounting.md)。
- 平均队长：分段队长的时间积分 / horizon，包含末尾未结束区间。没有对事件数简单平均。
- 回放：每方案**第一轮**，20 分钟采样一次；时间线使用完整状态区间。主 KPI、产出趋势、产品结构与方案对比是**重复实验均值**。

输出文件：

```text
outputs/
├── dashboard.html                # 单文件，内嵌所有面板资源与数据
├── results.json                  # 方案统计、逐轮样本及第一轮回放
├── replications.csv              # 每方案 × 每轮的 KPI
├── summary.csv                   # 指标均值、标准差、95% 区间半宽与有效 n
├── economics.csv                 # 经济指标、贡献配对区间、新增投资与回收期
└── representative/<scenario>/    # 每方案第 1 次重复的原始明细
    ├── jobs.csv
    ├── operations.csv
    ├── machine_states.csv
    ├── queues.csv
    ├── product_revenue.csv       # 实际完工产品数、售价和收入
    └── machine_costs.csv         # 单台机床计费时长与运行费；整线口径留空
```

CSV 使用带 BOM 的 UTF-8，方便表格软件打开。原始明细保留第一轮；如需某一其他种子的全部记录，用 `run --scenario ... --seed ... --output ...` 单独导出。无到达时明细允许为空，JSON 中无有效均值时为 `null`。

## 验证

自动测试覆盖四条路线的手算工时、故障后续做、换模中断、下游占机、并行派工唯一性、外部到达不中断、数量与状态时间守恒、经济指标、核心四方案矩阵、配对统计、种子复现、输入校验、HTTP 重跑与离线导出。

经济核算另覆盖四种售价、三种计费口径、2400 分钟到 40 小时的单位换算、期末未完工不确认收入、工作截断、资本支出分离、非正增量不算回收期、价格变动不改变生产事件，以及 HTTP/JSON/CSV 与配对统计的一致性。

原有 `soft-procedure.ipynb` 与 `案例二十二.docx` 保持原样。模型框架记录以本项目 SimPy 实现和参数契约文档为准。
