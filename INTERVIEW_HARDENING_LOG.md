# FixPilot Interview Hardening Log

> 目的：记录面向面试追问的工程补强、量化指标和测试结果。
> 最近更新：2026-06-14

## 参考追问来源

- 公开面经 / 招聘方向常见追问：RAG 是否真有必要、有没有离线评测、Agent 是否乱调工具、后端任务系统是否可靠、数据库有没有索引和事务意识。
- RAG 相关研究指出：RAG 需要系统化评测，常见维度包括检索准确性、生成忠实度、噪声鲁棒性和负样本拒答。
- RAG / Agent 安全资料反复强调：检索到的外部文档可能携带间接 prompt injection，需要在进入 LLM 前做检测、过滤或隔离。

## Round 1：RAG 检索效果可量化

面试官可能问：

- 你怎么证明 hybrid 比 semantic 好？
- 你的 RAG 有没有固定评测集？
- 你的优化提升了多少，不会只是感觉更好吧？

已补强：

- 新增 `backend/app/services/retrieval_benchmark.py`
- 新增 `backend/test/test_retrieval_benchmark.py`
- 指标：Recall@1、Recall@3、Hit@1、Hit@3、MRR@3、平均耗时、平均文件读取次数
- 对比方法：semantic、keyword、BM25、naive_hybrid、optimized_hybrid

量化结果：

| 方法 | Recall@1 | Recall@3 | MRR@3 | avg_file_reads |
|---|---:|---:|---:|---:|
| semantic | 0.000 | 1.000 | 0.500 | 0.00 |
| keyword | 1.000 | 1.000 | 1.000 | 8.00 |
| BM25 | 1.000 | 1.000 | 1.000 | 8.00 |
| naive_hybrid | 1.000 | 1.000 | 1.000 | 16.00 |
| optimized_hybrid | 1.000 | 1.000 | 1.000 | 8.00 |

结论：

- optimized_hybrid 相比 semantic：Recall@1 从 0.000 到 1.000，提升 100 个百分点。
- optimized_hybrid 相比 naive_hybrid：文件读取次数从 16 降到 8，下降 50%。

## Round 2：主 Workflow 真正接入 hybrid

面试官可能问：

- 你是不是只写了 hybrid 工具，主流程还是 semantic？
- README 和真实执行链路一致吗？

已补强：

- `backend/app/graph/nodes.py` 中 `retrieve_context_node` 改为 `search_method="hybrid"`
- `backend/test/test_workflow.py` 增加断言，确认主链路使用 hybrid

测试结论：

- `retrieve_context_node` 主链路已使用 hybrid。

## Round 3：Agent 工具调用可审计、可量化

面试官可能问：

- Agent 会不会乱调用高风险工具？
- 高风险工具是否有保护手段？
- 工具调用有没有审计数据？

已补强：

- 新增 `backend/app/services/tool_audit_metrics.py`
- 新增 `backend/test/test_tool_audit_metrics.py`
- 指标：工具调用总数、成功率、高风险调用占比、高风险失败数、未知工具数、高风险保护覆盖率、平均耗时

示例指标：

```text
ToolAudit: total=4, success_rate=0.750, high_risk_rate=0.750, guarded_high_risk_rate=0.667, unknown_tool_calls=1, avg_duration_ms=397.5
```

结论：

- 可以把“Agent 是否乱调工具”转成可解释的审计指标。
- 未知工具会被识别出来，不能悄悄当成低风险工具。

## Round 4：数据库查询索引

面试官可能问：

- 你只会建表吗？高频查询有没有索引？
- 任务列表、Trace、工具审计、检索结果怎么查？

已补强：

- `fix_tasks(status, created_at)`：任务列表按状态过滤和时间排序
- `fix_tasks(created_at)`：任务列表默认倒序
- `agent_steps(task_id, started_at)`：Trace 时间线
- `tool_calls(task_id, created_at)`：工具审计时间线
- `retrieved_contexts(task_id, score, id)`：检索结果按分数排序
- 新增 `backend/test/test_db_indexes.py`

测试结论：

- 高频任务列表 / Trace / 工具审计 / 检索结果查询均声明复合索引。

## Round 5：RAG Prompt Injection 防线

面试官可能问：

- 如果检索到的 README / 注释里写了“忽略之前指令”，Planner 会不会照做？
- RAG 投毒你怎么防？

已补强：

- 新增 `backend/app/services/prompt_injection_guard.py`
- `backend/app/agents/planner.py` 在拼接 retrieved snippet 前做检测和 redaction
- 新增 `backend/test/test_prompt_injection_guard.py`

