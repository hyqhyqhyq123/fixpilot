# FixPilot 总评估报告

> 数据源：真实 SWE-bench Lite rows。
> 下载来源：`https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Lite&config=default&split=test&offset=0&length=5`
> 本地数据文件：`backend/test/fixtures/swebench_lite_rows_sample.json`
> 评估范围：数据集质量、RAG 文件定位、工程回归门禁、单样本 Docker oracle patch 闭环。完整 FixPilot 生成 patch 的 SWE-bench resolve rate 仍需要后续接官方 harness。

## 1. 为什么用 SWE-bench

SWE-bench 的样本来自真实 GitHub issue / pull request，每条样本包含：

- `repo`：真实 GitHub 仓库
- `base_commit`：问题发生时的代码版本
- `problem_statement`：真实 issue 描述
- `patch`：人工修复 patch
- `test_patch`：验证修复的测试 patch
- `FAIL_TO_PASS`：修复前失败、修复后应该通过的测试
- `PASS_TO_PASS`：修复前后都应该保持通过的回归测试

这比自造样本更适合回答面试官追问：你的 Agent 是否能面对真实开源项目问题。

## 2. 数据集概览

| 指标 | 数值 |
|---|---:|
| SWE-bench Lite 样本数 | 5 |
| 唯一仓库数 | 1 |
| FAIL_TO_PASS 测试总数 | 7 |
| PASS_TO_PASS 测试总数 | 220 |
| 平均 issue 字符数 | 1487.6 |
| 平均 oracle patch 文件数 | 1.00 |
| 平均 test patch 文件数 | 1.20 |

当前子集均来自 `astropy/astropy`，用于先验证评估链路。后续可以把 `length=5` 改大，或替换成本地完整 SWE-bench JSONL。

## 3. 评估方法

### RAG 文件定位

目标：给定 issue 描述，系统是否能把真正需要修改的源码文件排在前面。

评估方式：

- 使用 SWE-bench 的 `patch` 文件路径作为 oracle relevant files。
- 使用 `problem_statement` 作为 query。
- baseline：朴素 `test-first` 排序，先看测试文件，再看源码文件。
- FixPilot 离线定位器：使用 issue 文本和候选路径 token 匹配，并对源码文件加权。

指标：

- `Recall@1`：Top 1 是否命中需要修改的文件。
- `Recall@3`：Top 3 是否覆盖需要修改的文件。
- `Hit@1`：Top 1 是否至少命中一个正确文件。
- `MRR@3`：正确文件越靠前，分数越高。

### SWE-bench 端到端修复

完整端到端指标应该是 `resolve_rate`：

- Agent 生成 patch。
- 官方 SWE-bench harness 在 Docker 环境应用 patch。
- `FAIL_TO_PASS` 全部通过。
- `PASS_TO_PASS` 不回归。

当前本地已跑通 1 条真实 SWE-bench Lite 样本的 Docker oracle patch 闭环，用来验证评测环境、补丁应用和 `FAIL_TO_PASS` 测试链路。这里仍不伪造 FixPilot 自生成 patch 的 resolve rate，只提供 `evaluate_swebench_predictions()` 适配器，后续可直接接官方结果。

## 4. RAG 文件定位结果

| 方法 | Recall@1 | Recall@3 | Hit@1 | MRR@3 |
|---|---:|---:|---:|---:|
| test-first baseline | 0.000 | 1.000 | 0.000 | 0.467 |
| FixPilot source-aware locator | 1.000 | 1.000 | 1.000 | 1.000 |

提升：

- Recall@1：`+1.000`
- MRR@3：`+0.533`

解释：

- baseline 更容易先看到测试文件，但真正要改的是源码文件。
- FixPilot 的 source-aware 定位策略会把源码文件排到测试文件前面。
- 在这 5 条真实 SWE-bench Lite 样本上，Top 1 文件定位从完全不命中提升到全部命中。

## 5. 工程回归门禁

本轮新增评估测试：

```powershell
.\.venv\Scripts\python.exe -m pytest --override-ini addopts= backend\test\test_real_issue_rag_benchmark.py -s
```

结果：

```text
4 passed in 0.09s
```

覆盖内容：

