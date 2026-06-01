# 同时继承 str 和 Enum
import enum
class TaskStatus(str, enum.Enum):
    PENDING = "pending"

status = TaskStatus.PENDING

print(status)               # 输出：pending  ← 直接就是字符串
print(status == "pending")  # 输出：True  ← 比较正常
print(status.value)         # 输出：pending  ← 也可以用 .value