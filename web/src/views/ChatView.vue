<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

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

const conversations = ref<ConversationSummary[]>([]);
const detail = ref<ConversationDetail | null>(null);
const activeConversationId = ref<string | null>(null);
const activeSessionId = ref<string | null>(null);
const latestTurn = ref<ChatResponse | null>(null);
const draft = ref("");
const loadingList = ref(false);
const loadingConversation = ref(false);
const sending = ref(false);
const errorMessage = ref("");

const activeTitle = computed(() => {
  if (detail.value?.conversation.title) {
    return detail.value.conversation.title;
  }
  return activeConversationId.value ? "Conversation" : "New conversation";
});

const canSend = computed(
  () => draft.value.trim().length > 0 && !sending.value,
);

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

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
  try {
    conversations.value = await listConversations();
  } catch (error) {
    errorMessage.value = errorText(error);
  } finally {
    loadingList.value = false;
  }
}

async function openConversation(id: string): Promise<void> {
  errorMessage.value = "";
  loadingConversation.value = true;
  latestTurn.value = null;
  activeSessionId.value = null;
  activeConversationId.value = id;

  try {
    detail.value = await getConversation(id);
  } catch (error) {
    errorMessage.value = errorText(error);
  } finally {
    loadingConversation.value = false;
  }
}

function startNewConversation(): void {
  activeConversationId.value = null;
  activeSessionId.value = null;
  detail.value = null;
  latestTurn.value = null;
  draft.value = "";
  errorMessage.value = "";
}

async function submitMessage(): Promise<void> {
  const message = draft.value.trim();
  if (!message || sending.value) {
    return;
  }

  sending.value = true;
  errorMessage.value = "";

  try {
    const result = await sendChat({
      message,
      conversationId: activeConversationId.value,
      sessionId: activeSessionId.value,
    });

    latestTurn.value = result;
    activeConversationId.value = result.conversation_id;
    activeSessionId.value = result.session_active
      ? result.session_id
      : null;
    draft.value = "";

    if (result.conversation_id) {
      detail.value = await getConversation(result.conversation_id);
    }
    await refreshConversations();
  } catch (error) {
    errorMessage.value = errorText(error);
  } finally {
    sending.value = false;
  }
}

