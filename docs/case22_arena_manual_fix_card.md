# Arena Student 完成出口修复卡（2026-10-17）

## 操作对象

只打开 Student 副本 `Model1_student_vv_base_v2.doe`，不要打开或覆盖微信目录中的原始 `Model1.doe`。修复完成后另存为 `Model1_student_vv_base_v3.doe`。

## 必须交换的两条连接

在完成全部工艺路线后的 `Decide 1` 模块上：

1. 删除当前从 `Step==6` 指向 `Dispose 1` 的连接。
2. 删除当前从 `Else` 指向 `Record OutPut` 的连接。
3. 将 `Step==6` 分支连接到 `Record OutPut`。
4. 将 `Else` 分支连接到 `Dispose 1`。

SIMAN 诊断文本的错误状态是：

```text
If,Step==6,35$,Yes:   ; 35$ = Dispose 1
Else,32$,Yes;         ; 32$ = Record OutPut
```

修复后的目标状态是：

```text
If,Step==6,32$,Yes:   ; 32$ = Record OutPut
Else,35$,Yes;         ; 35$ = Dispose 1
```

## 保存后立即做的最小验收

使用 S02-P1 的确定性设置运行 1 个实体：

- P1；加工时间 M1–M5 = 5/8/6/4/3 分钟；换模和故障关闭；运行长度 100 分钟。
- 预期路线时间为 26 分钟。
- `Entity 1.NumberOut = 1`。
- 完工计数器为 1。
- 产出价值为 200 元。
- 数量守恒差为 0。

只有这些值全部满足，才将 v3 作为 Student V&V 基础版本，并从 S01 重新执行。若仍为“路线时间正确但计数器为0”，不要继续 S03；重新检查两条连接的方向和分支条件。

## 证据留存

保存 `.doe`、`.db`、`.out`、Arena 报表、Decide/Record/Dispose 流程截图和预期—实际对照表。修复前的 v2 只作为诊断版本保留，不替换原始模型。