覆盖规则：

- instruction override：忽略 / 覆盖系统指令
- role hijack：让模型扮演 system/developer/admin/root
- secret exfiltration：要求泄露 token / api key / env
- tool abuse：要求执行 shell / sudo / curl / rm -rf
- prompt marker：system prompt / developer message / jailbreak 等提示注入标记

测试结论：

- 正常代码保留。
- 恶意行被替换为 `[redacted possible prompt injection: ...]`。
- Planner prompt 中不会原样注入恶意 RAG 片段。

## Round 6：RAG 证据充分性与负样本防线

面试官可能问：

- 如果 RAG 没检索到证据，Agent 会不会硬编？
- 你怎么判断“证据够不够”，有没有结构化字段？
- 低置信度检索结果会不会直接进入 Planner 当成确定事实？

已补强：

- 新增 `backend/app/services/retrieval_sufficiency.py`
- `backend/app/graph/state.py` 增加 `retrieval_quality`
- `backend/app/graph/nodes.py` 在 `retrieve_context_node` 后输出检索质量评估
- `backend/app/agents/planner.py` 在证据不足时给 Planner 加“不确定性提示”
- 新增 `backend/test/test_retrieval_sufficiency.py`

量化字段：

- `sufficient`：证据是否足够
- `level`：`none` / `low` / `high`
- `evidence_count`：证据条数
- `unique_files`：命中的唯一文件数
- `top_score`：最高检索分数
- `reasons`：证据不足的具体原因

测试结论：

- 空检索会被标记为 `sufficient=false`、`level=none`。
- 高分检索会被标记为 `sufficient=true`、`level=high`。
- Planner 在证据不足时会提示“不要编造未检索到的文件或函数”。
- 主 Workflow 的 `retrieve_context_node` 会输出 `retrieval_quality`。

## Round 7：任务状态机门禁集中化

面试官可能问：

- 任务状态能不能乱跳，比如 cancelled 又重新 running？
- running 任务会不会被用户重复 start，导致两个 Worker 同时跑？
- failed 任务重试有没有上限，还是能无限 retry？
- Celery 开关不同的时候，状态门禁会不会不一致？

已补强：

- 新增 `backend/app/services/task_state_machine.py`
- `backend/app/services/workflow_queue.py` 复用统一启动、审批继续、失败重试门禁
- `backend/app/services/workflow_runner.py` 复用统一启动、失败重试、取消门禁
- 新增 `backend/test/test_task_state_machine.py`

覆盖规则：

- `pending / failed -> running`：允许启动或失败重试
- `waiting_approval -> running`：只允许审批后继续
- `running -> waiting_approval / success / failed / cancelled`：允许主流程推进或取消
- `failed -> running`：允许在 `max_retries` 内重试
- `cancelled -> running`：拒绝

本轮测试记录：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\test\test_task_state_machine.py backend\test\test_workflow_completion.py backend\test\test_workflow.py backend\test\test_celery_tasks.py -q -s
```

```text
21 passed in 2.64s
```

测试结论：

- 状态机规则可被单独测试和解释。
- Celery worker 场景允许 `running` resume，但普通重复启动仍会被拒绝。
- failed 任务重试会检查状态和 `max_retries`，达到上限后拒绝。
- Workflow cancel 允许 running 任务取消，但拒绝已经 success 的任务。

## Round 8：Agent Trace 汇总指标

面试官可能问：

- Agent 慢在哪里，你怎么定位？
- 哪个节点失败了，能不能从结构化数据里看出来？
- LLM 调用大概用了多少 token，有没有成本意识？
- Trace 只是日志，还是能转成指标？

已补强：

- 新增 `backend/app/services/trace_metrics.py`
- 新增 `backend/test/test_trace_aggregate_metrics.py`
- 复用已有 `backend/test/test_trace_metrics.py` 的单步 latency / token / related_files 覆盖

量化字段：

- `total_steps`：节点总数
- `success_rate`：步骤成功率
- `failed_nodes`：失败节点列表
- `total_latency_ms` / `avg_latency_ms`：总耗时和平均耗时
- `slowest_node` / `slowest_latency_ms`：最慢节点
- `total_prompt_tokens` / `total_completion_tokens` / `total_tokens`：LLM token 汇总

本轮测试记录：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\test\test_trace_aggregate_metrics.py backend\test\test_trace_metrics.py -q -s
```

```text
5 passed in 0.22s
```

测试结论：

