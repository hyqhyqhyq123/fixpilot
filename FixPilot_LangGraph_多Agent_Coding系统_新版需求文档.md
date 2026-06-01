# FixPilot：基于 LangGraph 的多 Agent Coding 系统需求文档

## 1. 项目概述

### 1.1 项目名称

**FixPilot：基于 LangGraph 的多 Agent Coding 系统**

### 1.2 项目定位

FixPilot 是一个面向软件开发工作流的多 Agent Coding 系统。用户输入 GitHub Repository 和 Issue 后，系统通过多个职责明确的 Agent 协作完成需求理解、代码库分析、相关文件检索、修改计划生成、人工审批、代码编辑、测试执行、失败自修复、代码审查和 PR 文案生成。

项目重点不是简单“让 LLM 写代码”，而是构建一个具有 **状态管理、工具调用、角色协作、沙箱执行、失败恢复、人工审批和执行追踪** 的真实 Agent 工程系统。

### 1.3 项目核心亮点

1. 使用 LangGraph 构建有状态、多节点、多 Agent workflow。
2. 将 GitHub Issue 自动修复流程拆分为多个专业 Agent。
3. 支持 Coordinator、Issue Analyst、Code Retriever、Planner、Coder、Tester、Reviewer、PR Writer 等 Agent 协作。
4. 支持 LlamaIndex 作为代码语义检索工具。
5. 支持 Docker 沙箱执行测试、lint 和 type check。
6. 支持 human-in-the-loop，在代码修改和 PR 创建前进行人工审批。
7. 支持失败诊断和有限重试，自我修复测试失败。
8. 支持工具调用审计、节点日志、状态持久化和 Agent Trace UI。
9. 支持输出 patch diff、测试摘要、风险说明和 PR 描述。
10. 支持后续扩展为类似 Devin / OpenClaw 的开发者自动化助手。

---

## 2. 目标用户与场景

### 2.1 目标用户

| 用户类型 | 需求 |
|---|---|
| 软件工程师 | 自动处理小型 bug、补测试、生成 PR 草稿 |
| 开源维护者 | 初步处理 issue，生成候选 patch |
| AI Engineer | 展示多 Agent、工具调用、LangGraph 状态机能力 |
| 技术面试官 | 评估候选人是否理解 Agent 工程 |
| 团队负责人 | 自动化重复性修复任务，降低维护成本 |

### 2.2 典型场景

1. **Bug 修复**  
   用户输入 bug issue，系统定位相关文件，修改代码，运行测试并输出 patch。

2. **补充测试**  
   用户要求为某个功能补测试，系统分析测试框架并新增测试文件。

3. **文档修复**  
   用户输入 documentation issue，系统更新 README 或 API 文档。

4. **小功能实现**  
   用户输入简单 feature request，系统生成修改计划，审批后修改代码。

5. **PR 草稿生成**  
   系统根据 diff 自动生成 PR title、summary、changes、tests 和 risks。

---

## 3. 项目目标

### 3.1 产品目标

1. 用户可以提交 GitHub repo 和 issue。
2. 系统可以自动 clone public repo。
3. 系统可以分析项目结构、语言、框架、包管理器和测试命令。
4. 多个 Agent 可以协作完成 issue 理解、代码检索、规划、编辑、测试、审查和报告。
5. 系统在高风险操作前必须请求人工审批。
6. 代码修改必须通过 Docker 沙箱验证。
7. 测试失败后系统可以分析失败原因并有限重试。
8. 最终输出 patch diff、测试日志、风险说明和 PR 文案。
9. 每个步骤必须可追踪、可回放、可调试。

### 3.2 技术目标

1. 使用 LangGraph 管理 workflow state 和 node routing。
2. 使用 LangChain Tools 或自定义 tools 封装外部能力。
3. 使用 LlamaIndex 构建代码库语义检索。
4. 使用 Docker 执行测试和 lint。
5. 使用 PostgreSQL 持久化任务、步骤、日志、diff 和测试结果。
6. 使用 Redis + Celery 执行后台任务。
7. 使用 Next.js 构建可视化 Agent Trace UI。
8. 支持 GitHub API，V1 可自动创建 PR。

---

## 4. 多 Agent 架构

### 4.1 Agent 列表

| Agent | 职责 |
|---|---|
| Coordinator Agent | 总调度，维护全局状态，决定下一步调用哪个 Agent |
| Issue Analyst Agent | 分析 issue 类型、用户意图、验收条件和风险 |
| Repository Analyst Agent | 分析 repo 结构、语言、框架、测试命令和关键配置 |
| Code Retriever Agent | 检索相关代码文件和上下文 |
| Planner Agent | 生成修改计划、涉及文件、测试计划和风险分析 |
| Coder Agent | 根据计划生成 patch 或 edit operations |
| Tester Agent | 在 Docker 沙箱中运行测试、lint、type check |
| Failure Diagnosis Agent | 分析测试失败原因，决定是否需要重试 |
| Reviewer Agent | 审查 diff，检查风险、越权修改和风格问题 |
| PR Writer Agent | 生成 PR title、description、summary、test report |

