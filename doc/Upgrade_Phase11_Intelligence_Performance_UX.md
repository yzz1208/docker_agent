# Upgrade Phase 11 — Intelligence, Performance and UX Hardening

## Goal

Phase 11 turns the stable Phase 10 product into a faster, more coherent support system.
The focus is no longer feature count. The focus is:

- topic-aware multi-turn behavior;
- higher-quality retrieval and citation coverage;
- fewer unnecessary model calls;
- lower TTFT and total latency;
- clearer, calmer chat UX;
- better run-level observability;
- repeatable regression evaluation.

## Current evidence

Recent local product testing shows:

- retrieval itself is already fast for exact Docker terms;
- answer and synthesis model calls dominate latency;
- unrelated topics can inherit stale specialist context;
- comparison questions can retrieve evidence for only one side;
- the right-hand process panel exposes too much repeated detail;
- Operations records are useful but should evolve toward Run -> Stage -> Agent -> Model Call -> Evidence.

## Phase 11A — Context relevance and retrieval coverage

Status: in progress.

### Context relevance gate

A previous specialist result is carried into the next turn only when the new message is an explicit follow-up.

Examples that keep prior context:

- "继续，从依赖超时这个方向往下排查。"
- "那生产环境一般怎么选？"
- "再看一下刚才那个容器的日志。"

Examples that start a new topic:

- "Docker volume 和 bind mount 有什么区别？"
- followed by "checkout-api 一直 503，但 Docker 容器正常，依赖请求频繁超时。"

For a new topic:

- original query resets to the current message;
- user observations reset to the current message;
- stale specialist result is not forwarded to synthesis;
- the current specialist identity can still be used for routing/handoff decisions.

### Comparison retrieval coverage

For explicit comparison questions such as:

- "Docker volume 和 bind mount 有什么区别？"

the fast lexical path must retrieve evidence for both concepts before answering.

Flow:

```text
full query keyword search
        |
comparison concept extraction
        |
targeted search: concept A
targeted search: concept B
        |
both covered?
  | yes               | no
  v                   v
fast context       full hybrid RAG
```

The fast path remains preferred when both sides have evidence because it avoids expensive embedding and reranking.

## Phase 11B — Model-call and latency reduction

Planned next.

Separate model roles instead of forcing every task through one model profile:

- ROUTER_MODEL: cheap, low-latency, structured output, little/no reasoning;
- ANSWER_MODEL: higher-quality technical answer generation;
- SYNTHESIS_MODEL: fast summarization/fusion, only when synthesis is actually needed.

Targets:

- simple platform/greeting: 0 model calls;
- obvious docs query: 1 answer-model call;
- obvious runtime query: planner only if required + 1 answer call;
- obvious cross-agent incident: deterministic handoff, approval, specialist answer;
- synthesis only when multiple specialist results materially contribute.

Add per-model telemetry:

- model role;
- call count;
- TTFT;
- total duration;
- prompt/completion token counts when available;
- fallback/retry count.

## Phase 11C — Chat UI / UX redesign

UI is a first-class Phase 11 workstream.

### Chat center

- keep conversation content visually primary;
- reduce header control density;
- keep composer permanently visible;
- preserve failed user messages and partial assistant output;
- show compact retry state inline;
- improve long-answer typography and code blocks;
- make citations easier to scan and open.

### Process panel

Default state becomes a compact timeline:

```text
判断            0.0s
Docker 支持     18.6s
等待审批
基础设施排障    22.4s
综合            12.1s
```

Detailed reason/capability/evidence is collapsed behind "查看详情".

Avoid repeating the complete assistant answer in the right panel.

### Conversation list

- better active-state contrast;
- clearer failure/pending indicators;
- preserve active conversation across navigation and refresh;
- optional compact search/filter when conversation count grows.

### Responsive layout

- desktop: conversation list + chat + collapsible process panel;
- medium width: process panel becomes drawer;
- small width: history becomes drawer, chat remains primary.

## Phase 11D — Operations 2.0

Move from flat run tables toward:

```text
Run
  -> Stage
      -> Agent / Worker
          -> Model call
          -> Retrieval
          -> Tool call
          -> Evidence
```

Add:

- model-call count per run;
- per-role latency;
- TTFT;
- end-to-end duration;
- approval wait time separated from compute time;
- retrieval mode (keyword fast path / hybrid);
- retry/fallback markers;
- error root cause.

## Phase 11E — Evaluation and fault injection

Build a 30-50 case golden set covering:

- greetings/platform help;
- docs Q&A;
- comparison questions;
- runtime diagnostics;
- same-topic follow-ups;
- topic switches;
- cross-agent handoff;
- approval approve/deny/resume;
- model empty content;
- reasoning token exhaustion;
- SSE choices=[];
- HTML proxy fallback;
- orphan checkpoint retry;
- interrupted streaming.

Quality metrics:

- routing accuracy;
- unnecessary clarification rate;
- topic carry accuracy;
- retrieval concept coverage;
- citation correctness;
- groundedness;
- model-call count;
- TTFT;
- total latency.

## Phase 11 exit criteria

Phase 11 is complete when:

1. unrelated topics never inherit stale specialist summaries;
2. explicit follow-ups preserve useful context;
3. comparison questions retrieve evidence for all compared concepts or fall back safely;
4. obvious requests avoid unnecessary routing models;
5. model roles are independently configurable;
6. chat UI keeps the conversation primary and internal details progressive;
7. Operations exposes enough data to diagnose latency without raw logs;
8. golden evaluation and fault-injection suites pass in CI;
9. local product testing confirms stable navigation, approval, streaming and retry flows.
