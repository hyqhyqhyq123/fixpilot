# backend/app/schemas/coder.py
# 作用：Coder Agent 输入输出结构（FR-501）

from typing import List, Optional

from pydantic import BaseModel, Field


class FileEditOperation(BaseModel):
    """单个文件的完整内容修改（V2 首选整文件替换，简单可靠）。"""
    path: str = Field(description="相对仓库根目录的文件路径")
    content: str = Field(description="修改后的完整文件内容")
    is_new_file: bool = Field(default=False, description="是否为新建文件")


class CoderOutput(BaseModel):
    """Coder LLM 输出的 JSON 结构。"""
    edits: List[FileEditOperation] = Field(
        default_factory=list,
        description="要应用的所有文件修改",
    )
    test_note: Optional[str] = Field(
        default=None,
        description="若未新增测试，说明原因（FR-503）",
    )


class CoderApplyResult(BaseModel):
    """Coder 应用修改后的结果。"""
    success: bool
    edited_files: List[str] = Field(default_factory=list)
    edit_records: List[dict] = Field(default_factory=list)
    combined_diff: str = ""
    test_note: Optional[str] = None
    error_message: Optional[str] = None