async function renameActiveConversation(): Promise<void> {
  const conversation = detail.value?.conversation;
  if (!conversation) {
    return;
  }

  const nextTitle = window.prompt(
    "Conversation title",
    conversation.title ?? "",
  );
  if (nextTitle === null || !nextTitle.trim()) {
    return;
  }

  try {
    const updated = await renameConversation(
      conversation.id,
      nextTitle.trim(),
    );
    detail.value = {
      ...detail.value,
      conversation: updated,
    };
    await refreshConversations();
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

async function deleteActiveConversation(): Promise<void> {
  const conversation = detail.value?.conversation;
  if (!conversation) {
    return;
  }

  const confirmed = window.confirm(
    "Delete this conversation and its persisted history?",
  );
  if (!confirmed) {
    return;
  }

  try {
    await deleteConversation(conversation.id);
    startNewConversation();
    await refreshConversations();
  } catch (error) {
    errorMessage.value = errorText(error);
  }
}

onMounted(refreshConversations);
</script>

<template>
  <section class="chat-layout">
    <aside class="conversation-panel panel">
      <div class="panel__header conversation-panel__header">
        <div>
          <p class="section-label">History</p>
          <h2>Conversations</h2>
        </div>
        <button class="button button--primary" @click="startNewConversation">
          New
        </button>
      </div>

      <div v-if="loadingList" class="empty-state compact">
        Loading conversations…
      </div>

      <div v-else-if="conversations.length === 0" class="empty-state compact">
        No persisted conversations yet.
      </div>

      <div v-else class="conversation-list">
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{
            'conversation-item--active':
              conversation.id === activeConversationId,
          }"
          @click="openConversation(conversation.id)"
        >
          <strong>{{ conversation.title || "Untitled conversation" }}</strong>
          <span>{{ formatDate(conversation.updated_at) }}</span>
        </button>
      </div>
    </aside>

    <section class="chat-panel panel">
      <div class="panel__header chat-panel__header">
        <div>
          <p class="section-label">Docker Support</p>
          <h2>{{ activeTitle }}</h2>
        </div>

        <div v-if="detail" class="header-actions">
          <button class="button button--ghost" @click="renameActiveConversation">
            Rename
          </button>
          <button class="button button--danger" @click="deleteActiveConversation">
            Delete
          </button>
        </div>
      </div>

      <div v-if="errorMessage" class="alert alert--error">
        {{ errorMessage }}
      </div>

      <div class="message-stream">
        <div
          v-if="loadingConversation"
          class="empty-state"
        >
          Loading conversation…
        </div>

        <template v-else-if="detail?.messages.length">
          <article
            v-for="message in detail.messages"
            :key="message.id"
            class="message"
            :class="`message--${message.role}`"
          >
            <div class="message__meta">
              <span>{{ message.role }}</span>
              <span>{{ formatDate(message.created_at) }}</span>
            </div>
            <p>{{ message.content }}</p>

            <div
              v-if="message.execution"
              class="message__execution"
            >
              <span>
                workers:
                {{ message.execution.completed_workers.join(" → ") || "none" }}
              </span>
            </div>
          </article>
        </template>

        <div v-else class="empty-state">
          <div class="empty-state__badge">Agent</div>
          <h3>Start a Docker support conversation</h3>
          <p>
            Ask about Docker runtime failures, configuration, networking,
            images, containers, or documentation-backed troubleshooting.
          </p>
        </div>
      </div>

      <form class="composer" @submit.prevent="submitMessage">
        <div
          v-if="activeSessionId"
          class="clarification-banner"
        >
          Clarification session active. Your next message continues the same
          agent turn.
        </div>

        <div class="composer__row">
          <textarea
            v-model="draft"
            rows="3"
            placeholder="Describe the Docker issue…"
            :disabled="sending"
            @keydown.ctrl.enter.prevent="submitMessage"
          />
          <button
            class="button button--primary composer__send"
            type="submit"
            :disabled="!canSend"
          >
            {{ sending ? "Running…" : "Send" }}
          </button>
        </div>
        <p class="composer__hint">
          Ctrl + Enter to send
        </p>
      </form>
    </section>

    <aside class="trace-panel panel">
      <div class="panel__header">
        <div>
          <p class="section-label">Latest turn</p>
          <h2>Execution</h2>
        </div>
      </div>

      <div v-if="!latestTurn" class="empty-state compact">
        Run a turn to inspect routing, workers, and sources.
      </div>

      <template v-else>
        <dl class="fact-list">
          <div>
            <dt>Route</dt>
            <dd>{{ latestTurn.route }}</dd>
          </div>
          <div>
            <dt>Docs</dt>
            <dd>{{ latestTurn.use_docs ? "enabled" : "not used" }}</dd>
          </div>
          <div>
            <dt>Clarification</dt>
            <dd>{{ latestTurn.session_active ? "active" : "complete" }}</dd>
          </div>
        </dl>

        <section class="trace-section">
          <h3>Reason</h3>
          <p>{{ latestTurn.reason }}</p>
        </section>

        <section v-if="latestTurn.execution" class="trace-section">
          <h3>Workers</h3>
          <div class="chip-row">
            <span
              v-for="worker in latestTurn.execution.completed_workers"
              :key="worker"
              class="chip"
            >
              {{ worker }}
            </span>
          </div>
        </section>

        <section
          v-if="latestTurn.runtime_sources.length"
          class="trace-section"
        >
          <h3>Runtime sources</h3>
          <div
            v-for="source in latestTurn.runtime_sources"
            :key="`${source.index}-${source.tool}`"
            class="source-card"
          >
            <strong>{{ source.tool }}</strong>
            <code>{{ source.command.join(" ") }}</code>
          </div>
        </section>

        <section
          v-if="latestTurn.doc_sources.length"
          class="trace-section"
        >
          <h3>Documentation</h3>
          <a
            v-for="source in latestTurn.doc_sources"
            :key="`${source.index}-${source.source_url}`"
            class="source-card source-card--link"
            :href="source.source_url"
            target="_blank"
            rel="noreferrer"
          >
            <strong>{{ source.title }}</strong>
            <span>{{ source.section }}</span>
          </a>
        </section>
      </template>
    </aside>
  </section>
</template>
