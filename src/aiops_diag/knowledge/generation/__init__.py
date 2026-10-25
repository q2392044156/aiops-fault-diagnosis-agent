# 模块说明：定义当前包的公共入口、版本或导出符号。
"""Evidence-grounded report generation built on the frozen W7 retriever."""

from .engine import RagEngine

# 变量说明：`__all__` 保存本模块或数据模型使用的稳定值。
__all__ = ["RagEngine"]