### 4.2 Agent 协作流程

```text
User submits repo + issue
  ↓
Coordinator Agent
  ↓
Repository Analyst Agent
  ↓
Issue Analyst Agent
  ↓
Code Retriever Agent
  ↓
Planner Agent
  ↓
Human Approval
  ↓
Coder Agent
  ↓
Tester Agent
  ↓
Failure Diagnosis Agent
  ├── retry → Coder Agent
  └── pass/stop → Reviewer Agent
  ↓
PR Writer Agent
  ↓
Final Report
```

### 4.3 为什么用多 Agent

单 Agent 的问题：

1. 上下文过长。
2. 角色目标混乱。
3. 难以定位错误来源。
4. 难以单独评估每个阶段。
5. 工具权限不好控制。

多 Agent 的优势：

1. 每个 Agent 目标明确。
2. 可以单独限制工具权限。
3. 可以分阶段审批。
4. 可以记录每个 Agent 的输入输出。
5. 更容易做评估和调试。
6. 更像真实工程中的分工协作。

---

## 5. MVP 范围

### 5.1 MVP 必须实现

1. 用户登录。
2. 用户输入 public GitHub repo URL 和 issue 文本。
3. 系统 clone repo 到独立 workspace。
4. Repository Analyst 识别项目语言、框架、包管理器和测试命令。
5. Issue Analyst 输出结构化 issue 分析。
6. Code Retriever 使用关键词搜索和文件读取检索相关代码。
7. Planner 生成修改计划。
8. 用户审批修改计划。
9. Coder 根据计划修改文件。
10. Tester 使用 Docker 运行测试命令。
11. Failure Diagnosis 在测试失败时分析 stderr/stdout。
12. 最多自动重试 2 次。
13. Reviewer 审查 diff。
14. PR Writer 生成 PR 文案。
15. 前端展示 Agent 执行时间线、工具调用、diff 和测试日志。

### 5.2 V1 增强范围

1. GitHub OAuth。
2. 私有 repo 支持。
3. 自动读取 issue URL。
4. LlamaIndex 代码语义检索。
5. 自动创建 branch、commit 和 PR。
6. 多 Agent 并行化，例如代码检索和 repo 分析并行。
7. 更细粒度权限控制。
8. 支持 Python、TypeScript、Go、Java。
9. 支持 Code Review Agent 独立审查。
10. 支持回滚到任意 retry step。
11. Agent Trace 可视化和任务回放。

---

## 6. 核心用户流程

### 6.1 创建任务流程

```text
用户登录
  ↓
进入新建任务页
  ↓
输入 GitHub repo URL
  ↓
输入 issue 文本或 issue URL
  ↓
输入可选测试命令
  ↓
设置 max_retries
  ↓
点击开始
  ↓
系统创建 fix_task
```

### 6.2 多 Agent 执行流程

```text
Coordinator 初始化任务状态
  ↓
Repository Analyst 分析仓库
  ↓
Issue Analyst 分析 Issue
  ↓
Code Retriever 检索相关文件
  ↓
Planner 生成修改计划
  ↓
用户审批
  ↓
Coder 修改代码
  ↓
Tester 运行测试
  ↓
失败则 Failure Diagnosis 分析并重试
  ↓
Reviewer 审查 diff
  ↓
PR Writer 生成 PR 文案
  ↓
输出最终报告
```

### 6.3 人工审批流程

```text
Planner 生成计划
  ↓
前端展示：
  - 问题理解
  - 根因假设
  - 涉及文件
  - 修改步骤
  - 测试计划
  - 风险分析
  ↓
用户选择：
  - 批准
  - 拒绝
  - 补充要求
  - 取消任务
```

### 6.4 自我修复流程

```text
Coder 生成 patch
  ↓
Tester 运行测试
  ↓
测试失败
  ↓
Failure Diagnosis 读取错误日志
  ↓
判断是否由本次修改导致
  ↓
生成修复建议
  ↓
retry_count < max_retries 则回到 Coder
  ↓
否则输出失败报告
```

---

## 7. 功能需求

## 7.1 用户与任务模块

### FR-001 用户登录

用户可以通过邮箱密码登录。

**V1 支持：**

- GitHub OAuth

### FR-002 创建修复任务

