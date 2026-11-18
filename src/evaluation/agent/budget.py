"""评测预算核算：把两次账本读数之差与配置里的上限比较。"""


def usage_delta(before, after):
    """两次账本读数的差值；任一端缺失就返回 None，表示这一轮没有开在线调用。"""
    if before is None or after is None:
        return None
    return {"input_tokens": after["input_tokens"] - before["input_tokens"],
            "output_tokens": after["output_tokens"] - before["output_tokens"],
            "calls": after["calls"] - before["calls"],
            "estimated_cost_cny": round(after["estimated_cost_cny"]
                                        - before["estimated_cost_cny"], 8)}


def over_budget(cfg, before, current, per_run=False):
    """按 token 与人民币两个口径判断评测预算是否已经超限。"""
    used = usage_delta(before, current)
    suffix = "run_" if per_run else ""
    return (used["input_tokens"] + used["output_tokens"]
            >= int(cfg["evaluation"][f"{suffix}max_tokens"])
            or used["estimated_cost_cny"]
            >= float(cfg["evaluation"][f"{suffix}max_cost_cny"]))
