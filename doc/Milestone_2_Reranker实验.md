# Milestone 2：Reranker 实验

## 已有基线

评测集：`data/eval/retrieval_v2.jsonl`，共 37 个查询。

### Hybrid（Dense + PostgreSQL FTS + RRF）

- Document Hit@1: 0.6757
- Document Hit@3: 0.8649
- Document Hit@5: 0.8919
- Document MRR: 0.7635
- Section Hit@1: 0.5455
- Section Hit@3: 0.5455
- Section Hit@5: 0.7273
- Section MRR: 0.5864

### Candidate coverage

- Dense Hit@10: 0.9189
- Dense Hit@20: 1.0000
- Keyword Hit@10: 0.6216
- Keyword Hit@20: 0.7027
- Union Hit@10: 0.9459
- Union Hit@20: 1.0000
- Union Recall@20: 1.0000

这说明当前主要瓶颈已经不是第一阶段召回，而是候选排序。

### Reranker：union pool（最多约 40 chunks）

模型：`BAAI/bge-reranker-v2-m3`

- Document Hit@1: 0.6486
- Document Hit@3: 0.9189
- Document Hit@5: 0.9459
- Document MRR: 0.7770
- Section Hit@1: 0.6364
- Section Hit@3: 0.8182
- Section Hit@5: 1.0000
- Section MRR: 0.7576

结论：Reranker 明显改善了 Top-3 / Top-5 和 section-level 排序，但 Document Hit@1 从 0.6757 降到 0.6486。当前 union pool 最多会把 20 个 dense 候选与 20 个 keyword 候选一起交给 Cross Encoder，可能带入了不必要的噪声，同时增加推理开销。

## 下一组实验：rerank candidate pool

新增 `--rerank-pool`：

- `rrf`：先用 RRF 压缩为 Top-20，再交给 reranker（新的默认方案）
- `union`：保留旧行为，最多约 40 个候选
- `dense`：只对 Dense Top-20 进行 rerank

运行：

```powershell
uv run python scripts/eval_retrieval.py --mode rerank --rerank-pool rrf
uv run python scripts/eval_retrieval.py --mode rerank --rerank-pool dense
```

`union` 已有基线，如需复现：

```powershell
uv run python scripts/eval_retrieval.py --mode rerank --rerank-pool union
```

重点比较：

1. Document Hit@1 是否恢复或超过 Hybrid 的 0.6757。
2. Section Hit@1 / Hit@5 是否继续保持 Reranker 的优势。
3. RRF Top-20 能否在减少一半左右 rerank pair 数量的同时保持质量。
4. Dense-only Top-20 是否说明 Keyword union 中的候选会干扰 Cross Encoder。

如果 `rrf` pool 在 Document Hit@1、Section 指标和推理成本之间表现稳定，则将其作为 Milestone 2 的最终检索链路，并进入 Milestone 3：Context Builder + LLM Answer Generation。