- 示例 Trace 汇总结果：`success_rate=0.500`、`slowest=planning_node:340ms`、`total_tokens=360`。
- 空 Trace 默认无失败、无耗时、无 token，避免监控页因为空数据报错。

## Round 9：Alembic 数据库迁移

面试官可能问：

- 线上数据库表结构怎么升级，不会靠 `create_all` 吧？
- 索引和新表怎么版本化？
- 能不能回滚？

已补强：

- 新增 `backend/alembic.ini`
- 新增 `backend/alembic/env.py`
- 新增 `backend/alembic/versions/20260614_0001_initial_schema.py`
- 新增 `backend/alembic/versions/20260614_0002_code_embedding_pgvector.py`
- 新增 `backend/test/test_alembic_migrations.py`

测试结论：

- 临时 SQLite 数据库实际执行 `upgrade head`。
- 能创建 `fix_tasks`、`agent_steps`、`tool_calls`、`workflow_checkpoints` 等核心表。
- 能执行 `downgrade base` 回滚。
- pgvector 迁移在 SQLite 下 no-op，在 PostgreSQL 下创建 `vector` 扩展和 `code_embeddings` 表。

## Round 10：质量门禁与 CI

面试官可能问：

- 你怎么保证不是本地能跑、提交就坏？
- 有没有 lint、类型检查、覆盖率、CI？
- 前端和后端是不是都进流水线？

已补强：

- 新增 `pyproject.toml`：pytest / coverage / Ruff / mypy 配置
- 新增 `backend/requirements-dev.txt`
- 新增 `.pre-commit-config.yaml`
- 新增 `.github/workflows/ci.yml`
- 新增 `backend/test/test_quality_gate_config.py`

测试结论：

- 配置中包含 Ruff、mypy、coverage、pytest。
- pre-commit 包含 Ruff、mypy、后端聚焦测试。
- GitHub Actions 包含后端 lint/type/migration/test 和前端 lint/build。

## Round 11：Prometheus / OpenTelemetry 可观测性

面试官可能问：

- 线上怎么知道请求量、错误率、慢接口？
- Agent 项目出了问题，你是看日志猜，还是有指标？
- OpenTelemetry collector 没部署时应用会不会启动失败？

已补强：

- 新增 `backend/app/core/observability.py`
- `backend/app/main.py` 接入 `setup_observability`
- `backend/app/core/config.py` 增加 `enable_prometheus`、`enable_opentelemetry` 等配置
- `backend/requirements.txt` 增加 Prometheus / OpenTelemetry 依赖声明
- 新增 `backend/test/test_observability.py`

测试结论：

- `/metrics` 输出 Prometheus 文本格式。
- 能统计 `fixpilot_http_requests_total` 和 `fixpilot_http_request_duration_seconds`。
- OpenTelemetry 是可选启用；依赖缺失时不会拖垮 FastAPI 启动。

## Round 12：PostgreSQL pgvector 向量持久化

面试官可能问：

- 你的向量检索是不是只在内存里跑，服务重启怎么办？
- 为什么不用 Milvus/Qdrant？
- embedding 表怎么设计，有没有索引和 upsert？

已补强：

- 新增 `backend/app/services/vector_store.py`
- 新增 pgvector Alembic 迁移 `20260614_0002_code_embedding_pgvector.py`
- `docker-compose.yml` 的 PostgreSQL 镜像改为 `pgvector/pgvector:pg15`
- `backend/requirements.txt` 增加 `pgvector`
- 新增 `backend/test/test_vector_store_pgvector.py`

量化/工程点：

- `code_embeddings` 表包含 `repo_url`、`file_path`、`chunk_id`、`content_hash`、`embedding vector(1536)`。
- 唯一约束：`repo_url, file_path, chunk_id, content_hash`。
- 相似度索引：`ivfflat (embedding vector_cosine_ops)`。
- 查询使用 `embedding <=> :embedding` cosine distance 排序。
- SQL 构建器拒绝非法表名，避免标识符注入。

## Round 13：pgvector 接入检索主链路

面试官可能问：

- 你说有 pgvector，那真实检索会用它吗？
- hybrid 是不是还是只有 semantic / keyword / BM25？
- 向量库挂了会不会影响默认本地检索？

已补强：

- `CodeRetrievalRequest.search_method` 增加 `pgvector`
- `RetrievedFile.method` 增加 `pgvector`
- `backend/app/agents/code_retriever.py` 增加 `_retrieve_pgvector`
- `VECTOR_STORE_PROVIDER=pgvector` 时，`hybrid` 会把 pgvector 作为第四路召回参与 RRF
- `backend/test/test_vector_store_pgvector.py` 增加主链路测试

