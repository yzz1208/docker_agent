# Milestone 1 数据质量检查

在进入 Embedding / pgvector 之前，先验证 `chunks.jsonl` 是否值得被向量化。

## 为什么要做这一步

如果原始 Chunk 已经存在以下问题：

- 过短；
- 过长；
- 代码块被切坏；
- shortcode 残留；
- 来源 URL 丢失；
- section_path 丢失；
- 大量重复内容；

那么后续即使换更好的 Embedding 模型，也无法从根本上修复检索质量。

因此本项目采用：

```text
Markdown
→ Document
→ Chunk
→ Audit
→ Embedding
→ pgvector
```

而不是直接把所有 Markdown 转成向量。

## 运行

```powershell
uv run python scripts/audit_chunks.py
```

默认读取：

```text
data/processed/chunks.jsonl
```

默认只做检查，不修改也不删除任何 Chunk。

## 输出指标

### total_chunks / unique_documents

用于确认数据量和文档覆盖范围。

### word_count

输出：

- min
- P50
- P90
- P95
- max
- average

相比只看平均值，P50/P90/P95 更能反映 Chunk 分布。

### tiny_chunks

默认小于 20 words。

短 Chunk 不一定错误，例如一个很短但独立的重要命令说明可能仍有价值；这里先标记，后续结合 examples 人工判断。

### oversized_chunks

默认大于 600 words。

当前 splitter 的目标 `max_words=450`，但为了保持 fenced code block 原子性，个别代码块可能自然超过 450，因此审计阈值放宽到 600。

### unbalanced_code_fences

检测 Markdown 中 ``` 或 ~~~ 是否成对闭合。

如果不平衡，很可能意味着 Chunk 在代码块中间被错误切开。

### shortcode_remnants

检查 Docker Docs / Hugo shortcode 是否仍残留在 Chunk 中。

### duplicate_contents

对标准化后的完整 Chunk 内容计算 SHA-1，只用于快速发现完全重复的文本，不涉及安全用途。

## 下一步判断

拿到报告后重点看：

1. `empty_chunks` 应为 0；
2. `missing_source_url` 应为 0；
3. `missing_section_path` 应为 0；
4. `unbalanced_code_fences` 理想为 0；
5. `shortcode_remnants` 如果很多，需要继续改 cleaner；
6. `tiny_chunks` 和 `oversized_chunks` 结合 examples 判断；
7. `duplicate_contents` 如果很多，需要检查 include / 页面重复问题。

确认数据质量后，再进入 Milestone 2：Embedding + PostgreSQL/pgvector。