用户输入：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| repo_url | string | 是 | GitHub 仓库 URL |
| issue_text | text | 是 | Issue 描述 |
| issue_url | string | 否 | GitHub Issue URL |
| base_branch | string | 否 | 默认 main |
| test_command | string | 否 | 测试命令 |
| lint_command | string | 否 | lint 命令 |
| max_retries | integer | 否 | 默认 2 |

**验收标准：**

1. repo_url 必须是合法 GitHub URL。
2. MVP 只支持 public repo。
3. 创建成功后返回 task_id。
4. 任务初始状态为 pending。

### FR-003 查看任务列表

展示：

1. repo 名称。
2. issue summary。
3. status。
4. 当前 Agent。
5. 创建时间。
6. 最终结果。

### FR-004 查看任务详情

展示：

1. issue 原文。
2. repo 信息。
3. Agent 时间线。
4. 每个 Agent 的输入输出摘要。
5. 工具调用记录。
6. 修改计划。
7. 审批记录。
8. diff。
9. 测试日志。
10. 最终报告。

---

## 7.2 Repository Analyst Agent

### FR-101 Clone Repo

系统需要将 repo clone 到独立 workspace。

**要求：**

1. 每个任务使用独立目录。
2. 禁止覆盖已有 workspace。
3. clone 失败时任务状态为 failed。
4. clone 日志保存到 task_steps。

### FR-102 分析项目结构

识别：

1. 编程语言。
2. 框架。
3. 包管理器。
4. 测试框架。
5. lint 工具。
6. type check 工具。
7. 入口文件。
8. 关键配置文件。

**规则示例：**

| 文件 | 推断 |
|---|---|
| package.json | Node.js / TypeScript |
| pyproject.toml | Python |
| requirements.txt | Python |
| go.mod | Go |
| pom.xml | Java Maven |
| Cargo.toml | Rust |

### FR-103 生成文件树摘要

要求：

1. 排除 node_modules、.git、dist、build、venv、__pycache__。
2. 大型 repo 只展示前 3 层。
3. 标记 src、tests、docs、config 文件夹。
4. 标记 package.json、pyproject.toml 等关键文件。

---

## 7.3 Issue Analyst Agent

### FR-201 Issue 分类

输出 JSON：

```json
{
  "issue_type": "bug | feature | documentation | refactor | test | dependency | unknown",
  "summary": "string",
  "expected_behavior": "string",
  "actual_behavior": "string | null",
  "acceptance_criteria": ["string"],
  "constraints": ["string"],
  "risk_level": "low | medium | high",
  "needs_user_clarification": false
}
```

**验收标准：**

1. 必须输出合法 JSON。
2. 信息不足时 needs_user_clarification 为 true。
3. high risk 任务必须进入人工审批。

### FR-202 提取验收条件

从 issue 中提取可验证条件。

示例：

```json
{
  "acceptance_criteria": [
    "空输入时 API 返回 400",
    "已有测试继续通过",
    "新增 invalid input 单元测试"
  ]
}
```

---

## 7.4 Code Retriever Agent

### FR-301 关键词搜索

使用 ripgrep 或等效工具搜索关键词。

**输入：**

1. query。
2. file_extensions。
3. max_results。

**输出：**

1. file_path。
2. line_start。
3. line_end。
4. snippet。
5. score。

### FR-302 LlamaIndex 代码语义检索

V1 使用 LlamaIndex 对代码库建立索引。

**切分策略：**

1. 按文件切分。
2. 按函数 / 类切分。
3. 保留 file_path、language、symbol_name、line_start、line_end。
4. issue_text 作为 query。

**输出：**

```json
{
  "retrieved_files": [
    {
      "file_path": "src/utils/validator.ts",
      "line_start": 10,
      "line_end": 48,
      "snippet": "string",
      "score": 0.83,
      "method": "semantic"
    }
  ]
}
```

### FR-303 多策略检索

组合：

```text
Issue keywords
  + stack trace symbols
  + error messages
  + semantic retrieval
  + file tree hints
```

### FR-304 读取文件

Agent 可以读取文件内容。

**限制：**

1. 只能读取 workspace 内文件。
2. 禁止路径逃逸。
3. 单次读取超过 30KB 时需要分段。
4. 读取操作必须记录日志。

---

## 7.5 Planner Agent

### FR-401 生成修改计划

输出 JSON：

```json
{
  "problem_summary": "string",
  "root_cause_hypothesis": "string",
  "files_to_modify": [
    {
      "path": "string",
      "reason": "string",
      "planned_changes": ["string"]
    }
  ],
  "files_to_add": [
    {
      "path": "string",
      "reason": "string"
    }
  ],
  "test_plan": ["string"],
  "risk_analysis": "string",
  "requires_approval": true
}
```

**验收标准：**

1. 必须列出涉及文件。
2. 必须包含测试计划。
3. 必须说明风险。
4. 计划必须审批后才能进入 Coder。