测试结论：

- `search_method=pgvector` 会查询持久化向量表并返回 `RetrievedFile`。
- `VECTOR_STORE_PROVIDER=pgvector` 时，hybrid 会融合 pgvector 召回。
- 默认配置仍保持本地 hybrid，不强依赖 pgvector 数据库可用。

## Round 14：Agent 指标进入 Prometheus

面试官可能问：

- 你怎么知道 Planner 慢，还是 Coder 慢？
- 每个 LangGraph node 的成功/失败有没有指标？
- LLM token 用在哪些节点？

已补强：

- `backend/app/core/observability.py` 增加 `AgentMetrics`
- `backend/app/services/workflow_runner.py` 在持久化 step 时写入 Agent metrics
- `/metrics` 现在同时输出 HTTP 指标和 Agent 指标
- `backend/test/test_observability.py` 增加 Agent metrics 测试

新增指标：

- `fixpilot_agent_steps_total{node,status}`
- `fixpilot_agent_step_duration_seconds_sum/count{node}`
- `fixpilot_agent_tokens_total{node,type}`

测试结论：

- Agent metrics 能输出节点状态、耗时和 token。
- workflow_runner 的 step record 可直接写入 Agent metrics。

## Round 15：任务状态流转审计

面试官可能问：

- 状态机会不会被某个内部函数绕过？
- task 从 pending 到 running、failed 到 running 有没有审计？
- cancelled 能不能重新 running？

已补强：

- 新增 `backend/app/models/task_status_transition.py`
- 新增 `backend/app/services/task_status_audit.py`
- 新增 Alembic 迁移 `20260614_0003_task_status_transitions.py`
- `workflow_queue.py` / `workflow_runner.py` 的关键入口接入状态流转审计
- 新增 `backend/test/test_task_status_audit.py`
- `backend/test/test_db_indexes.py` 增加状态审计索引断言

测试结论：

- 合法状态流转会写入 `task_status_transitions`。
- 非法 `cancelled -> running` 会被拒绝且不写审计。
- 状态审计表有 `task_id, created_at` 复合索引，适合按任务查时间线。

## Round 16：真实 SWE-bench Lite 总评估数据集

面试官可能问：

- 你的评估样本是不是自己编的？
- 能不能用 SWE-bench 这种真实 GitHub issue / PR 数据？
- 端到端 resolve rate 和 RAG 文件定位怎么区分？

已补强：

- 从 Hugging Face datasets-server 下载真实 `princeton-nlp/SWE-bench_Lite` rows
- 新增 `backend/test/fixtures/swebench_lite_rows_sample.json`
- 新增 `backend/app/services/project_evaluation.py`
- 重写 `backend/test/test_real_issue_rag_benchmark.py`
- 新增 `FIXPILOT_EVALUATION_REPORT.md`

数据集概览：

| 指标 | 数值 |
|---|---:|
| SWE-bench Lite 样本数 | 5 |
| 唯一仓库数 | 1 |
| FAIL_TO_PASS 测试总数 | 7 |
| PASS_TO_PASS 测试总数 | 220 |
| 平均 issue 字符数 | 1487.6 |
| 平均 oracle patch 文件数 | 1.00 |

量化结果：

| 方法 | Recall@1 | Recall@3 | Hit@1 | MRR@3 |
|---|---:|---:|---:|---:|
| test-first baseline | 0.000 | 1.000 | 0.000 | 0.467 |
| FixPilot source-aware locator | 1.000 | 1.000 | 1.000 | 1.000 |

测试结论：

- 当前总评估输入来自真实 SWE-bench Lite rows，不再使用自造 issue 风格样本。
- SWE-bench file localization 子集上，FixPilot Recall@1 相比 baseline 提升 100 个百分点。
- `evaluate_swebench_predictions()` 已支持接入官方 harness 输出后的 resolve_rate 计算。
- 完整 SWE-bench resolve rate 尚未伪造，需要后续接官方 Docker harness 跑 patch。

## Round 17：SWE-bench 单样本 Docker Oracle 闭环

面试官可能问：

- 你只是算了离线定位指标，还是能真的 clone 仓库跑测试？
- `FAIL_TO_PASS` 是否真的在 base commit 上失败、在修复 patch 后通过？
- 历史开源项目依赖环境很复杂，你的评测环境能不能复现？

已补强：

