# backend/app/agents/repository_analyst.py
# Purpose: Repository Analyst Agent wrapper.
#
# A Tool is a small concrete operation, such as cloning a repository.
# An Agent decides which tool outputs matter for the workflow and returns a
# stable shape that later nodes can use.

from pydantic import BaseModel, Field

from app.tools.repo_analysis_tool import (
    ProjectInfo,
    get_file_tree_text,
    list_files,
)
from app.tools.repo_clone_tool import clone_repo


class RepositoryCloneResult(BaseModel):
    """Normalized clone result returned by the Repository Analyst Agent."""

    success: bool
    workspace_path: str | None = None
    repo_path: str | None = None
    message: str | None = None
    error: str | None = None


class RepositoryAnalysisResult(BaseModel):
    """Workflow-ready repository analysis output."""

    repo_path: str = Field(description="Local repository path")
    total_files: int = Field(description="Number of scanned files")
    total_dirs: int = Field(description="Number of scanned directories")
    file_tree_summary: str = Field(description="Readable repository tree summary")
    project_info: ProjectInfo = Field(description="Detected project metadata")
    test_command: str | None = Field(default=None, description="Suggested test command")
    lint_command: str | None = Field(default=None, description="Suggested lint command")
    typecheck_command: str | None = Field(
        default=None,
        description="Suggested type-check command",
    )


def clone_repository(task_id: int, repo_url: str) -> RepositoryCloneResult:
    """
    Clone a public GitHub repository through the existing clone tool.

    The Agent keeps the workflow insulated from raw tool dictionaries, so future
    changes to the tool are less likely to leak into LangGraph nodes.
    """

    return RepositoryCloneResult.model_validate(
        clone_repo(task_id=task_id, repo_url=repo_url)
    )


def analyze_repository(repo_path: str) -> RepositoryAnalysisResult:
    """
    Analyze repository structure and expose the fields used by later agents.

    The underlying tool already detects languages, frameworks, commands and file
    trees. This function packages those results into one Agent-level model.
    """

    analysis = list_files(repo_path)
    project_info = analysis.project_info
    return RepositoryAnalysisResult(
        repo_path=analysis.repo_path,
        total_files=analysis.total_files,
        total_dirs=analysis.total_dirs,
        file_tree_summary=get_file_tree_text(analysis),
        project_info=project_info,
        test_command=project_info.test_command,
        lint_command=project_info.lint_command,
        typecheck_command=project_info.typecheck_command,
    )
