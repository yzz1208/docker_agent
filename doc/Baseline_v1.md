# Baseline v1

## 目的

在进入 State / Evidence / LangGraph 重构前，冻结当前稳定行为作为回归基线。

Baseline v1 包含：Docker Docs RAG、read-only runtime tools、Router、Dynamic Planner、observe→decide→act→observe、failure recovery、citation guard、workflow eval 与 LLM judge。

## 当前稳定能力

- Docker Docs 清洗、切块、BGE-M3 dense retrieval、keyword retrieval、RRF、BGE reranker。
- docs/runtime citation validation。
- docs_only / runtime_tools / clarify。
- validated container_ref。
- dynamic single-tool planning 与 observation-driven replanning。
- multi-turn clarification 与 FastAPI chat session。
- container not found / daemon unavailable / logs unavailable / stopped stats recovery。
- Docker tool timeout recovery。
- daemon/socket permission denied recovery。
- transient model HTTP/TLS retry 与 eval fault isolation。

## 当前评测基线

### Dynamic Workflow

8/8 exact pass：completion、route、tool sequence、finish、step limit、no-repeat、runtime/docs citation、concept coverage、exact workflow 全部为 1.0。

Judge：groundedness=5、runtime citation correctness=5、docs citation correctness=5、diagnosis quality=5、unsupported claims=0。

### Failure Recovery

4/4 exact pass：container not found、daemon unavailable、logs unavailable、stopped container stats。Judge 全 5 分。

### Timeout Recovery

2/2 exact pass：stats timeout、logs timeout after inspect。Judge 全 5 分。

### Permission Denied Recovery

2/2 exact pass：docker_info permission denied、docker_inspect permission denied。Judge 全 5 分。

## Baseline 原则

1. 不为了新框架删除稳定测试。
2. State/Evidence 第一阶段不得改变外部回答行为。
3. 新 Schema 优先通过 adapter 接入旧实现。
4. 旧 Eval 在迁移过程中持续运行。
5. LangGraph Migration 只有在 schema 稳定后开始。
6. Multi-Agent 不作为 Phase 1 的目标。

## 回归命令

~~~powershell
uv run ruff check .
uv run pytest -v
uv run python scripts/eval_agent_router.py
uv run python scripts/eval_agent_workflow.py --judge
uv run python scripts/eval_dynamic_workflow.py --judge
uv run python scripts/eval_dynamic_workflow.py --input data/eval/dynamic_failure_v1.jsonl --output reports/dynamic_failure_eval_latest.jsonl --judge
uv run python scripts/eval_dynamic_workflow.py --input data/eval/dynamic_timeout_v1.jsonl --output reports/dynamic_timeout_eval_latest.jsonl --judge
uv run python scripts/eval_dynamic_workflow.py --input data/eval/dynamic_permission_v1.jsonl --output reports/dynamic_permission_eval_latest.jsonl --judge
~~~

Baseline v1 是下一阶段所有结构升级的行为参照。
