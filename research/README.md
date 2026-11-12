# 经营贡献搜索实验 · 2026-10-22

本轮已在预定的独立确认终点结束。这里保存实际执行的评测器、26 份冻结策略、候选生成决策、公开统计和静态页面源文件。没有开启第二轮搜索，也没有把胜出策略替换为生产默认策略。

## 结果与适用范围

目标是空系统开始、无预热的 `[0, 2400)` 工作分钟内：完工收入 − 所有已发生加工费 − 换模费。未完成工件的加工和换模照计费用；空闲、维修与阻塞不计费。设备数、来料、路线、售价、费率、故障与随机机制均固定。

独立确认每方案 100 次，胜出者 `c20_hybrid` 在 M2/M3/M4 使用同类优先，在其他工位按剩余贡献率派工；准入优先释放上游占机，再按贡献率选择外部请求。

| 确认比较 | 经营贡献均值 / 元 | 配对增量 / 元 | 正式单侧下界 / 元 |
|---|---:|---:|---:|
| c20_hybrid | 140,782.90 | — | — |
| 相对 FIFO（均值 67,673.64） | — | +73,109.26 | +69,474.28 |
| 相对同类优先（均值 95,065.87） | — | +45,717.03 | +41,865.60 |

相对同类优先均值增加约 48.09%。代价是 P1/P2/P3/P4 的平均交付为 0.48 / 0.81 / 355.72 / 238.54 件，线外积压均值 2,237.42 件，线内在制均值 172.29 件。题目没有合同保供门槛，结果不能外推为满足产品交付要求、长期最优或完整净利润。

## 搜索过程

| 阶段 | 范围 | 次数 |
|---|---|---:|
| 冒烟 | 24 个候选 × 3 个公开种子 | 72 |
| 开发 | 24 个候选 + 2 个对照，各 30 个公开种子 | 780 |
| 封闭验证 | 冻结开发前三名 + 2 个对照，各 50 个新种子 | 250 |
| 独立确认 | 验证胜出者 + 2 个对照，各 100 个新种子 | 300 |
| 合计 | 一次有界搜索，无追加样本 | 1,402 |

候选路径保存在 `search_workspace/notes/` 和逐候选 `submission.json`，包括机制探索、参数细化、组合与消融；静态实验树可回看全部 24 个候选。封闭阶段不反馈中途成绩。总研究线 α=0.05，本轮分配 0.025，再按两个预声明比较作 Bonferroni 分配，每项单侧 α=0.0125；正式下界使用 t(99) 分位数 2.276003474751275。图表中的双侧 95% 区间是描述性区间，与正式判定分开呈现。

## 文件与证据

| 路径 | 内容 |
|---|---|
| `contribution_loop/` | 本轮冻结的可信适配器、子进程策略接口、seccomp 边界、计量与搜索控制器 |
| `site/` | 可维护的静态网页模板、样式和交互脚本 |
| `../search_workspace/candidates/` | 24 个候选 + FIFO/同类优先，源代码及两种提交元数据 |
| `../search_workspace/notes/` | 三批候选和两次基于开发成绩的改进决策 |
| `../outputs/contribution_loop_20261022/` | 原始协议、启动指令、执行补充、状态、CSV、原始轨迹哈希、审计回执 |
| `…/evaluator/receipts/` | 各候选各阶段的逐轮记录 |
| `…/evaluator/ledger/events.jsonl` | 1,547 条带 SHA-256 前向链接的追加日志 |
| `…/evaluator/confirmation_preregistration.json` | 确认前固定的胜出者、样本数、比较项、α 和种子承诺 |

原始启动指令和协议从先前会话中保存的生成内容恢复。本轮执行原样保留 `loop_contract.json` 的设计状态；实际实现与限制另记于 `execution_addendum.json`、就绪回执和冻结文件清单，不追改契约或源哈希。

**公开范围：** 用户明确选择将原始轨迹与封闭种子库继续留在本地。约 207 MiB 的 `evaluator/raw/`、`evaluator/private/seeds.json`、基准预检原始轨迹及包含种子的完整本地 ZIP 均被 Git 忽略。公开库提供 1,402 条逐轮统计、各阶段回执和原始文件哈希，可重新核算统计结论，但无法仅凭公开库重放隐藏种子的整条轨迹。原始日志中的首次本地 HTTP 测试失败及随后 38/38 通过记录一并保留。

## 核验

网页生成只需要标准库。统计审计额外需要 SciPy；评测器还需要 SimPy。为了保持原有项目依赖锁不变，研究依赖单独固定：

```bash
uv venv .venv-research --python 3.12
uv pip install --python .venv-research/bin/python -r research/requirements.txt
.venv-research/bin/python tools/audit_contribution_snapshot.py
python tools/build_flexline_static.py --check
PYTHONPATH=src .venv-research/bin/python -m unittest discover -s tests -v
```

公开审计检查冻结源文件、候选元数据、哈希日志链、阶段回执、CSV、全部均值/方差/区间、分产品守恒、原始文件哈希承诺和最终正式下界。输出明确标记 `scope=published-summary`、`raw_files_checked=0`，不会把本地原始轨迹检查冒充为公开可复核项。

保有原始本地证据时，可执行完整只读核验：

```bash
.venv-research/bin/python tools/audit_contribution_snapshot.py --full
```

它额外验证 1,402 份原始文件 SHA-256、大小，以及两个封闭种子库的数量、互斥和预先承诺的哈希。任一原始文件缺失会失败，不自动降级。历史 `outputs/…/verify_campaign.py` 同样需要完整本地证据，而且会重写导出记录；日常检查优先使用上面的只读脚本。

Linux 上的策略边界测试还要求 `/usr/bin/python3` 为本轮使用的 Python 3.13，并提供 `libseccomp.so.2`：

```bash
PYTHONPATH=src:research/contribution_loop .venv-research/bin/python -m unittest preflight -v
```

这是 5 项边界回归，不更新原有预检回执。历史适配器会结束并等待子进程，但未显式关闭管道文件对象，测试可能显示 `ResourceWarning`；该文件按冻结哈希保留，后续评测器版本应补齐资源清理。当前归档有 6 条完整 FIFO/同类优先轨迹与原模型逐字段一致的预检记录。Mac/Windows 可以直接使用静态页和统计审计；策略沙箱依赖 Linux。

## 冻结实现与后续实验

`contribution_loop/` 是生成本轮证据的历史执行版本，保留原文件以便校验哈希。它使用原环境的 `/usr/bin/python3` 和 `/workspace/sites/contribution-loop-20261022/dist` 路径，不是通用跨平台启动器。当前 `state.json` 已封闭，`init`/`batch`/`seal` 拒绝重复运行；不要删除状态或再生成种子库来绕过终点。

新研究周期需另建输出目录、记录环境与新冻结摘要、承接下一次 α 分配，并单独授权。静态页导出和只读审计不消耗实验预算，也不会修改原模拟器或启动新实验。当前接口覆盖固定机床顺序的派工、准入排序、CONWIP 和截止放行；未实现联合多机匹配或在线学习。