### FR-402 计划修订

用户可以补充要求，Planner 重新生成计划。

**示例：**

```text
不要修改 API 行为，只补充错误处理。
```

Planner 必须把用户补充要求写入 state。

---

## 7.6 Coder Agent

### FR-501 生成 Patch

Coder 根据审批计划生成 patch。

**方式：**

1. MVP 使用 unified diff。
2. V1 支持结构化 edit operations。

**edit operation 示例：**

```json
{
  "file_path": "src/utils/validator.ts",
  "operation": "replace",
  "target": "old code",
  "replacement": "new code"
}
```

### FR-502 修改限制

Coder 只能修改计划中允许的文件。

**要求：**

1. 修改计划外文件需要重新审批。
2. 每次修改前保存快照。
3. patch 应用失败时回滚。
4. 修改后必须生成 git diff。

### FR-503 新增测试

如果项目存在测试目录，Coder 应尝试新增或更新测试。

**要求：**

1. bug fix 优先补测试。
2. 不补测试时必须说明原因。
3. 测试文件必须符合项目风格。

---

## 7.7 Tester Agent

### FR-601 Docker 沙箱执行

Tester 在 Docker 沙箱运行测试。

**默认限制：**

| 资源 | 限制 |
|---|---|
| CPU | 2 cores |
| Memory | 2GB |
| Timeout | 120 秒 |
| Workspace | 当前任务目录 |
| Network | MVP 可开启，V1 可限制 |

### FR-602 自动检测测试命令

规则：

| 项目类型 | 命令 |
|---|---|
| Node.js | npm test |
| Python + pytest | pytest |
| Python + unittest | python -m unittest |
| Go | go test ./... |
| Rust | cargo test |

### FR-603 运行 lint 和 type check

支持：

1. npm run lint
2. npm run typecheck
3. ruff check .
4. mypy .
5. eslint .
6. go test ./...
7. cargo clippy

### FR-604 测试结果结构化

输出：

```json
{
  "command": "pytest",
  "exit_code": 1,
  "stdout": "string",
  "stderr": "string",
  "duration_ms": 5421,
  "passed": false
}
```

---

## 7.8 Failure Diagnosis Agent

### FR-701 错误诊断

测试失败时分析日志。

输出：

```json
{
  "failure_summary": "string",
  "likely_cause": "string",
  "is_caused_by_current_patch": true,
  "related_files": ["string"],
  "next_fix_plan": ["string"],
  "should_retry": true
}
```

### FR-702 有限重试

默认 max_retries = 2。

**要求：**

1. 每次重试保存 diff。
2. 每次重试保存测试日志。
3. 超过次数后停止。
4. 如果失败与当前 patch 无关，停止重试并说明。

---

## 7.9 Reviewer Agent

### FR-801 Diff 审查

Reviewer 检查：

1. 是否只修改计划内文件。
2. 是否存在高风险代码。
3. 是否删除大量代码。
4. 是否引入敏感信息。
5. 是否修改配置、依赖或 CI。
6. 是否有测试。
7. 是否符合 issue 目标。

### FR-802 风险分级

输出：

```json
{
  "risk_level": "low | medium | high",
  "issues": [
    {
      "type": "scope_creep",
      "message": "修改了计划外文件",
      "file": "string"
    }
  ],
  "approval_required": true
}
```

高风险时需要人工确认。

---

## 7.10 PR Writer Agent

### FR-901 生成 PR 文案

格式：

```markdown
## Summary

## Changes

## Tests

## Risks

## Notes
```

### FR-902 生成 Commit Message

示例：

```text
fix: handle empty input in request validator
```

### FR-903 V1 创建 PR

流程：

```text
create branch
  ↓
commit changes
  ↓
push branch
  ↓
create pull request
  ↓
return PR URL
```

**要求：**

1. 创建 PR 前必须审批。
2. 不允许自动 merge。
3. commit message 和 PR body 必须展示给用户。

---

## 8. LangGraph 状态设计

### 8.1 State Schema

```python
from typing import TypedDict, List, Optional, Dict, Any

class FixPilotState(TypedDict):
    task_id: str
    user_id: str

    repo_url: str
    repo_path: Optional[str]
    base_branch: str

    issue_text: str
    issue_url: Optional[str]

    current_agent: str
    current_node: str
    status: str

    project_info: Optional[Dict[str, Any]]
    file_tree_summary: Optional[str]

    issue_analysis: Optional[Dict[str, Any]]
    retrieved_context: List[Dict[str, Any]]

    plan: Optional[Dict[str, Any]]
    approval_status: str
    user_feedback: Optional[str]

    allowed_files: List[str]

    edit_history: List[Dict[str, Any]]
    current_diff: Optional[str]

    test_command: Optional[str]
    lint_command: Optional[str]
    typecheck_command: Optional[str]
    test_results: List[Dict[str, Any]]

    failure_analysis: Optional[Dict[str, Any]]
    retry_count: int
    max_retries: int

    review_result: Optional[Dict[str, Any]]
    pr_draft: Optional[str]

    final_status: str
    final_report: Optional[str]
    error_message: Optional[str]
```

