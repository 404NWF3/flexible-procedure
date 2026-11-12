# Flexline 静态网页

- [index.html](index.html)：本轮搜索实验树，支持节点选择、键盘操作、缩放、阶段切换、贡献分解、分产品交付和证据下载。
- [baseline.html](baseline.html)：原有五方案仿真面板，支持方案对比、成本收益、机床时间线、产线回放和结果导出。

双击 HTML 即可查看。每页都包含自身所需的 CSS、JavaScript 和数据；下载按钮从内嵌数据生成文件，不请求服务器。相互跳转需要两个 HTML 放在同一目录。无 CDN、外部字体、轮询或计算 API；“回放”播放已记录轨迹，配置弹窗只供查看。

也可以通过任意静态服务器预览：

```bash
python -m http.server 8765 --bind 127.0.0.1 --directory docs/flexline
# http://127.0.0.1:8765/
```

## 更新归档页面

生成脚本只读取已保存的结果，不运行新实验。Python 3.12+，无第三方依赖：

```bash
python tools/build_flexline_static.py
python tools/build_flexline_static.py --check
```

搜索页模板位于 `research/site/`，数据源为 `outputs/contribution_loop_20261022/state.json`。五方案页复用 `src/soft_procedure/web/` 模板和 `outputs/results.json`；打包时移除服务探测和重新计算请求，不修改原有本地服务。

生成后的 HTML 已提交，无需先执行命令。修改页面时请编辑模板后重新生成；`--check` 检查生成物与源数据完全一致。统计核验与完整本地证据要求见 [实验归档说明](../../research/README.md)。

## 页面中的结论

搜索页的开发区间仅用于探索，正式结论来自一次独立确认。当前实验已结束，页面不再显示“连接中”或声称后台还在搜索。原始契约保留设计时状态，执行范围和就绪检查以 `execution_addendum.json` 与 `evaluator/ready_receipt.json` 为准。

逐轮统计可公开核验；“完整本地审计回执”是原始轨迹仍在本地时的核验结果，不代表公开仓库包含这些轨迹。哈希清单可用于以后核对本地文件。
