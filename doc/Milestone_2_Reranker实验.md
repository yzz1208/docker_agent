# Milestone 2：Reranker 实验

## 评测集

评测集：`data/eval/retrieval_v2.jsonl`，共 37 个查询。

## Hybrid 基线

Dense + PostgreSQL FTS + RRF：

- Document Hit@1: 0.6757
- Document Hit@3: 0.8649
- Document Hit@5: 0.8919
- Document MRR: 0.7635
- Section Hit@1: 0.5455
- Section Hit@3: 0.5455
- Section Hit@5: 0.7273
- Section MRR: 0.5864

## Candidate coverage

- Dense Hit@10: 0.9189
- Dense Hit@20: 1.0000
- Keyword Hit@10: 0.6216
- Keyword Hit@20: 0.7027
- Union Hit@10: 0.9459
- Union Hit@20: 1.0000
- Union Recall@20: 1.0000

这说明当前 37 条评测中，正确文档已经全部进入 Dense Top-20 / Union Top-20，主要瓶颈已经从第一阶段召回转移到候选排序。

## Reranker 对比

模型：`BAAI/bge-reranker-v2-m3`

### Union pool（最多约 40 chunks）

- Document Hit@1: 0.6486
- Document Hit@3: 0.9189
- Document Hit@5: 0.9459
- Document MRR: 0.7770
- Section Hit@1: 0.6364
- Section Hit@3: 0.8182
- Section Hit@5: 1.0000
- Section MRR: 0.7576

### Dense Top-20 pool

- Document Hit@1: 0.6486
- Document Hit@3: 0.9189
- Document Hit@5: 0.9459
- Document MRR: 0.7770
- Section Hit@1: 0.6364
- Section Hit@3: 0.8182
- Section Hit@5: 1.0000
- Section MRR: 0.7576

### RRF Top-20 pool（最终方案）

- Document Hit@1: 0.6757
- Document Hit@3: 0.9189
- Document Hit@5: 0.9459
- Document MRR: 0.7905
- Section Hit@1: 0.6364
- Section Hit@3: 0.8182
- Section Hit@5: 1.0000
- Section MRR: 0.7576

## 最终选择

Milestone 2 最终检索链路确定为：

```text
User Query
   ├─ BGE-M3 Dense Top-20
   └─ PostgreSQL FTS Top-20
              ↓
       RRF (1.0 : 1.0)
              ↓
           Top-20
              ↓
  BGE-reranker-v2-m3
              ↓
           Top-5
```

选择 RRF Top-20 的原因：

1. 保持 Hybrid 的 Document Hit@1 = 0.6757。
2. Document Hit@3 / Hit@5 提升到 0.9189 / 0.9459。
3. Document MRR 提升到 0.7905，是本轮对比中最高。
4. Section Hit@1 从 Hybrid 的 0.5455 提升到 0.6364。
5. Section Hit@5 达到 1.0000。
6. 相比 union pool，reranker 只需处理最多 20 个候选，减少约一半 pair 推理量。

## Milestone 2 结论

Milestone 2 到此收尾，不再围绕当前 37 条评测继续细调 RRF 常数、权重或候选深度，避免对小型评测集过拟合。

下一阶段进入 Milestone 3：

```text
Retrieval
  ↓
RRF Top-20
  ↓
Reranker Top-5
  ↓
Context Builder
  ↓
Grounded Prompt
  ↓
LLM
  ↓
Answer + Docker Docs citations
```