### 8.2 Node 列表

| Node | Agent | 作用 |
|---|---|---|
| intake_node | Coordinator | 初始化任务 |
| clone_repo_node | Repository Analyst | clone repo |
| analyze_repo_node | Repository Analyst | 分析项目结构 |
| classify_issue_node | Issue Analyst | 分析 issue |
| retrieve_context_node | Code Retriever | 检索代码 |
| planning_node | Planner | 生成计划 |
| approval_node | Coordinator | 等待人工审批 |
| edit_code_node | Coder | 修改代码 |
| run_tests_node | Tester | 运行测试 |
| diagnose_failure_node | Failure Diagnosis | 分析失败 |
| retry_decision_node | Coordinator | 判断是否重试 |
| review_diff_node | Reviewer | 审查 diff |
| pr_writer_node | PR Writer | 生成 PR 文案 |
| final_report_node | Coordinator | 生成报告 |

### 8.3 Edge 设计

```text
START
  ↓
intake_node
  ↓
clone_repo_node
  ↓
analyze_repo_node
  ↓
classify_issue_node
  ↓
retrieve_context_node
  ↓
planning_node
  ↓
approval_node
  ├── approved → edit_code_node
  ├── rejected → planning_node
  └── cancelled → final_report_node
  ↓
run_tests_node
  ├── pass → review_diff_node
  └── fail → diagnose_failure_node
                  ↓
             retry_decision_node
                  ├── retry → edit_code_node
                  └── stop → review_diff_node
  ↓
review_diff_node
  ├── low_risk → pr_writer_node
  ├── high_risk → approval_node
  └── reject → final_report_node
  ↓
pr_writer_node
  ↓
final_report_node
```

---

## 9. 工具设计

### 9.1 工具列表

| Tool | 权限级别 | 说明 |
|---|---|---|
| repo_clone_tool | medium | clone repo |
| list_files_tool | low | 列出文件 |
| read_file_tool | low | 读取文件 |
| search_code_tool | low | 关键词搜索 |
| semantic_code_search_tool | low | LlamaIndex 语义检索 |
| edit_file_tool | high | 修改文件 |
| apply_patch_tool | high | 应用 patch |
| git_diff_tool | low | 查看 diff |
| run_tests_tool | high | Docker 执行测试 |
| run_lint_tool | high | Docker 执行 lint |
| run_typecheck_tool | high | Docker 执行类型检查 |
| create_branch_tool | high | 创建 branch |
| commit_tool | high | commit |
| create_pr_tool | high | 创建 PR |

### 9.2 工具权限策略

| 权限 | 是否需要审批 |
|---|---|
| low | 不需要 |
| medium | 视情况 |
| high | 必须审批或在安全沙箱中执行 |

高风险工具包括：

1. 文件写入。
2. shell 执行。
3. Docker 测试。
4. Git push。
5. PR 创建。
6. 依赖安装。
7. 修改 CI / 配置。

---

## 10. 安全设计

### 10.1 沙箱隔离

1. 每个任务独立 workspace。
2. Docker 容器执行测试。
3. 限制 CPU、内存、超时。
4. 禁止访问宿主机敏感目录。
5. workspace 定期清理。

### 10.2 路径安全

1. 所有文件路径 normalize。
2. 禁止 `../` 路径逃逸。
3. 禁止访问绝对路径。
4. 只能读写 workspace 内文件。

### 10.3 命令安全

危险命令拦截：

```text
rm -rf /
sudo
curl ... | sh
wget ... | sh
cat ~/.ssh/id_rsa
cat ~/.env
docker run --privileged
```

### 10.4 GitHub 安全

1. 默认不 push。
2. 创建 PR 前必须审批。
3. 不允许自动 merge。
4. token 加密存储。
5. 日志中不能输出 token。

### 10.5 Agent 越权防护

1. Coder 只能修改 Planner 批准的文件。
2. 修改计划外文件必须重新审批。
3. Reviewer 检查 scope creep。
4. 所有高风险工具调用写入 audit log。

---

## 11. 数据模型设计

### 11.1 users

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 用户 ID |
| email | varchar | 邮箱 |
| password_hash | varchar | 密码哈希 |
| github_user_id | varchar | GitHub 用户 ID |
| created_at | timestamp | 创建时间 |

