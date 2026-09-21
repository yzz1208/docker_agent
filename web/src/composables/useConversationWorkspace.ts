import { computed, ref } from "vue";

import {
  ApiError,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  sendChat,
} from "../lib/api";
import type {
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
} from "../lib/types";

export function useConversationWorkspace() {
  const conversations = ref<ConversationSummary[]>([]);
  const detail = ref<ConversationDetail | null>(null);
  const activeConversationId = ref<string | null>(null);
  const activeSessionId = ref<string | null>(null);
  const draft = ref("");

  const latestTurns = ref<Record<string, ChatResponse>>({});

  const loadingList = ref(false);
  const loadingConversation = ref(false);
  const sending = ref(false);
  const renaming = ref(false);
  const deleting = ref(false);

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

  const latestTurn = computed(() => {
    const id = activeConversationId.value;
    return id ? latestTurns.value[id] ?? null : null;
  });

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
        conversationId: activeConversationId.value,
        sessionId: activeSessionId.value,
      });

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
    conversations,
    detail,
    activeConversationId,
    activeSessionId,
    draft,
    latestTurn,
    loadingList,
    loadingConversation,
    sending,
    renaming,
    deleting,
    listError,
    conversationError,
    actionError,
    activeTitle,
    canSend,
    refreshConversations,
    openConversation,
    startNewConversation,
    submitMessage,
    renameActiveConversation,
    deleteActiveConversation,
  };
}
