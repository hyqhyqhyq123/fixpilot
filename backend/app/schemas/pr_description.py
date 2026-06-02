# backend/app/schemas/pr_description.py
# 作用：定义 PR Writer Agent 的输出结构

from typing import Optional
from pydantic import BaseModel, Field


class PRDescription(BaseModel):
    """
    PR Writer Agent 生成的 Pull Request 描述。

    Markdown 格式，方便直接粘贴到 GitHub PR 描述框。
    MVP 只生成文案，不自动创建 PR（避免误操作）。
    """
    title: str = Field(description="PR 标题，简洁描述改了什么")

    summary: str = Field(description="## Summary 部分，说明为什么做这次修改")

    changes: str = Field(description="## Changes 部分，列举具体改了什么")

    tests: str = Field(description="## Tests 部分，说明如何验证修改")

    risks: str = Field(description="## Risks 部分，说明潜在风险和注意事项")

    notes: Optional[str] = Field(
        default=None,
        description="## Notes 部分，其他补充信息（可选）",
    )

    full_markdown: str = Field(
        default="",
        description="完整的 Markdown 格式 PR 描述（所有章节合并后的文本）",
    )