### 11.2 fix_tasks

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 任务 ID |
| user_id | uuid | 用户 ID |
| repo_url | text | repo URL |
| issue_url | text | issue URL |
| issue_text | text | issue 内容 |
| base_branch | varchar | 基础分支 |
| status | varchar | pending / running / waiting_approval / success / failed / cancelled |
| current_agent | varchar | 当前 Agent |
| current_node | varchar | 当前节点 |
| retry_count | integer | 重试次数 |
| max_retries | integer | 最大重试次数 |
| workspace_path | text | workspace |
| final_report | text | 最终报告 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 11.3 agent_steps

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | step ID |
| task_id | uuid | 任务 ID |
| agent_name | varchar | Agent 名称 |
| node_name | varchar | 节点名称 |
| status | varchar | running / success / failed / skipped |
| input_summary | jsonb | 输入摘要 |
| output_summary | jsonb | 输出摘要 |
| error_message | text | 错误信息 |
| started_at | timestamp | 开始时间 |
| ended_at | timestamp | 结束时间 |

### 11.4 tool_calls

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | tool call ID |
| task_id | uuid | 任务 ID |
| step_id | uuid | step ID |
| tool_name | varchar | 工具名称 |
| permission_level | varchar | low / medium / high |
| input_summary | jsonb | 输入摘要 |
| output_summary | jsonb | 输出摘要 |
| status | varchar | success / failed |
| duration_ms | integer | 耗时 |
| created_at | timestamp | 创建时间 |

### 11.5 retrieved_contexts

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | context ID |
| task_id | uuid | 任务 ID |
| file_path | text | 文件路径 |
| line_start | integer | 起始行 |
| line_end | integer | 结束行 |
| snippet | text | 代码片段 |
| score | float | 分数 |
| method | varchar | keyword / semantic / hybrid |

### 11.6 edit_history

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | edit ID |
| task_id | uuid | 任务 ID |
| retry_index | integer | 第几次尝试 |
| file_path | text | 文件路径 |
| before_content | text | 修改前内容 |
| after_content | text | 修改后内容 |
| diff | text | diff |
| created_at | timestamp | 创建时间 |

### 11.7 test_runs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | test run ID |
| task_id | uuid | 任务 ID |
| retry_index | integer | 第几次尝试 |
| command | text | 命令 |
| exit_code | integer | 退出码 |
| stdout | text | 标准输出 |
| stderr | text | 错误输出 |
| duration_ms | integer | 耗时 |
| created_at | timestamp | 创建时间 |

### 11.8 approvals

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 审批 ID |
| task_id | uuid | 任务 ID |
| approval_type | varchar | plan / file_write / test_execution / pr_creation / high_risk |
| status | varchar | approved / rejected / cancelled |
| user_comment | text | 用户反馈 |
| created_at | timestamp | 创建时间 |

---

## 12. API 设计

### 12.1 Auth API

