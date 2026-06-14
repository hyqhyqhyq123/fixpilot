# backend/app/schemas/test_result.py
# 作用：定义测试执行结果的数据结构
#
# 为什么要结构化测试结果？
# Failure Diagnoser Agent 需要读取测试的 stdout/stderr 来分析失败原因。
# 结构化格式比纯文本更好解析和记录。

from typing import Literal, Optional

from pydantic import BaseModel, Field

CheckType = Literal["test", "lint", "typecheck"]


class TestRunResult(BaseModel):
    """
    一次测试运行的完整结果。

    exit_code 是关键字段：
    - 0 = 测试全部通过
    - 非 0 = 有失败（具体数值含义因测试框架而异）

    stdout 是正常输出（测试结果），stderr 是错误输出（崩溃信息）。
    """
    command: str = Field(description="实际执行的测试命令，例如 'pytest tests/'")

    check_type: CheckType = Field(
        default="test",
        description="检查类型：test / lint / typecheck（FR-603）",
    )

    exit_code: int = Field(description="命令退出码：0 表示成功，非 0 表示失败")

    stdout: str = Field(default="", description="标准输出内容（测试框架的输出）")

    stderr: str = Field(default="", description="标准错误内容（崩溃、异常等）")

    duration_ms: int = Field(default=0, description="命令执行耗时（毫秒）")

    passed: bool = Field(description="测试是否全部通过（exit_code == 0）")

    timed_out: bool = Field(
        default=False,
        description="是否超时（超时时 passed=False，exit_code=-1）",
    )

    error_message: Optional[str] = Field(
        default=None,
        description="如果是系统错误（找不到命令等），记录错误信息",
    )