- SWE-bench Lite fixture schema 是否真实可解析。
- oracle patch/test 字段是否存在。
- 文件定位指标是否可复现。
- SWE-bench `resolve_rate` 适配器是否能评估官方 harness 结果。
- Markdown 报告是否包含数据源、方法、指标和测试记录。

## 6. 单样本 Docker Oracle 闭环

本轮额外跑了 1 条真实 SWE-bench Lite 样本，验证“真实仓库 + base commit + 测试补丁 + oracle 修复补丁 + Docker pytest”的闭环。

命令：

```powershell
.\.venv\Scripts\python.exe backend\test\run_swebench_oracle_single.py --index 0 --run-id full2 --timeout 1800
```

样本：

- `instance_id`：`astropy__astropy-12907`
- `repo`：`astropy/astropy`
- `base_commit`：`d16bfe05a744909de4b27f5875fe0d4ed41ce607`
- 输出：`outputs/swebench_oracle/astropy__astropy-12907_full2/result.json`

结果：

| 阶段 | 结果 | 关键输出 |
|---|---:|---|
| clone 真实仓库 | 通过 | `exit_code=0` |
| checkout base commit | 通过 | `exit_code=0` |
| apply test_patch | 通过 | `exit_code=0` |
| base 上运行 FAIL_TO_PASS | 符合预期失败 | `2 failed in 2.32s` |
| apply oracle patch | 通过 | `exit_code=0` |
| oracle 后运行 FAIL_TO_PASS | 通过 | `2 passed in 1.45s` |

结论：

- `baseline_failed_as_expected=true`
- `oracle_passed=true`
- oracle patch 单样本闭环通过：`1/1`
- 这证明评测 runner 能真实 clone GitHub 仓库、复现失败测试，并验证人工修复 patch。
- 这还不是 FixPilot 自己生成 patch 的 resolve rate；它是 oracle patch 环境校验。

为了让历史项目可复现，runner 里补了这些工程细节：

- Docker 镜像固定为 `python:3.10-bullseye`，避免新系统编译器对旧 C 扩展过严。
- `setuptools<60`，兼容 astropy 旧 commit 中的 `setuptools.dep_util`。
- `numpy==1.21.6`，兼容旧 Cython/NumPy C API。
- 安装 `pytest-astropy` 和 `hypothesis`，满足项目自己的测试配置。
- 支持 `--run-id`，避免 Windows 上旧 Docker 输出目录锁文件影响重复评测。

## 7. 当前限制

- 当前只下载了 SWE-bench Lite 的 5 条 rows，用于先把评估链路跑通。
- 当前完整 Docker 闭环只跑了 1 条 oracle patch 样本。
- 当前没有评估 FixPilot 自己生成 patch 的官方 `resolve_rate`。
- 当前单样本闭环只跑 `FAIL_TO_PASS`，还没有跑完整 `PASS_TO_PASS` 回归集合。

## 8. 下一步

更完整的评估路线：

1. 下载完整 `princeton-nlp/SWE-bench_Lite` test split。
2. 对每条样本 clone `repo` 并 checkout `base_commit`。
3. 让 FixPilot 跑完整 Agent workflow，生成 patch。
4. 把 patch 交给 SWE-bench 官方 harness。
5. 统计 `resolve_rate`、`FAIL_TO_PASS pass rate`、`PASS_TO_PASS regression rate`。
6. 分别记录 RAG file localization、plan approval、tool audit、test pass、最终 resolve 的漏斗指标。

## 9. 面试回答短句

- 我没有用自造样本做总评估，评估输入来自 SWE-bench Lite 的真实 GitHub issue / PR rows。
- RAG 文件定位使用 oracle patch 文件作为正确答案，指标用 Recall@K 和 MRR@K。
- 当前子集上，FixPilot 的 source-aware 文件定位 Recall@1 从 `0.000` 提升到 `1.000`。
- 我已经跑通 1 条真实 SWE-bench Lite 样本的 Docker oracle patch 闭环：base 上 `2 failed`，oracle 后 `2 passed`。
- 完整 FixPilot 自生成 patch 的 SWE-bench resolve rate 我没有伪造，已经预留预测结果适配器，后续接官方 harness 输出即可。