```http
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

### 12.2 Task API

```http
POST   /api/fix-tasks
GET    /api/fix-tasks
GET    /api/fix-tasks/{task_id}
DELETE /api/fix-tasks/{task_id}
```

### 12.3 Agent Control API

```http
POST /api/fix-tasks/{task_id}/start
POST /api/fix-tasks/{task_id}/approve
POST /api/fix-tasks/{task_id}/reject
POST /api/fix-tasks/{task_id}/cancel
POST /api/fix-tasks/{task_id}/retry
```

### 12.4 Result API

```http
GET /api/fix-tasks/{task_id}/steps
GET /api/fix-tasks/{task_id}/tool-calls
GET /api/fix-tasks/{task_id}/retrieved-contexts
GET /api/fix-tasks/{task_id}/diff
GET /api/fix-tasks/{task_id}/test-runs
GET /api/fix-tasks/{task_id}/report
GET /api/fix-tasks/{task_id}/patch
```

### 12.5 GitHub API

```http
GET  /api/github/issues
POST /api/github/create-branch
POST /api/github/create-pr
```

---

## 13. 前端页面设计

| 页面 | 路径 | 说明 |
|---|---|---|
| 登录页 | /login | 用户登录 |
| Dashboard | /dashboard | 任务列表 |
| 新建任务 | /tasks/new | 输入 repo 和 issue |
| 任务详情 | /tasks/:id | Agent 执行详情 |
| 审批页 | /tasks/:id/approval | 审批修改计划 |
| Diff 页 | /tasks/:id/diff | 查看代码改动 |
| 测试页 | /tasks/:id/tests | 查看测试日志 |
| Trace 页 | /tasks/:id/trace | Agent Trace |
| 设置页 | /settings | GitHub token、模型配置 |

### 13.1 任务详情页

展示：

1. 当前状态。
2. 当前 Agent。
3. LangGraph 时间线。
4. 每个 Agent 的输入输出摘要。
5. 工具调用记录。
6. 修改计划。
7. 审批操作。
8. diff。
9. 测试日志。
10. 最终报告。

### 13.2 Agent Trace UI

每个节点点击后展示：

1. Agent name。
2. Node name。
3. 输入摘要。
4. 输出摘要。
5. 工具调用。
6. token usage。
7. latency。
8. error message。
9. 关联文件。

---

## 14. Prompt 设计

### 14.1 Issue Analyst Prompt

```text
你是一个资深软件工程师，负责分析 GitHub Issue。
请输出 JSON，不要输出 Markdown。
你需要判断 issue 类型、总结问题、提取验收条件、判断风险等级。
如果信息不足，请设置 needs_user_clarification=true。
```

### 14.2 Planner Prompt

```text
你是一个谨慎的软件修复规划 Agent。
你不能直接修改代码。
你必须基于 issue 分析、项目结构和检索到的代码上下文生成修改计划。
计划必须包含涉及文件、修改原因、测试计划和风险分析。
```

### 14.3 Coder Prompt

```text
你是代码修改 Agent。
你只能修改审批计划中允许的文件。
你必须尽量做最小修改。
你需要遵循项目原有代码风格。
如果需要新增测试，请优先新增或修改测试。
输出 unified diff 或结构化 edit operations。
```

### 14.4 Tester Prompt

```text
你是测试执行 Agent。
你需要运行指定测试命令、lint 和 type check。
你必须输出结构化测试结果，包括 command、exit_code、stdout、stderr、duration_ms。
```

### 14.5 Failure Diagnosis Prompt

```text
你是错误诊断 Agent。
请分析测试失败日志，判断失败是否由当前 patch 导致。
如果可以修复，请给出下一步修复计划。
如果失败与当前 patch 无关或风险过高，请停止重试。
输出 JSON。
```

### 14.6 Reviewer Prompt

```text
你是代码审查 Agent。
请审查 diff 是否符合 issue 目标，是否修改计划外文件，是否存在高风险变更，是否需要更多测试。
输出风险等级和审查意见。
```

---

## 15. 非功能需求

### 15.1 性能要求

| 指标 | MVP 要求 |
|---|---|
| 创建任务响应 | < 3 秒 |
| repo clone | 异步执行 |
| issue 分析 | < 15 秒 |
| 修改计划生成 | < 30 秒 |
| 单次测试运行 | < 120 秒 |
| 单任务最大运行时间 | 15 分钟 |
| 并发任务 | 5 |

### 15.2 可靠性要求

1. 每个任务状态必须持久化。
2. 每个 Agent step 必须持久化。
3. 工具调用失败不能导致系统崩溃。
4. 测试超时必须自动终止。
5. 修改失败必须回滚。
6. 任务中断后可以查看已完成步骤。

### 15.3 可观测性要求

记录：

1. Agent step latency。
2. Tool call latency。
3. LLM token usage。
4. 测试命令。
5. 测试日志。
6. diff 历史。
7. retry 次数。
8. approval 记录。
9. error stack。

---

## 16. 评估指标

### 16.1 产品指标

| 指标 | 目标 |
|---|---|
| Issue 分析成功率 | > 85% |
| 相关文件召回率 | > 70% |
| 修改计划通过率 | > 70% |
| 测试一次通过率 | > 40% |
| 最终自动修复成功率 | > 60% |
| 平均任务完成时间 | < 10 分钟 |
| 高风险误执行次数 | 0 |

### 16.2 Agent 指标

| 指标 | 说明 |
|---|---|
| Tool Call Success Rate | 工具调用成功率 |
| Retrieval Precision | 检索代码是否相关 |
| Retrieval Recall | 是否召回正确文件 |
| Plan Accuracy | 修改计划是否合理 |
| Patch Correctness | patch 是否解决问题 |
| Test Pass Rate | 测试通过率 |
| Retry Effectiveness | 重试后是否改善结果 |
| Reviewer Catch Rate | Reviewer 是否发现风险 |
| Human Intervention Rate | 人工介入频率 |

---

## 17. 里程碑

### Milestone 1：基础任务系统

交付：

1. 用户登录。
2. 创建任务。
3. clone public repo。
4. 任务列表和详情。
5. PostgreSQL 数据表。

### Milestone 2：LangGraph 多 Agent Workflow

交付：

1. State schema。
2. Coordinator Agent。
3. Repository Analyst Agent。
4. Issue Analyst Agent。
5. 基础 workflow routing。
6. Agent step 日志。

### Milestone 3：代码检索和规划

交付：

1. keyword search。
2. 文件读取工具。
3. LlamaIndex 语义检索。
4. Planner Agent。
5. 人工审批。

### Milestone 4：代码修改和测试

交付：

1. Coder Agent。
2. apply patch。
3. git diff。
4. Docker 测试。
5. 测试日志保存。

### Milestone 5：失败自修复和审查

交付：

1. Failure Diagnosis Agent。
2. retry loop。
3. Reviewer Agent。
4. 回滚机制。
5. 风险分级。

### Milestone 6：PR 文案和 GitHub 集成

交付：

1. PR Writer Agent。
2. patch 下载。
3. PR 描述生成。
4. GitHub issue 读取。
5. V1 创建 PR。

### Milestone 7：可观测性和部署

交付：

1. Agent Trace UI。
2. 工具调用审计。
3. 指标面板。
4. Docker Compose。
5. README 和演示视频。

---

## 18. 验收标准

MVP 完成标准：

1. 用户可以创建修复任务。
2. 系统可以 clone public GitHub repo。
3. Repository Analyst 可以分析项目结构。
4. Issue Analyst 可以输出结构化 issue 分析。
5. Code Retriever 可以检索相关代码。
6. Planner 可以生成修改计划。
7. 用户可以审批或拒绝计划。
8. Coder 可以根据计划修改代码。
9. Tester 可以在 Docker 中运行测试。
10. Failure Diagnosis 可以分析失败日志。
11. 系统最多自动重试 2 次。
12. Reviewer 可以审查 diff。
13. PR Writer 可以生成 PR 文案。
14. 前端可以展示完整 Agent 时间线。
15. 项目可以通过 Docker Compose 本地运行。

---

## 19. 可量化指标

建议最终展示：

| 指标 | 示例目标 |
|---|---|
| Agent 数量 | 8-10 个 |
| LangGraph 节点数 | 12-15 个 |
| 工具数量 | 10-14 个 |
| 测试 issue 数量 | 30+ |
| 自动修复成功率 | 60%+ |
| 相关文件召回率 | 75%+ |
| 平均任务耗时 | < 10 分钟 |
| 最大重试次数 | 2 |
| 沙箱超时 | 120 秒 |
| 沙箱内存限制 | 2GB |

---

## 20. 简历写法

```text
FixPilot｜基于 LangGraph 的多 Agent Coding 系统
技术栈：Python、FastAPI、LangGraph、LangChain Tools、LlamaIndex、Docker、GitPython、GitHub API、PostgreSQL、Redis、Next.js

