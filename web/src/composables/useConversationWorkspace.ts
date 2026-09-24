import { computed, ref } from "vue";

import {
  ApiError,
  deleteConversation,
  getAutoApproval,
  getConversation,
  listAgents,
  listConversations,
  renameConversation,
  resolveAutoApproval,
  sendAutoChatStream,
  sendChat,
} from "../lib/api";
import type {
  AgentDescriptor,
  AutoChatProgressEvent,
  AutoChatResponse,
  ChatResponse,
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  DocSource,
  RuntimeSource,
} from "../lib/types";

type ChatMode = "manual" | "auto";

const AUTO_AGENT_TYPE = "auto_orchestration";

export function useConversationWorkspace() {
  const agents = ref<AgentDescriptor[]>([]);
  const conversations = ref<ConversationSummary[]>([]);
  const detail = ref<ConversationDetail | null>(null);
  const selectedAgentType = ref("docker_support");
  const selectedMode = ref<ChatMode>("auto");
  const activeConversationId = ref<string | null>(null);
  const activeSessionId = ref<string | null>(null);
  const draft = ref("");
  const pendingUserMessage = ref<string | null>(null);
  const streamingAssistantText = ref("");
  const optimisticMessages = ref<ConversationMessage[]>([]);
  const optimisticConversationId = ref<string | null>(null);
  const syncingConversation = ref(false);
  const autoProgress = ref<AutoChatProgressEvent | null>(null);

  const latestTurns = ref<Record<string, ChatResponse>>({});
  const latestAutoTurns = ref<Record<string, AutoChatResponse>>({});

  const loadingAgents = ref(false);
  const loadingList = ref(false);
  const loadingConversation = ref(false);
  const sending = ref(false);
  const approving = ref(false);
  const renaming = ref(false);
  const deleting = ref(false);

  const agentError = ref("");
  const listError = ref("");
  const conversationError = ref("");
  const actionError = ref("");

  let conversationRequestVersion = 0;
  let activeSyncRequests = 0;

  const activeTitle = computed(() => {
    if (detail.value?.conversation.title) {
      return detail.value.conversation.title;
    }
    return activeConversationId.value
      ? "对话"
      : "新对话";
  });

  const activeMode = computed<ChatMode>(() =>
    detail.value?.conversation.agent_type === AUTO_AGENT_TYPE ||
    (!detail.value && selectedMode.value === "auto")
      ? "auto"
      : "manual",
  );

  const latestAutoTurn = computed(() => {
    const id = activeConversationId.value;
    return id ? latestAutoTurns.value[id] ?? null : null;
  });

  const pendingApproval = computed(() =>
    latestAutoTurn.value?.needs_approval
      ? latestAutoTurn.value.approval_request
      : null,
  );

  const activeAgentType = computed(() => {
    if (activeMode.value === "auto") {
      return (
        latestAutoTurn.value?.current_agent_type ??
        AUTO_AGENT_TYPE
      );
    }
    return (
      detail.value?.conversation.agent_type ??
      selectedAgentType.value
    );
  });

  const activeAgent = computed(
    () =>
      activeMode.value === "manual"
        ? agents.value.find(
            (agent) => agent.agent_type === activeAgentType.value,
          ) ?? null
        : agents.value.find(
            (agent) =>
              agent.agent_type ===
              latestAutoTurn.value?.current_agent_type,
          ) ?? null,
  );

  const latestTurn = computed(() => {
    const id = activeConversationId.value;
    return id ? latestTurns.value[id] ?? null : null;
  });

  const canSelectMode = computed(
    () => !activeConversationId.value && !sending.value,
  );

  const canSelectAgent = computed(
    () =>
      canSelectMode.value &&
      selectedMode.value === "manual",
  );

  const canSend = computed(
    () =>
      draft.value.trim().length > 0 &&
      !sending.value &&
      !approving.value &&
      !pendingApproval.value,
  );

  const displayMessages = computed(() => [
    ...(detail.value?.messages ?? []),
    ...(
      optimisticConversationId.value === activeConversationId.value
        ? optimisticMessages.value
        : []
    ),
  ]);

  function errorText(error: unknown): string {
    if (error instanceof ApiError) {
      return error.detail;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return "发生了未知错误，请稍后重试。";
  }

  function agentDisplayName(agentType: string): string {
    const localized: Record<string, string> = {
      auto_orchestration: "智能编排",
      docker_support: "Docker 支持",
      infrastructure_troubleshooter: "基础设施排障",
    };
    return (
      localized[agentType] ??
      agents.value.find((agent) => agent.agent_type === agentType)
        ?.display_name ??
      agentType
    );
  }

  function autoProgressStageDisplayName(stage: string): string {
    const localized: Record<string, string> = {
      request: "正在理解问题",
      orchestration_decision: "正在选择合适专家",
      decision: "正在判断处理方式",
      rag_database: "正在检查文档知识库",
      embedding: "正在理解检索问题",
      dense_retrieval: "正在进行语义检索",
      keyword_retrieval: "正在匹配关键技术词",
      fusion: "正在合并检索结果",
      rerank: "正在筛选最相关文档",
      context_build: "正在整理文档证据",
      runtime: "正在运行只读诊断",
      answer: "正在生成回答",
      synthesis: "正在综合专家结果",
    };
    return localized[stage] ?? "正在处理";
  }

  const autoProgressText = computed(() => {
    const progress = autoProgress.value;
    if (!progress) return "正在准备智能编排";

    const label = autoProgressStageDisplayName(progress.stage);
    if (
      progress.status === "completed" &&
      progress.duration_ms !== null
    ) {
      const completedLabel = label.startsWith("正在")
        ? label.slice(2)
        : label;
      return `${completedLabel}完成 · ${(
        progress.duration_ms / 1000
      ).toFixed(1)}s`;
    }
    return label;
  });

  function capabilityDisplayName(capability: string): string {
    const localized: Record<string, string> = {
      chat: "对话",
      documentation_qa: "文档问答",
      runtime_diagnostics: "运行时诊断",
      multi_agent_supervision: "多智能体监督",
      incident_triage: "故障分诊",
    };
    return localized[capability] ?? capability;
  }

  function workerDisplayName(worker: string): string {
    const localized: Record<string, string> = {
      knowledge: "知识检索",
      runtime: "运行时检查",
      diagnosis: "诊断回答",
      synthesis: "结果综合",
    };
    return localized[worker] ?? worker;
  }

  function routeDisplayName(route: string): string {
    const localized: Record<string, string> = {
      chat: "快速对话",
      clarify: "补充信息",
      docs_only: "文档解答",
      runtime_only: "运行时检查",
      runtime_tools: "运行时诊断",
      triage: "故障分诊",
      auto: "智能编排",
      auto_clarify: "智能补充信息",
      auto_direct: "专家直达",
      auto_direct_clarify: "专家补充信息",
      auto_delegate_clarify: "转交后补充信息",
      auto_synthesis: "多专家综合",
      auto_approval_pending: "等待人工批准",
      auto_approval_denied: "人工拒绝",
    };
    return localized[route] ?? route;
  }

  function agentDescription(agentType: string): string {
    const localized: Record<string, string> = {
      docker_support:
        "结合 Docker 文档检索、只读运行时诊断与多 Worker 协作，处理容器相关问题。",
      infrastructure_troubleshooter:
        "面向服务级故障进行分诊，区分已知事实、可能原因与下一步安全检查。",
      auto_orchestration:
        "自动判断问题类型，选择合适专家，并在必要时安全转交与综合结果。",
    };
    return (
      localized[agentType] ??
      agents.value.find((agent) => agent.agent_type === agentType)
        ?.description ??
      ""
    );
  }

  function traceStageDisplayName(stage: string): string {
    const localized: Record<string, string> = {
      decision: "智能判断",
      approval: "人工审批",
      handoff: "专家转交",
      specialist: "专家处理",
      synthesis: "综合结论",
    };
    return localized[stage] ?? stage;
  }

  async function refreshAgents(): Promise<void> {
    loadingAgents.value = true;
    agentError.value = "";
    try {
      agents.value = await listAgents();
      if (
        agents.value.length > 0 &&
        !agents.value.some(
          (agent) => agent.agent_type === selectedAgentType.value,
        )
      ) {
        selectedAgentType.value =
          agents.value.find((agent) => agent.default_enabled)
            ?.agent_type ??
          agents.value[0]?.agent_type ??
          selectedAgentType.value;
      }
    } catch (error) {
      agentError.value = errorText(error);
    } finally {
      loadingAgents.value = false;
    }
  }

  async function initialize(): Promise<void> {
    await Promise.all([
      refreshAgents(),
      refreshConversations(),
    ]);
  }

  function optimisticMessage(
    role: "user" | "assistant",
    content: string,
    options: {
      route?: string | null;
      clarification?: string | null;
      useDocs?: boolean | null;
    } = {},
  ): ConversationMessage {
    const {
      route = null,
      clarification = null,
      useDocs = null,
    } = options;
    return {
      id: `optimistic-${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      role,
      content,
      route,
      use_docs: useDocs,
      clarification,
      created_at: new Date().toISOString(),
      execution: null,
    };
  }

  function showOptimisticCompletedTurn(
    userMessage: string,
    assistantContent: string,
    options: {
      route: string | null;
      clarification?: string | null;
      useDocs?: boolean | null;
    },
  ): void {
    optimisticConversationId.value = activeConversationId.value;
    optimisticMessages.value = [
      ...(
        optimisticConversationId.value === activeConversationId.value
          ? optimisticMessages.value
          : []
      ),
      optimisticMessage("user", userMessage),
      optimisticMessage("assistant", assistantContent, options),
    ];
  }

  function reconcileOptimisticMessages(
    conversationId: string,
    persisted: ConversationMessage[],
  ): void {
    if (optimisticConversationId.value !== conversationId) {
      return;
    }
    const counts = new Map<string, number>();
    for (const message of persisted) {
      const key = `${message.role}\u0000${message.content}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }

    optimisticMessages.value = optimisticMessages.value.filter(
      (message) => {
        const key = `${message.role}\u0000${message.content}`;
        const count = counts.get(key) ?? 0;
        if (count <= 0) {
          return true;
        }
        counts.set(key, count - 1);
        return false;
      },
    );
  }

  async function syncConversationAfterTurn(
    conversationId: string,
    expected: {
      role: "user" | "assistant";
      content: string;
    },
  ): Promise<void> {
    activeSyncRequests += 1;
    syncingConversation.value = true;
    let lastError: unknown = null;

    try {
      for (let attempt = 0; attempt < 5; attempt += 1) {
        try {
          const loaded = await refreshConversationDetail(
            conversationId,
            1,
          );
          reconcileOptimisticMessages(
            conversationId,
            loaded.messages,
          );

          if (
            loaded.messages.some(
              (message) =>
                message.role === expected.role &&
                message.content === expected.content,
            )
          ) {
            return;
          }
          lastError = new Error(
            "completed message is not visible in persistence yet",
          );
        } catch (error) {
          lastError = error;
        }

        if (attempt < 4) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, 180 * (attempt + 1)),
          );
        }
      }

      throw lastError ?? new Error("conversation sync failed");
    } catch {
      actionError.value =
        "回答已经完成，但对话记录暂时没有同步成功。你可以继续提问，系统会稍后重新加载记录。";
    } finally {
      activeSyncRequests = Math.max(0, activeSyncRequests - 1);
      syncingConversation.value = activeSyncRequests > 0;
    }
  }

  async function refreshConversationDetail(
    conversationId: string,
    attempts = 3,
  ): Promise<ConversationDetail> {
    let lastError: unknown = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const loaded = await getConversation(conversationId);
        if (activeConversationId.value === conversationId) {
          detail.value = loaded;
          if (loaded.conversation.agent_type === AUTO_AGENT_TYPE) {
            restoreAutoTurn(loaded);
          }
        }
        return loaded;
      } catch (error) {
        lastError = error;
        if (attempt + 1 < attempts) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, 180 * (attempt + 1)),
          );
        }
      }
    }
    throw lastError;
  }

  async function refreshConversations(): Promise<void> {
    loadingList.value = true;
    listError.value = "";
    try {
      conversations.value = await listConversations();
    } catch (error) {
      listError.value = errorText(error);
    } finally {
      loadingList.value = false;
    }
  }

  async function openConversation(id: string): Promise<void> {
    const requestVersion = ++conversationRequestVersion;
    conversationError.value = "";
    actionError.value = "";
    loadingConversation.value = true;
    activeSessionId.value = null;
    activeConversationId.value = id;
    optimisticConversationId.value = null;
    optimisticMessages.value = [];

    try {
      const loaded = await getConversation(id);
      if (requestVersion === conversationRequestVersion) {
        detail.value = loaded;
        if (loaded.conversation.agent_type === AUTO_AGENT_TYPE) {
          selectedMode.value = "auto";
          restoreAutoTurn(loaded);
          try {
            const pending = await getAutoApproval(
              loaded.conversation.id,
            );
            if (
              requestVersion === conversationRequestVersion &&
              pending
            ) {
              latestAutoTurns.value = {
                ...latestAutoTurns.value,
                [loaded.conversation.id]: pending,
              };
            }
          } catch (approvalError) {
            if (requestVersion === conversationRequestVersion) {
              actionError.value = errorText(approvalError);
            }
          }
        } else {
          selectedMode.value = "manual";
          selectedAgentType.value = loaded.conversation.agent_type;
          restoreManualTurn(loaded);
        }
      }
    } catch (error) {
      if (requestVersion === conversationRequestVersion) {
        conversationError.value = errorText(error);
      }
    } finally {
      if (requestVersion === conversationRequestVersion) {
        loadingConversation.value = false;
      }
    }
  }

  function startNewConversation(): void {
    conversationRequestVersion += 1;
    activeConversationId.value = null;
    activeSessionId.value = null;
    detail.value = null;
    draft.value = "";
    optimisticMessages.value = [];
    optimisticConversationId.value = null;
    selectedMode.value = "auto";
    conversationError.value = "";
    actionError.value = "";
    loadingConversation.value = false;
  }

  function traceDocSources(
    trace: Record<string, unknown>[],
  ): DocSource[] {
    const direct = trace
      .filter((item) => item.kind === "doc_source")
      .map((item) => ({
        index: Number(item.index ?? 0),
        title: String(item.title ?? ""),
        section: String(item.section ?? ""),
        source_url: String(item.source_url ?? ""),
      }))
      .filter(
        (source) =>
          source.index > 0 &&
          Boolean(source.title) &&
          Boolean(source.source_url),
      );

    for (const item of trace) {
      if (item.kind !== "auto_state") continue;
      const nested = item.result_doc_sources;
      if (!Array.isArray(nested)) continue;
      for (const source of nested) {
        if (!source || typeof source !== "object") continue;
        const value = source as Record<string, unknown>;
        const normalized = {
          index: Number(value.index ?? 0),
          title: String(value.title ?? ""),
          section: String(value.section ?? ""),
          source_url: String(value.source_url ?? ""),
        };
        if (
          normalized.index > 0 &&
          normalized.title &&
          normalized.source_url
        ) {
          direct.push(normalized);
        }
      }
    }
    return direct;
  }

  function traceRuntimeSources(
    trace: Record<string, unknown>[],
  ): RuntimeSource[] {
    const direct = trace
      .filter((item) => item.kind === "runtime_source")
      .map((item) => ({
        index: Number(item.index ?? 0),
        tool: String(item.tool ?? ""),
        command: Array.isArray(item.command)
          ? item.command.map(String)
          : [],
        ok: item.ok === true,
      }))
      .filter(
        (source) => source.index > 0 && Boolean(source.tool),
      );

    for (const item of trace) {
      if (item.kind !== "auto_state") continue;
      const nested = item.result_runtime_sources;
      if (!Array.isArray(nested)) continue;
      for (const source of nested) {
        if (!source || typeof source !== "object") continue;
        const value = source as Record<string, unknown>;
        const normalized = {
          index: Number(value.index ?? 0),
          tool: String(value.tool ?? ""),
          command: Array.isArray(value.command)
            ? value.command.map(String)
            : [],
          ok: value.ok === true,
        };
        if (normalized.index > 0 && normalized.tool) {
          direct.push(normalized);
        }
      }
    }
    return direct;
  }

  function messageDocSources(
    message: ConversationMessage,
  ): DocSource[] {
    return traceDocSources(
      message.execution?.worker_trace ?? [],
    );
  }

  function messageRuntimeSources(
    message: ConversationMessage,
  ): RuntimeSource[] {
    return traceRuntimeSources(
      message.execution?.worker_trace ?? [],
    );
  }

  function restoreManualTurn(
    loaded: ConversationDetail,
  ): void {
    if (loaded.conversation.agent_type === AUTO_AGENT_TYPE) {
      return;
    }

    const assistant = [...loaded.messages]
      .reverse()
      .find((message) => message.role === "assistant");
    if (!assistant) {
      return;
    }

    latestTurns.value = {
      ...latestTurns.value,
      [loaded.conversation.id]: {
        agent_type: loaded.conversation.agent_type,
        conversation_id: loaded.conversation.id,
        session_id: "",
        session_active: false,
        route: assistant.route ?? "chat",
        reason: "已从该对话最近一次持久化执行中恢复。",
        use_docs: Boolean(assistant.use_docs),
        clarification: assistant.clarification,
        answer: assistant.clarification
          ? null
          : assistant.content,
        runtime_sources: traceRuntimeSources(
          assistant.execution?.worker_trace ?? [],
        ),
        doc_sources: traceDocSources(
          assistant.execution?.worker_trace ?? [],
        ),
        execution: assistant.execution
          ? {
              planned_workers:
                assistant.execution.planned_workers,
              completed_workers:
                assistant.execution.completed_workers,
              worker_trace:
                assistant.execution.worker_trace
                  .filter(
                    (item) =>
                      typeof item.index === "number" &&
                      typeof item.role === "string",
                  )
                  .map((item) => ({
                    index: Number(item.index),
                    role: String(item.role),
                    tool_results_added: Number(
                      item.tool_results_added ?? 0,
                    ),
                    evidence_added: Number(
                      item.evidence_added ?? 0,
                    ),
                    runtime_steps_added: Number(
                      item.runtime_steps_added ?? 0,
                    ),
                    answer_created: Boolean(
                      item.answer_created,
                    ),
                  })),
            }
          : null,
      },
    };
  }

  function restoreAutoTurn(loaded: ConversationDetail): void {
    if (loaded.conversation.agent_type !== AUTO_AGENT_TYPE) {
      return;
    }
    const assistant = [...loaded.messages]
      .reverse()
      .find((message) => message.role === "assistant");
    if (!assistant) {
      return;
    }
    const workerTrace = assistant.execution?.worker_trace ?? [];
    const trace = workerTrace
      .filter((item) => item.kind === "orchestration_trace")
      .map((item) => ({
        stage: String(item.stage ?? "specialist") as
          AutoChatResponse["trace"][number]["stage"],
        label: String(item.label ?? ""),
        agent_type:
          typeof item.agent_type === "string" && item.agent_type
            ? item.agent_type
            : null,
        capability:
          typeof item.capability === "string" && item.capability
            ? item.capability
            : null,
        reason: String(item.reason ?? ""),
      }));
    const state = [...workerTrace]
      .reverse()
      .find((item) => item.kind === "auto_state");
    const currentAgent =
      typeof state?.current_agent_type === "string" &&
      state.current_agent_type
        ? state.current_agent_type
        : null;
    const restoredSpecialistResults =
      state &&
      typeof state.result_agent_type === "string" &&
      state.result_agent_type &&
      typeof state.result_route === "string" &&
      state.result_route &&
      typeof state.result_reason === "string" &&
      state.result_reason
        ? [
            {
              agent_type: state.result_agent_type,
              route: state.result_route,
              reason: state.result_reason,
              needs_clarification:
                state.result_needs_clarification === true,
              clarification:
                typeof state.result_clarification === "string" &&
                state.result_clarification
                  ? state.result_clarification
                  : null,
              summary:
                typeof state.result_summary === "string" &&
                state.result_summary
                  ? state.result_summary
                  : null,
              doc_sources: traceDocSources(
                state ? [state] : [],
              ),
              runtime_sources: traceRuntimeSources(
                state ? [state] : [],
              ),
            },
          ]
        : [];

    latestAutoTurns.value = {
      ...latestAutoTurns.value,
      [loaded.conversation.id]: {
        mode: "auto",
        conversation_id: loaded.conversation.id,
        current_agent_type: currentAgent,
        route: assistant.route ?? "auto",
        answer: assistant.clarification ? null : assistant.content,
        clarification: assistant.clarification,
        needs_clarification: Boolean(assistant.clarification),
        synthesized: trace.some((item) => item.stage === "synthesis"),
        trace,
        specialist_results: restoredSpecialistResults,
        approval_status: null,
        needs_approval: false,
        approval_request: null,
      },
    };
  }

  async function submitMessage(): Promise<boolean> {
    const message = draft.value.trim();
    if (!message || sending.value) {
      return false;
    }

    sending.value = true;
    pendingUserMessage.value = message;
    streamingAssistantText.value = "";
    actionError.value = "";

    try {
      if (activeMode.value === "auto") {
        autoProgress.value = {
          stage: "request",
          status: "started",
          duration_ms: null,
        };
        const result = await sendAutoChatStream(
          {
            message,
            conversationId: activeConversationId.value,
          },
          (progress) => {
            autoProgress.value = progress;
          },
          (delta) => {
            streamingAssistantText.value += delta;
          },
        );
        activeConversationId.value = result.conversation_id;
        activeSessionId.value = null;
        draft.value = "";
        latestAutoTurns.value = {
          ...latestAutoTurns.value,
          [result.conversation_id]: result,
        };

        if (result.needs_approval) {
          optimisticConversationId.value =
            result.conversation_id;
          optimisticMessages.value = [
            ...optimisticMessages.value,
            optimisticMessage("user", message),
          ];
        } else {
          const assistantContent =
            result.answer ?? result.clarification;
          if (assistantContent) {
            showOptimisticCompletedTurn(
              message,
              assistantContent,
              {
                route: result.route,
                clarification: result.clarification,
              },
            );
          }
        }

        pendingUserMessage.value = null;
        void syncConversationAfterTurn(
          result.conversation_id,
          result.needs_approval
            ? { role: "user", content: message }
            : {
                role: "assistant",
                content:
                  result.answer ??
                  result.clarification ??
                  "",
              },
        );
      } else {
        const result = await sendChat({
          message,
          agentType:
            detail.value?.conversation.agent_type ??
            (activeConversationId.value
              ? undefined
              : selectedAgentType.value),
          conversationId: activeConversationId.value,
          sessionId: activeSessionId.value,
        });

        selectedAgentType.value = result.agent_type;
        activeConversationId.value = result.conversation_id;
        activeSessionId.value = result.session_active
          ? result.session_id
          : null;
        draft.value = "";

        if (result.conversation_id) {
          latestTurns.value = {
            ...latestTurns.value,
            [result.conversation_id]: result,
          };

          const assistantContent =
            result.answer ?? result.clarification;
          if (assistantContent) {
            showOptimisticCompletedTurn(
              message,
              assistantContent,
              {
                route: result.route,
                clarification: result.clarification,
                useDocs: result.use_docs,
              },
            );
          }

          pendingUserMessage.value = null;
          void syncConversationAfterTurn(
            result.conversation_id,
            {
              role: "assistant",
              content:
                result.answer ??
                result.clarification ??
                "",
            },
          );
        }
      }

      void refreshConversations();
      return true;
    } catch (error) {
      actionError.value = errorText(error);
      return false;
    } finally {
      sending.value = false;
      pendingUserMessage.value = null;
      autoProgress.value = null;
      streamingAssistantText.value = "";
    }
  }

  async function resolvePendingApproval(
    approved: boolean,
  ): Promise<boolean> {
    const conversationId = activeConversationId.value;
    if (
      !conversationId ||
      !pendingApproval.value ||
      approving.value
    ) {
      return false;
    }

    approving.value = true;
    actionError.value = "";

    try {
      const result = await resolveAutoApproval({
        conversationId,
        approved,
        comment: approved
          ? "用户批准继续执行。"
          : "用户拒绝继续执行。",
      });
      latestAutoTurns.value = {
        ...latestAutoTurns.value,
        [conversationId]: result,
      };
      const assistantContent =
        result.answer ?? result.clarification;
      if (assistantContent) {
        optimisticConversationId.value = conversationId;
        optimisticMessages.value = [
          ...optimisticMessages.value,
          optimisticMessage(
            "assistant",
            assistantContent,
            {
              route: result.route,
              clarification: result.clarification,
            },
          ),
        ];
      }
      if (assistantContent) {
        void syncConversationAfterTurn(
          conversationId,
          {
            role: "assistant",
            content: assistantContent,
          },
        );
      }
      void refreshConversations();
      return true;
    } catch (error) {
      actionError.value = errorText(error);
      return false;
    } finally {
      approving.value = false;
    }
  }

  async function renameActiveConversation(
    title: string,
  ): Promise<boolean> {
    const conversation = detail.value?.conversation;
    const normalizedTitle = title.trim();
    if (!conversation || !normalizedTitle || renaming.value) {
      return false;
    }

    renaming.value = true;
    actionError.value = "";

    try {
      const updated = await renameConversation(
        conversation.id,
        normalizedTitle,
      );
      if (detail.value?.conversation.id === updated.id) {
        detail.value = {
          ...detail.value,
          conversation: updated,
        };
      }
      conversations.value = conversations.value.map((item) =>
        item.id === updated.id ? updated : item,
      );
      return true;
    } catch (error) {
      actionError.value = errorText(error);
      return false;
    } finally {
      renaming.value = false;
    }
  }

  async function deleteActiveConversation(): Promise<boolean> {
    const conversation = detail.value?.conversation;
    if (!conversation || deleting.value) {
      return false;
    }

    deleting.value = true;
    actionError.value = "";

    try {
      await deleteConversation(conversation.id);
      const deletedId = conversation.id;
      conversations.value = conversations.value.filter(
        (item) => item.id !== deletedId,
      );
      const { [deletedId]: _removed, ...remainingTurns } =
        latestTurns.value;
      latestTurns.value = remainingTurns;
      const {
        [deletedId]: _removedAuto,
        ...remainingAutoTurns
      } = latestAutoTurns.value;
      latestAutoTurns.value = remainingAutoTurns;
      startNewConversation();
      return true;
    } catch (error) {
      actionError.value = errorText(error);
      return false;
    } finally {
      deleting.value = false;
    }
  }

  return {
    agents,
    conversations,
    detail,
    selectedAgentType,
    selectedMode,
    activeConversationId,
    activeSessionId,
    draft,
    pendingUserMessage,
    streamingAssistantText,
    optimisticMessages,
    displayMessages,
    activeMode,
    activeAgentType,
    activeAgent,
    latestTurn,
    latestAutoTurn,
    pendingApproval,
    loadingAgents,
    loadingList,
    loadingConversation,
    sending,
    approving,
    syncingConversation,
    autoProgress,
    autoProgressText,
    renaming,
    deleting,
    agentError,
    listError,
    conversationError,
    actionError,
    activeTitle,
    canSelectMode,
    canSelectAgent,
    canSend,
    agentDisplayName,
    capabilityDisplayName,
    autoProgressStageDisplayName,
    workerDisplayName,
    routeDisplayName,
    messageDocSources,
    messageRuntimeSources,
    agentDescription,
    traceStageDisplayName,
    initialize,
    refreshAgents,
    refreshConversations,
    refreshConversationDetail,
    openConversation,
    startNewConversation,
    submitMessage,
    resolvePendingApproval,
    renameActiveConversation,
    deleteActiveConversation,
  };
}
