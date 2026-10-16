# Flexline · 柔性生产线决策仿真

基于 **SimPy** 复现《案例二十二：多品种小批量柔性生产线调度优化》，沿用参考对话的“工件 → 工位 → 单台机床”结构，提供可重复实验、原始记录和中文 HTML 面板。模型时间统一为**分钟**。

## 直接运行

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。运行时仅依赖 SimPy；HTML 不使用 CDN、外部字体或前端构建工具。

```bash
uv sync
uv run soft-procedure serve
```

浏览器打开 **http://127.0.0.1:8765**。首次启动计算 5 个方案 × 10 次重复；“配置与运行”会真实调用 Python/SimPy，完成后同时更新图表与 `outputs/`。仅监听本机地址。按 `Ctrl+C` 停止。

只生成可离线打开的 HTML：

```bash
uv run soft-procedure experiments --replications 10 --seed 42
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
├── experiments.py        # 单因素方案、配对重复、95% t 区间
├── export.py             # JSON、CSV 与自包含 HTML 导出
├── server.py             # 本地 GET /api/results、POST /api/run
├── cli.py                # 命令行入口
└── web/                  # HTML 模板、CSS 与原生 JavaScript
tests/                    # 手算契约、随机复现、接口与导出测试
examples/custom.json      # 只覆盖需要变动的配置
analysis.ipynb            # 读取逐轮结果与重新核算的可选分析本
outputs/                  # 已生成的面板与实验记录
```

Python 调用接口：

```python
from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.experiments import run_experiments

result = run_simulation(SimulationConfig(), seed=42)
print(result["summary"])

suite = run_experiments(SimulationConfig(), replications=10, seed=42)
```

`Station.put(job)` 只在工件真正进入缓冲后触发；`Station.request_job(machine)` 在完成原子分配后返回工件。`Machine` 在交接事件成功前一直占机。`Simulation._transfer` 唯一负责推进工序索引和登记成品。

## 案例参数

| 产品 | 比例 | 路线（加工均值 / min） |
|---|---:|---|
| P1 | 30% | M1(5) → M2(8) → M3(6) → M4(4) → M5(3) |
| P2 | 25% | M1(4) → M3(7) → M4(5) → M5(6) |
| P3 | 25% | M2(6) → M3(5) → M5(8) |
| P4 | 20% | M1(3) → M4(9) → M5(4) |

M1–M5 的机床数为 `2 / 1 / 2 / 1 / 2`。加工时长为正态分布，标准差为均值的 10%；非正样本重新抽样。到达间隔 `EXPO(10)`，批量为离散均匀 `5…20`，每工位缓冲 50 件。不同产品换模 15 分钟。MTBF 6000 分钟，维修 `EXPO(240)`。观察 2400 分钟，默认 10 次重复，种子 42–51。

## 补充假设与边界

这些是实现口径，不是原文全部明确规定的条件：

