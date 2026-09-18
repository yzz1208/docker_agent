# Milestone 3：Answer Evaluation v1

## 为什么需要 Answer Eval

Retrieval Eval 只能回答“有没有找到正确资料”。

进入生成阶段以后，还需要单独回答：

1. 模型有没有使用检索到的资料。
2. 引用编号是否合法。
3. 引用的文档是否与人工标注的参考文档重合。
4. 回答是否覆盖关键概念。
5. 回答中的事实是否真正被引用资料支持。
6. 对“必须查看用户本机运行状态才能回答”的问题，模型能否承认文档证据不足。

因此 Answer Eval 分成两层。

## 第一层：Deterministic metrics

不再调用额外 Judge 模型，结果稳定且可重复。

当前指标：

- citation_presence_rate：回答是否至少包含一个合法引用。
- mean_cited_sources：平均实际引用来源数。
- retrieved_expected_source_hit_rate：Top-5 是否包含人工标注参考文档。
- cited_expected_source_hit_rate：模型最终实际引用的来源是否包含参考文档。
- mean_expected_source_recall：多个参考文档场景下的来源覆盖率。
- mean_concept_coverage：回答是否包含人工定义的关键概念组。

这些指标不能证明自然语言事实完全正确，但适合做回归测试。

## 第二层：Optional LLM-as-judge

使用 --judge 开启。

Judge 只能依据本次检索 Context 评价，不允许使用外部 Docker 知识。当前输出：

- groundedness：1-5
- citation_correctness：1-5
- completeness：1-5
- insufficient_evidence_handling：pass / fail / not_applicable
- unsupported_claims
- rationale

当前默认使用与回答相同的模型作为 Judge，因此这些分数只作为诊断指标，不视为 gold label。后面可以增加独立 Judge 模型配置或人工抽查。

## answer_v1 数据集

文件：

data/eval/answer_v1.jsonl

第一版共 10 条：

- Compose startup order
- Docker daemon connection
- volume vs bind mount
- memory limit
- tmpfs
- port publishing
- Compose env precedence
- restart policy
- 本机容器当前内存（不可仅靠文档回答）
- 本机容器某次重启的真实原因（不可仅靠文档回答）

最后两条用于验证一个非常重要的边界：

文档 RAG 不应该假装知道用户当前 Docker runtime 的真实状态。

这也是后续 Agent Tool Calling 的切入点。

## 运行

先同步代码：

~~~powershell
git pull --ff-only
uv run ruff check .
uv run pytest -v
~~~

先跑 3 条，不使用 Judge：

~~~powershell
uv run python scripts/eval_answers.py --limit 3
~~~

结果会写入：

reports/answer_eval_latest.jsonl

reports/ 已经在 .gitignore 中，不会把实际模型输出误提交进仓库。

确认前 3 条正常后，跑完整 deterministic eval：

~~~powershell
uv run python scripts/eval_answers.py
~~~

然后再进行 LLM-assisted eval：

~~~powershell
uv run python scripts/eval_answers.py --judge
~~~

如果希望先控制调用量：

~~~powershell
uv run python scripts/eval_answers.py --limit 3 --judge
~~~

## 如何读结果

例如：

~~~text
[compose-startup-order-zh] citations=3 source_hit=True concepts=1.00
~~~

表示：

- 模型实际用了 3 个引用。
- 至少一个引用命中了人工标注的 startup-order 文档。
- 两个要求的关键概念 service_healthy / healthcheck 都出现在答案里。

Judge 模式还会增加：

~~~text
grounded=5/5 citation=5/5 complete=5/5
~~~

Summary 中最先关注：

1. generation_failures 是否为 0。
2. citation_presence_rate 是否接近 1。
3. cited_expected_source_hit_rate 是否较高。
4. mean_concept_coverage 是否较高。
5. groundedness / citation_correctness 是否稳定。
6. 两条 runtime-only case 的 insufficient_evidence_pass_rate 是否通过。

## 当前限制

- required_concept_groups 是字符串级检查，不是语义判断。
- expected_file_paths 是人工参考路径，不代表其他 Docker 官方页面一定无效。
- 同一模型做 Answer 和 Judge 会有自评偏差。
- 10 条 case 只适合作为第一版回归集，后续需要扩充。
- Citation Guard 只能保证 [n] 存在，不能替代 citation correctness 语义评测。

## 下一阶段

当 Answer Eval 稳定后，进入 Docker Tool Calling：

~~~text
User Question
     ↓
Need runtime evidence?
  ┌──┴──┐
 no    yes
 │      │
RAG   docker ps / inspect / logs / stats
 │      │
 └──┬───┘
    ↓
Grounded diagnosis
~~~

届时 runtime-only 的两条 case 将从“应该承认无法判断”变成“Agent 应主动调用只读 Docker 工具收集证据”。