- 基于 LangGraph 设计多 Agent Coding Workflow，将 GitHub Issue 修复流程拆分为需求分析、仓库解析、代码检索、修改计划、代码编辑、测试执行、失败诊断、代码审查和 PR 文案生成等协作节点。
- 设计 Coordinator、Issue Analyst、Repository Analyst、Code Retriever、Planner、Coder、Tester、Reviewer、PR Writer 等 Agent 角色，实现任务路由、状态共享、失败分支处理和有限重试机制。
- 使用 LlamaIndex 构建代码语义检索模块，结合关键词搜索和向量检索定位相关文件，为 Planner Agent 提供候选代码上下文。
- 封装文件读取、代码搜索、代码编辑、git diff、Docker 测试执行和 GitHub PR 生成等工具，使不同 Agent 具备受控的外部执行能力。
- 引入 Docker 沙箱、工具权限分级、用户审批和审计日志机制，对 shell 执行、文件修改、PR 创建等高风险操作进行限制和追踪。
- 构建 Agent Trace 面板，记录用户请求、Agent 输出、工具调用、审批记录、测试日志和最终结果，提升多 Agent 系统的可观测性和可调试性。
```

---

## 21. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Agent 改错文件 | 破坏代码 | 计划审批 + allowed_files 限制 |
| 测试命令危险 | 安全风险 | Docker 沙箱 + 命令黑名单 |
| 代码检索不准 | patch 错误 | keyword + semantic hybrid retrieval |
| LLM 生成无效 diff | patch 失败 | diff 校验 + 回滚 |
| 重试越修越错 | 质量下降 | max_retries 限制 + Reviewer 审查 |
| 私有 repo 权限复杂 | 集成困难 | MVP 只支持 public repo |
| 高风险修改误执行 | 安全风险 | human-in-the-loop + audit log |
| 上下文过长 | 成本高 | 文件摘要 + 代码片段检索 |

---

## 22. 后续扩展方向

1. 支持私有 repo。
2. 支持自动创建 PR。
3. 支持 GitHub Actions 结果读取。
4. 支持多 Agent 并行执行。
5. 支持 Code Review Agent 独立运行。
6. 支持依赖升级 Agent。
7. 支持安全漏洞修复 Agent。
8. 支持浏览器自动化。
9. 扩展成 DevClaw：开发者版多 Agent 自动化助手。
