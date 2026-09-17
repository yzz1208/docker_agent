# Milestone 2：候选召回与加权 RRF 实验

## 1. 这一轮解决什么问题

上一轮 37-case 评测结果：

```text
Dense
Document Hit@1 = 0.6216
Document Hit@3 = 0.8108
Document Hit@5 = 0.8649
Document MRR   = 0.7207
Section Hit@1  = 0.4545
Section Hit@5  = 0.6364
Section MRR    = 0.5182

Hybrid (Dense + Keyword + 等权 RRF)
Document Hit@1 = 0.6757
Document Hit@3 = 0.8649
Document Hit@5 = 0.8919
Document MRR   = 0.7635
Section Hit@1  = 0.5455
Section Hit@5  = 0.7273
Section MRR    = 0.5864
```

Hybrid 已经优于 Dense baseline，但仍有若干 MISS。下一步不能直接假设 Reranker 可以解决，因为 Reranker 只能重新排序已经被第一阶段召回的候选。

因此这一轮先回答：

```text
正确文档是否进入 Dense Top-20？
正确文档是否进入 Keyword Top-20？
Dense ∪ Keyword Top-20 是否覆盖正确文档？
```

如果正确文档没有进入候选池，Reranker 无法修复，需要继续改善召回；如果进入候选池但最终 Top-5 排名差，则适合进入 Reranker 阶段。

## 2. Candidate Coverage 指标

Hybrid 评测现在额外输出：

```text
candidate_coverage:
  dense_hit_at:
    10: ...
    20: ...
  keyword_hit_at:
    10: ...
    20: ...
  union_hit_at:
    10: ...
    20: ...
  union_recall_at:
    10: ...
    20: ...
```

其中：

- `dense_hit_at@20`：Dense Top-20 是否至少包含一篇标注相关文档
- `keyword_hit_at@20`：Keyword Top-20 是否至少包含一篇标注相关文档
- `union_hit_at@20`：两路候选合并后是否至少包含一篇相关文档
- `union_recall_at@20`：对多相关文档 case，候选池覆盖了多少标注相关文档

## 3. 运行 baseline

更新代码：

```powershell
git pull --ff-only
```

检查：

```powershell
uv run ruff check .
uv run pytest -v
```

然后：

```powershell
uv run python scripts/eval_retrieval.py --mode hybrid
```

默认参数仍是：

```text
candidate_k = 20
rrf_k = 60
dense_weight = 1.0
keyword_weight = 1.0
```

先记录 `candidate_coverage`，不要先调权重。

## 4. 如何根据 Candidate Coverage 决策

### 情况 A：Union Hit@20 很高，但最终 Hit@5 明显低

例如：

```text
Union Hit@20 = 0.97
Hybrid Hit@5 = 0.89
```

说明正确资料通常已经进入候选池，只是排序还不够好。

下一步优先：

```text
Hybrid candidates -> Reranker -> Top-K
```

### 情况 B：Union Hit@20 仍然低

例如：

```text
Union Hit@20 = 0.85
```

说明仍有大量问题连候选池都召回不到正确文档。

下一步应该继续改善第一阶段召回，例如：

- query rewrite / query expansion
- 更好的 keyword token 处理
- title / section lexical boost
- 扩大 candidate depth
- 调整 embedding 输入

而不是直接加 Reranker。

## 5. Weighted RRF

当前 RRF 支持：

```text
--dense-weight
--keyword-weight
```

默认仍为等权：

```text
1.0 / 1.0
```

公式：

```text
score(d) = dense_weight / (rrf_k + dense_rank)
         + keyword_weight / (rrf_k + keyword_rank)
```

不要在看 Candidate Coverage 之前盲目调参。

如果候选覆盖很好，但等权 RRF 把一些强 Dense 结果拉低，可以尝试轻微偏向 Dense：

```powershell
uv run python scripts/eval_retrieval.py --mode hybrid --dense-weight 1.25 --keyword-weight 1.0
```

再试：

```powershell
uv run python scripts/eval_retrieval.py --mode hybrid --dense-weight 1.5 --keyword-weight 1.0
```

每次只改一个参数，并记录完整指标。

## 6. 当前实验纪律

这一轮先完成：

```text
1. 等权 Hybrid candidate coverage
2. 判断失败属于 recall 还是 ranking
3. 再做少量 weighted RRF 对比
4. 决定是否进入 Reranker
```

不要同时改 candidate_k、rrf_k、Dense 权重和 Keyword 权重，否则无法判断指标变化来自哪一个变量。
