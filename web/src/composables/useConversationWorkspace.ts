import { computed, ref } from "vue";

import {
  ApiError,
  deleteConversation,
  getConversation,
  listAgents,
  listConversations,
  renameConversation,
  sendChat,
} from "../lib/api";
import type {
  AgentDescriptor,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
} from "../lib/types";

export function useConversationWorkspace() {
  const agents = ref<AgentDescriptor[]>([]);
  const conversations = ref<ConversationSummary[]>([]);
  const detail = ref<ConversationDetail | null>(null);
  const selectedAgentType = ref("docker_support");
  const activeConversationId = ref<string | null>(null);
  const activeSessionId = ref<string | null>(null);
  const draft = ref("");

  const latestTurns = ref<Record<string, ChatResponse>>({});

  const loadingAgents = ref(false);
  const loadingList = ref(false);
  const loadingConversation = ref(false);
  const sending = ref(false);
  const renaming = ref(false);
  const deleting = ref(false);

  const agentError = ref("");
  const listError = ref("");
  const conversationError = ref("");
  const actionError = ref("");

  let conversationRequestVersion = 0;

  const activeTitle = computed(() => {
    if (detail.value?.conversation.title) {
      return detail.value.conversation.title;
    }
    return activeConversationId.value
      ? "Conversation"
      : "New conversation";
  });

  const activeAgentType = computed(
    () =>
      detail.value?.conversation.agent_type ??
      selectedAgentType.value,
  );

  const activeAgent = computed(
    () =>
      agents.value.find(
        (agent) => agent.agent_type === activeAgentType.value,
      ) ?? null,
  );

  const latestTurn = computed(() => {
    const id = activeConversationId.value;
    return id ? latestTurns.value[id] ?? null : null;
  });

  const canSelectAgent = computed(
    () => !activeConversationId.value && !sending.value,
  );

  const canSend = computed(
    () => draft.value.trim().length > 0 && !sending.value,
  );

  function errorText(error: unknown): string {
    if (error instanceof ApiError) {
      return error.detail;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return "Something went wrong.";
  }

  function agentDisplayName(agentType: string): string {
    return (
      agents.value.find((agent) => agent.agent_type === agentType)
        ?.display_name ?? agentType
    );
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

    try {
      const loaded = await getConversation(id);
      if (requestVersion === conversationRequestVersion) {
        detail.value = loaded;
        selectedAgentType.value = loaded.conversation.agent_type;
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
    conversationError.value = "";
    actionError.value = "";
    loadingConversation.value = false;
  }

  async function submitMessage(): Promise<boolean> {
    const message = draft.value.trim();
    if (!message || sending.value) {
      return false;
    }

    sending.value = true;
    actionError.value = "";

    try {
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
        detail.value = await getConversation(result.conversation_id);
      }

      await refreshConversations();
      return true;
    } catch (error) {
      actionError.value = errorText(error);
      return false;
    } finally {
      sending.value = false;
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
    activeConversationId,
    activeSessionId,
    draft,
    activeAgentType,
    activeAgent,
    latestTurn,
    loadingAgents,
    loadingList,
    loadingConversation,
    sending,
    renaming,
    deleting,
    agentError,
    listError,
    conversationError,
    actionError,
    activeTitle,
    canSelectAgent,
    canSend,
    agentDisplayName,
    initialize,
    refreshAgents,
    refreshConversations,
    openConversation,
    startNewConversation,
    submitMessage,
    renameActiveConversation,
    deleteActiveConversation,
  };
}