1. 空系统开始，无预热期；2400 分钟为累计工作时间，不模拟夜间。首批在第一个指数间隔后到达，每件独立抽产品，允许混合批次。
2. 每台机床有独立模具和故障状态；首次装模免费，故障不令整个工位停机。故障间隔补充为指数分布，只消耗加工与换模时间；维修后续做，无共享维修工约束。
3. 工位间运输为零。下游满载时采用“加工后阻塞”；线外毛坯单独等待，外生到达过程不中断。
4. **缓冲准入按请求时刻 FIFO**，线外毛坯与上游转入共用待入队队列，不设优先级。FIFO/同类优先/超时优先只选择已进入缓冲的工件。因此在高到达负荷下，M2 的 P3 入口可能使来自 M1 的 P1 长时间阻塞，并影响其他产品的供给。投料优先级是后续可单独研究的决策，不隐含在同类优先中。
5. 采用 `[0, horizon)` 窗口，截止时刻的普通事件不执行；工作恰好耗尽故障额度时先完成工作，下一段有效工作前维修。符合 [SimPy 终止时间语义](https://simpy.readthedocs.io/en/stable/topical_guides/environments.html)。
6. 同类优先可能让其他产品久等；另提供 `aging`（等待超过 `aging_threshold` 后按 FIFO 优先）供自定义基准使用。

## 五个实验

| ID | 对基准的唯一修改 |
|---|---|
| `baseline` | 当前基准配置，默认 FIFO |
| `m4_extra` | M4 增加 1 台机床 |
| `same_family` | 使用同类优先 |
| `no_setup` | 换模时间变为 0 |
| `no_failure` | 关闭故障 |

同一轮不同方案共享外生到达清单；加工时长按“种子 + 工件编号 + 工序”固定，不随派工顺序变化。故障与维修随机流按机床名称固定；新增机床有自己的流。每轮种子递增，各次运行重建环境及所有状态。

产量差值先逐轮相减，再计算均值和双侧 95% Student-t 区间；百分比为“配对平均差值 / 基准平均产量”。若区间跨 0，不将变化方向解释为已确认。1 次重复没有可估计的区间；面板与实验入口支持 1–30 次重复。

默认种子 42–51、当前建模假设下，已验证的运行结果：

| 方案 | 平均成品 / 件 | 相对基准的配对平均差值 / 件 | 差值 95% CI / 件 |
|---|---:|---:|---:|
| 基准 | 339.3 | — | — |
| M4 增加机床 | 338.8 | −0.5 | [−1.6, 0.6] |
| 同类优先 | 448.9 | +109.6 | [86.4, 132.8] |
| 消除换模 | 421.0 | +81.7 | [69.3, 94.1] |
| 无故障 | 354.3 | +15.0 | [−13.1, 43.1] |

这些数值用于复现检查，依赖上面的投料、阻塞与故障假设。它们并不构成最优策略结论；M4 扩容和无故障两组的差值区间均跨 0。没有成本模型，不能由产量增幅直接推断经济收益。

## 指标与记录

- 成品：仅计完成全部工艺的工件；`已到达 = 成品 + 线内在制 + 线外待投料`。
- 平均完成周期：外部到达到完成，含线外等待，只含已完成件。另保留从投料到完成的流动时间。不是所有到达件的无偏交期估计。
- 队列等待：入缓冲到被分配机床，不含换模与维修；未派工件另报数量和已等待时长，不当作 0。跨轮显示各轮样本均值的平均值；无样本轮数可从 JSON 的 `n` 核对。
- 加工利用率：实际加工时间 /（机床数量 × horizon）。换模、维修、阻塞、空闲分别计时，五种状态总和为 100%。
- 平均队长：分段队长的时间积分 / horizon，包含末尾未结束区间。没有对事件数简单平均。
- 回放：每方案**第一轮**，20 分钟采样一次；时间线使用完整状态区间。主 KPI、产出趋势、产品结构与方案对比是**重复实验均值**。

输出文件：

```text
outputs/
├── dashboard.html                # 单文件，内嵌所有面板资源与数据
├── results.json                  # 五方案统计、逐轮样本及第一轮回放
├── replications.csv              # 每方案 × 每轮的 KPI
├── summary.csv                   # 指标均值、标准差、95% 区间半宽与有效 n
└── representative/<scenario>/    # 每方案第 1 次重复的原始明细
    ├── jobs.csv
    ├── operations.csv
    ├── machine_states.csv
    └── queues.csv
```

CSV 使用带 BOM 的 UTF-8，方便表格软件打开。原始明细保留第一轮；如需某一其他种子的全部记录，用 `run --scenario ... --seed ... --output ...` 单独导出。无到达时明细允许为空，JSON 中无有效均值时为 `null`。

## 验证

自动测试覆盖原对话 `P1 → P1 → P2` 的 5、10、29 分钟交接，四条路线的手算工时，故障后续做、换模中断、下游占机、并行派工唯一性、外部到达不中断、数量与状态时间守恒、时间积分、配对统计、种子复现、输入校验、HTTP 重跑与离线导出。

原有 `soft-procedure.ipynb` 与 `案例二十二.docx` 保持原样。相关记录来源：[Simpy项目框架](chatgpt-conversation://6ad0c956-78d4-83ec-82fd-91e8595d09a4)。
