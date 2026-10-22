"""案例二十二的参数；所有模型时间统一为分钟。"""
from dataclasses import asdict, dataclass, field, fields
import math

# 加工均值，单位：分钟
ROUTES = {
    "P1": (("M1", 5), ("M2", 8), ("M3", 6), ("M4", 4), ("M5", 3)),
    "P2": (("M1", 4), ("M3", 7), ("M4", 5), ("M5", 6)),
    "P3": (("M2", 6), ("M3", 5), ("M5", 8)),
    "P4": (("M1", 3), ("M4", 9), ("M5", 4)),
}

PRODUCT_MIX = {"P1": 0.30, "P2": 0.25, "P3": 0.25, "P4": 0.20}
PRODUCT_PRICES = {"P1": 200.0, "P2": 180.0, "P3": 250.0, "P4": 300.0}
OPERATING_COST_BASES = {
    "machine_calendar": "每台机床全部观察时间（含加工、换模、维修、阻塞、空闲）",
    "machine_active": "每台机床实际加工与换模时间（不含维修、阻塞、空闲）",
    "line_calendar": "整条产线全部观察时间",
}

@dataclass
class SimulationConfig:
    horizon: float = 2400.0
    arrival_mean: float = 10.0
    batch_min: int = 5
    batch_max: int = 20

    machine_counts: dict[str, int] = field(
        default_factory=lambda: {
            "M1": 2, "M2": 1, "M3": 2, "M4": 1, "M5": 2,
        }
    )
    buffer_capacity: int = 50
    processing_cv: float = 0.10  # 标准差 / 均值
    setup_time: float = 15.0

    mtbf: float = 6000.0        # 100 小时，统一换算为分钟
    mttr: float = 240.0         # 4 小时
    failures_enabled: bool = True

    policy_name: str = "fifo"
    aging_threshold: float = 120.0
    sample_interval: float = 20.0

    product_prices: dict[str, float] = field(default_factory=lambda: PRODUCT_PRICES.copy())
    machine_purchase_cost: float = 500_000.0  # 元 / 台，资本支出单列
    operating_cost_per_hour: float = 100.0
    operating_cost_basis: str = "machine_active"

    def validate(self) -> "SimulationConfig":
        for key in ("horizon", "arrival_mean", "mtbf", "mttr", "aging_threshold", "sample_interval"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} 必须是有限正数")
        for key in ("processing_cv", "setup_time", "machine_purchase_cost", "operating_cost_per_hour"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} 必须是有限非负数")
        for key in ("batch_min", "batch_max", "buffer_capacity"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} 必须是正整数")
        if self.batch_min > self.batch_max:
            raise ValueError("batch_min 不能大于 batch_max")
        if not isinstance(self.machine_counts, dict) or set(self.machine_counts) != set(STATIONS):
            raise ValueError("machine_counts 必须包含 M1–M5")
        if any(type(v) is not int or v < 1 for v in self.machine_counts.values()):
            raise ValueError("每个工位的机床数必须为正整数")
        if self.policy_name not in ("fifo", "same_family", "aging"):
            raise ValueError("policy_name 必须为 fifo、same_family 或 aging")
        if type(self.failures_enabled) is not bool:
            raise ValueError("failures_enabled 必须为布尔值")
        if not isinstance(self.product_prices, dict) or set(self.product_prices) != set(PRODUCT_MIX):
            raise ValueError("product_prices 必须包含 P1–P4 的售价")
        for product, price in self.product_prices.items():
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
                raise ValueError(f"{product} 售价必须是有限非负数")
        if not isinstance(self.operating_cost_basis, str) or self.operating_cost_basis not in OPERATING_COST_BASES:
            raise ValueError("operating_cost_basis 必须为 machine_calendar、machine_active 或 line_calendar")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "SimulationConfig":
        if not isinstance(values, dict):
            raise ValueError("config 必须是 JSON 对象")
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"未知参数：{', '.join(sorted(unknown))}")
        return cls(**values).validate()


STATIONS = ("M1", "M2", "M3", "M4", "M5")
ASSUMPTIONS = [
    "从空系统开始；2400 分钟为累计工作时间，不额外模拟夜间或预热期。",
    "每件产品独立按比例抽样，批次允许混合产品；首批在第一次指数到达间隔后到达。",
    "模具和故障属于单台机床；首次装模不耗时，故障不使整个工位停机。",
    "故障间隔补充假设为指数分布，只累计加工和换模时间；维修后续做剩余工作。",
    "维修资源不受共享维修工数量限制；工位间运输时间为零。",
    "缓冲满时采用加工后阻塞，工件继续占用上游机床；外部到达过程持续运行。",
    "缓冲准入请求按请求时刻 FIFO 排队，线外毛坯与上游转入不设优先级；调度规则只对已入缓冲的工件生效。",
    "正态加工时间若抽到非正值则重新抽样；方案共享按工件与工序绑定的加工样本。",
    "观察窗口为 [0, horizon)，截止时刻的普通事件不执行；未完成工件不计成品。",
    "同类优先可能使其他产品等待更久；另提供超时优先策略供自定义基准使用。",
    "窗口内完成全部工艺的产品按配置售价全部售出；在制品和线外毛坯不确认收入，未建模需求、退货或库存残值。",
    "运行成本默认仅按每台机床的实际加工与换模时间计费，维修、阻塞和空闲不计费；可切换为每台机床全时或整线全时计费。",
    "经营贡献 = 销售收入 − 已知运行成本；原文未提供材料、人工、库存持有、维修额外费用、折旧和税费，不代表净利润。",
    "现有机床价值单列；扩容仅计相对当前基准新增机床的购置支出，不将全部购机款作为当期运行费用。",
    "首期增量现金假设销售收入当期收取、运行费用当期支付；仅从经营贡献增量中扣除新增购机款。",
    "简单回收期 = 新增投资 / 配对平均经营贡献增量，单位为观察期；假定后续重复同等收益，未考虑贴现、寿命与产线爬坡。非正增量不计算回收期。",
    "消除换模、无故障为理想对照，改善实施成本未知；经济结果用于估计改善空间，不能直接视为可实施方案的净收益。",
]
