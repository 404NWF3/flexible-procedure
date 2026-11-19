# Flexline · 独立参数灵敏度页面

打开 [index.html](index.html) 查看本轮物理参数灵敏度。它与 [上一轮实验搜索树](../flexline/index.html)是两项独立实验，使用独立记录、样本和统计范围。

页面内嵌数据、样式、脚本与统计下载内容，无需联网或启动 Python。选择一个固定策略，再选择经营贡献、产量、积压、故障或分产品交付；四张图均比较该策略自身的标准情景，纵轴使用同一尺度。点击、鼠标悬停或键盘聚焦数据点可查看实际参数值和区间。

执行期间每个情景完成后重新生成 HTML，刷新本地文件即可读取新快照；全部结束后为固定归档。未完成的参数水平不会显示为零。运行进度矩阵与完整样本统计分开呈现。

在仓库根目录可运行：

```bash
.venv-research/bin/python research/sensitivity/render.py
.venv-research/bin/python research/sensitivity/render.py --check
python -m http.server 8765 --bind 127.0.0.1 --directory docs
# http://127.0.0.1:8765/sensitivity/
```

方法、依赖与独立核验见 [研究说明](../../research/sensitivity/README.md)。本页没有重新运行或调整策略的功能，参数情景不能当作上一轮系统提升的候选。
