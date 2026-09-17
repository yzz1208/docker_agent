# Milestone 2：Dense / Keyword / Hybrid 检索实验

## 1. 为什么现在加入 Keyword Retrieval

`retrieval_v2.jsonl` 的 37 条真实场景评测显示，BGE-M3 dense baseline 为：

```text
Document Hit@1 = 0.6216
Document Hit@3 = 0.8108
Document Hit@5 = 0.8649
Document MRR   = 0.7207

Section Hit@1 = 0.4545
Section Hit@3 = 0.5455
Section Hit@5 = 0.6364
Section MRR   = 0.5182
```

失败样本中包含很多 Docker 技术词：

- `iptables`
- `env_file`
- `DOCKER_HOST`
- `exit code 137`
- `tmpfs`
- `daemon.json`
- `secrets`

Dense retrieval 擅长语义和中英文跨语言匹配，但对精确技术 token、命令名、配置字段并不总是稳定。因此这一轮加入 PostgreSQL Full Text Search 作为 lexical retriever。

## 2. 为什么 Keyword 不是 Dense 的替代品

Docker 文档主要是英文，而用户大量使用中文。

例如：

```text
容器删掉以后数据还要保留怎么办
```

这类 query 可能没有任何可用于英文全文检索的 ASCII 技术词，但 BGE-M3 可以做跨语言语义检索。

因此系统设计是：

```text
Dense Retrieval  ─┐
                  ├─> Reciprocal Rank Fusion -> Top-K
Keyword Retrieval ─┘
```

Keyword retrieval 主要补充精确技术词，而不是独立承担中文语义检索。

## 3. Keyword Retrieval

实现位置：

```text
src/docker_agent/rag/store.py
```

流程：

```text
Query
  ↓
提取 ASCII 技术 token
  ↓
PostgreSQL to_tsquery('simple', ...)
  ↓
title + section_path + content
  ↓
ts_rank_cd
  ↓
Keyword Top-K
```

查询词之间使用 OR，而不是 AND。

原因是混合中文问题中可能只有少数技术词真正出现在英文文档中。Keyword retrieval 的目标是扩大 lexical candidate recall，后续由 Hybrid Fusion 决定最终排序。

## 4. Reciprocal Rank Fusion

当前 Hybrid 使用 RRF，不直接把 cosine similarity 与 PostgreSQL `ts_rank_cd` 相加。

原因是两套 score 不在同一尺度：

```text
Dense: cosine similarity / distance
Keyword: ts_rank_cd
```

直接归一化或加权容易引入人为尺度假设。

RRF 只使用排名：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

当前默认：

```text
candidate_k = 20
rrf_k = 60
```

这些参数先作为 baseline，不提前调参。只有在评测结果出来之后再决定是否调整。

## 5. 单条查询对比

Dense：

```powershell
uv run python scripts/search_docs.py "为什么启动 Docker 后 iptables 规则被改了？" --mode dense --top-k 5
```

Keyword：

```powershell
uv run python scripts/search_docs.py "为什么启动 Docker 后 iptables 规则被改了？" --mode keyword --top-k 5
```

Hybrid：

```powershell
uv run python scripts/search_docs.py "为什么启动 Docker 后 iptables 规则被改了？" --mode hybrid --top-k 5
```

Hybrid 输出会显示：

```text
rrf_score=...
dense_rank=...
keyword_rank=...
```

可以直接观察最终结果来自哪一条检索链。

## 6. 全量评测

先验证代码：

```powershell
uv run ruff check .
uv run pytest -v
```

Dense baseline：

```powershell
uv run python scripts/eval_retrieval.py --mode dense
```

Keyword baseline：

```powershell
uv run python scripts/eval_retrieval.py --mode keyword
```

Hybrid：

```powershell
uv run python scripts/eval_retrieval.py --mode hybrid
```

三次都使用同一个 37-case `retrieval_v2.jsonl`，因此指标可以直接比较。

## 7. 重点观察的失败样本

Dense v2 当前值得重点观察：

```text
storage-persist-after-delete-zh
storage-host-directory-zh
storage-tmpfs-zh
network-iptables-zh
compose-env-precedence-zh
```

以及排名偏低：

```text
container-cpu-limit-zh
storage-prune-unused-zh
compose-profiles-zh
compose-secrets-zh
build-tag-publish-zh
```

如果 Hybrid 主要修复包含精确技术词的 case，说明 lexical retrieval 起到了预期作用。

如果纯中文、没有英文技术 token 的 case 没有改善，这是合理现象，它们仍主要依赖 Dense retrieval。

## 8. 不要急着调参数

第一轮先记录：

```text
Dense
Keyword
Hybrid (candidate_k=20, rrf_k=60)
```

只有看到对比结果以后，才考虑：

- 调整 keyword token 提取
- 调整 candidate_k
- 调整 RRF 权重/常数
- 加入 Reranker
- 调整 chunk / section 策略

这样每个系统改动都有实验依据，而不是为了堆技术栈。
