"""按已完成产量与实际状态时间计价，不改变生产事件或随机流。金额单位为元。"""


def machine_chargeable_hours(config, state_times):
    if config.operating_cost_basis == "line_calendar":
        return None  # 整线费率不任意分摊给单台机床。
    minutes = (state_times["processing"] + state_times["setup"]
               if config.operating_cost_basis == "machine_active" else sum(state_times.values()))
    return minutes / 60.0


def economic_snapshot(config, completed_by_product, machine_times, elapsed):
    revenue = sum(completed_by_product[p] * price for p, price in config.product_prices.items())
    hours = (elapsed / 60.0 if config.operating_cost_basis == "line_calendar" else
             sum(machine_chargeable_hours(config, times) for times in machine_times))
    cost = hours * config.operating_cost_per_hour
    return {"sales_revenue": revenue, "operating_cost": cost, "operating_contribution": revenue - cost}


def investment_comparison(config, base, paired_contribution):
    """只评价增量投资；回收期取均值之比，绝不平均逐轮的回收期。"""
    added = sum(max(0, count - base.machine_counts[name]) for name, count in config.machine_counts.items())
    capex = added * config.machine_purchase_cost
    gain, ci = paired_contribution["mean"], paired_contribution["ci95"]
    payback = capex / gain if capex > 0 and gain > 0 else None
    status = ("no_additional_capex" if capex == 0 else
              "no_positive_gain" if gain <= 0 else
              "positive_gain" if ci is not None and gain - ci > 0 else "uncertain_gain")
    return {
        "additional_machines": added,
        "additional_capex": capex,
        "first_period_incremental_cash": gain - capex,
        "payback_periods": payback,
        "payback_work_hours": payback * config.horizon / 60 if payback is not None else None,
        "status": status,
    }