- 新增 `backend/test/run_swebench_oracle_single.py`
- 支持真实 clone GitHub 仓库、checkout `base_commit`、应用 `test_patch`、运行 `FAIL_TO_PASS`、应用 oracle `patch`、再次运行 `FAIL_TO_PASS`
- Docker 镜像固定为 `python:3.10-bullseye`
- 为 astropy 旧 commit 固定 `setuptools<60`、`numpy==1.21.6`、`pytest-astropy>=0.9`、`hypothesis`
- 增加 `--run-id`，避免 Windows 上旧 Docker 输出目录锁文件影响重复评测

本轮测试记录：

```powershell
.\.venv\Scripts\python.exe backend\test\run_swebench_oracle_single.py --index 0 --run-id full2 --timeout 1800
```

样本：

- `instance_id=astropy__astropy-12907`
- `repo=astropy/astropy`
- `base_commit=d16bfe05a744909de4b27f5875fe0d4ed41ce607`
- 结果文件：`outputs/swebench_oracle/astropy__astropy-12907_full2/result.json`

量化结果：

| 阶段 | 结果 |
|---|---|
| clone / checkout / apply test_patch | 通过 |
| base 上运行 FAIL_TO_PASS | `2 failed in 2.32s` |
| apply oracle patch | 通过 |
| oracle 后运行 FAIL_TO_PASS | `2 passed in 1.45s` |

测试结论：

- `baseline_failed_as_expected=true`
- `oracle_passed=true`
- 单样本 oracle patch 闭环：`1/1`
- 这证明评测 runner 能真实复现失败并验证人工修复 patch。
- 这仍不是 FixPilot 自生成 patch 的官方 resolve rate，不能夸大为模型已解决 SWE-bench。

## 最新完整测试记录

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest --override-ini addopts= backend\test\test_alembic_migrations.py backend\test\test_quality_gate_config.py backend\test\test_observability.py backend\test\test_vector_store_pgvector.py backend\test\test_task_status_audit.py backend\test\test_real_issue_rag_benchmark.py backend\test\test_trace_aggregate_metrics.py backend\test\test_trace_metrics.py backend\test\test_task_state_machine.py backend\test\test_retrieval_sufficiency.py backend\test\test_prompt_injection_guard.py backend\test\test_retrieval_benchmark.py backend\test\test_tool_audit_metrics.py backend\test\test_db_indexes.py backend\test\test_workflow.py backend\test\test_workflow_completion.py backend\test\test_hybrid_bm25_rrf.py backend\test\test_query_rewrite.py backend\test\test_rerank.py backend\test\test_tool_permissions.py -s
```

结果：

```text
71 passed in 2.44s
```

## 目前可用于面试回答的短句

- 我没有只说“用了 RAG”，而是补了固定样例离线评测，记录 Recall@K、MRR、耗时和文件读取次数。
- 主 Workflow 已从 semantic 切到 hybrid，README 能力和真实链路一致。
- Agent 工具调用不是黑盒，能统计成功率、高风险占比、未知工具数和保护覆盖率。
- 高频查询路径补了复合索引，并用测试锁住索引设计。
- RAG 上下文进入 Planner 前有 prompt injection 检测和 redaction，避免把仓库恶意注释当系统指令。
- RAG 找不到足够证据时会产出 `retrieval_quality`，Planner 会显式带着不确定性规划，避免把低置信度检索当事实。
- 任务状态机有集中门禁和单测，能解释重复启动、审批继续、失败重试、取消这些关键状态转换。
- Trace 不只是一串日志，可以汇总为成功率、失败节点、最慢节点、平均耗时和 token 用量。
- 数据库结构有 Alembic 迁移链，能 upgrade/downgrade，不再只靠 `create_all`。
- CI / pre-commit / Ruff / mypy / coverage 已有配置，能把质量门禁前移到提交和 PR。
- `/metrics` 暴露 Prometheus 指标，OpenTelemetry 可选接入，不会因为依赖缺失影响启动。
- 向量持久化选择 pgvector，复用 PostgreSQL，避免为项目早期额外维护 Milvus/Qdrant 集群。
- pgvector 已可作为独立 `search_method`，也能在配置开启时并入 hybrid 主链路。
- Agent metrics 已进入 `/metrics`，能按 node 统计成功/失败、耗时和 token。
- 关键任务状态流转会写入审计表，非法状态转换会被状态机拒绝。
- 总评估样本已切换为真实 SWE-bench Lite rows；当前子集 file localization Recall@1 从 0.000 提升到 1.000。
