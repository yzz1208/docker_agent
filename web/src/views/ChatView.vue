<script setup lang="ts">
import { onMounted, ref } from "vue";

import AppDialog from "../components/AppDialog.vue";
import { useConversationWorkspace } from "../composables/useConversationWorkspace";

const workspace = useConversationWorkspace();

const renameDialogOpen = ref(false);
const deleteDialogOpen = ref(false);
const renameTitle = ref("");

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function openRenameDialog(): void {
  const conversation = workspace.detail.value?.conversation;
  if (!conversation) {
    return;
  }
  renameTitle.value = conversation.title ?? "";
  renameDialogOpen.value = true;
}

function closeRenameDialog(): void {
  if (!workspace.renaming.value) {
    renameDialogOpen.value = false;
  }
}

async function confirmRename(): Promise<void> {
  const renamed = await workspace.renameActiveConversation(
    renameTitle.value,
  );
  if (renamed) {
    renameDialogOpen.value = false;
  }
}

function openDeleteDialog(): void {
  if (!workspace.detail.value) {
    return;
  }
  deleteDialogOpen.value = true;
}

function closeDeleteDialog(): void {
  if (!workspace.deleting.value) {
    deleteDialogOpen.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  const deleted = await workspace.deleteActiveConversation();
  if (deleted) {
    deleteDialogOpen.value = false;
  }
}

onMounted(workspace.initialize);
</script>

<template>
  <section class="chat-layout">
    <aside class="conversation-panel panel">
      <div class="panel__header conversation-panel__header">
        <div>
          <p class="section-label">History</p>
          <h2>Conversations</h2>
        </div>
        <button
          class="button button--primary"
          :disabled="workspace.sending.value"
          @click="workspace.startNewConversation"
        >
          New
        </button>
      </div>

      <div
        v-if="workspace.listError.value"
        class="panel-state panel-state--error"
      >
        <strong>Could not load conversations.</strong>
        <span>{{ workspace.listError.value }}</span>
        <button
          class="button button--ghost"
          type="button"
          @click="workspace.refreshConversations"
        >
          Retry
        </button>
      </div>

      <div
        v-else-if="workspace.loadingList.value"
        class="empty-state compact"
      >
        Loading conversations…
      </div>

      <div
        v-else-if="workspace.conversations.value.length === 0"
        class="empty-state compact"
      >
        No persisted conversations yet.
      </div>

      <div v-else class="conversation-list">
        <button
          v-for="conversation in workspace.conversations.value"
          :key="conversation.id"
          class="conversation-item"
          :class="{
            'conversation-item--active':
              conversation.id === workspace.activeConversationId.value,
          }"
          :disabled="workspace.sending.value"
          @click="workspace.openConversation(conversation.id)"
        >
          <strong>{{ conversation.title || "Untitled conversation" }}</strong>
          <div class="conversation-item__meta">
            <span class="conversation-item__agent">
              {{ workspace.agentDisplayName(conversation.agent_type) }}
            </span>
            <span>{{ formatDate(conversation.updated_at) }}</span>
          </div>
        </button>
      </div>
    </aside>

    <section class="chat-panel panel">
      <div class="panel__header chat-panel__header">
        <div>
          <p class="section-label">
            {{
              workspace.activeAgent.value?.display_name ??
              workspace.activeAgentType.value
            }}
          </p>
          <h2>{{ workspace.activeTitle.value }}</h2>
        </div>

        <div class="chat-header-controls">
          <label
            v-if="!workspace.activeConversationId.value"
            class="agent-picker"
          >
            <span>Agent</span>
            <select
              v-model="workspace.selectedAgentType.value"
              :disabled="
                workspace.loadingAgents.value ||
                !workspace.canSelectAgent.value
              "
            >
              <option
                v-for="agent in workspace.agents.value"
                :key="agent.agent_type"
                :value="agent.agent_type"
              >
                {{ agent.display_name }}
              </option>
            </select>
          </label>

          <div v-else class="agent-lock">
            <span>Agent</span>
            <strong>
              {{
                workspace.activeAgent.value?.display_name ??
                workspace.activeAgentType.value
              }}
            </strong>
          </div>

          <div v-if="workspace.detail.value" class="header-actions">
            <button
              class="button button--ghost"
              :disabled="
                workspace.sending.value ||
                workspace.renaming.value ||
                workspace.deleting.value
              "
              @click="openRenameDialog"
            >
              Rename
            </button>
            <button
              class="button button--danger"
              :disabled="
                workspace.sending.value ||
                workspace.renaming.value ||
                workspace.deleting.value
              "
              @click="openDeleteDialog"
            >
              Delete
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="workspace.agentError.value"
        class="alert alert--error"
      >
        <span>{{ workspace.agentError.value }}</span>
        <button
          class="button button--ghost"
          type="button"
          @click="workspace.refreshAgents"
        >
          Retry Agent catalog
        </button>
      </div>

      <div
        v-if="workspace.actionError.value"
        class="alert alert--error alert--dismissible"
      >
        <span>{{ workspace.actionError.value }}</span>
        <button
          type="button"
          aria-label="Dismiss error"
          @click="workspace.actionError.value = ''"
        >
          ×
        </button>
      </div>

      <div class="message-stream">
        <div
          v-if="workspace.loadingConversation.value"
          class="empty-state"
        >
          Loading conversation…
        </div>

        <div
          v-else-if="workspace.conversationError.value"
          class="panel-state panel-state--error panel-state--centered"
        >
          <strong>Could not open this conversation.</strong>
          <span>{{ workspace.conversationError.value }}</span>
          <button
            v-if="workspace.activeConversationId.value"
            class="button button--ghost"
            type="button"
            @click="
              workspace.openConversation(
                workspace.activeConversationId.value,
              )
            "
          >
            Retry
          </button>
        </div>

        <template
          v-else-if="workspace.detail.value?.messages.length"
        >
          <article
            v-for="message in workspace.detail.value.messages"
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
                {{
                  message.execution.completed_workers.join(" → ") ||
                  "none"
                }}
              </span>
            </div>
          </article>
        </template>

        <div v-else class="empty-state">
          <div class="empty-state__badge">Agent</div>
          <h3>
            Start a conversation with
            {{
              workspace.activeAgent.value?.display_name ??
              workspace.activeAgentType.value
            }}
          </h3>
          <p>
            {{
              workspace.activeAgent.value?.description ??
              "Choose a registered Agent and describe the task."
            }}
          </p>
          <div
            v-if="workspace.activeAgent.value"
            class="agent-capability-summary"
          >
            <div class="chip-row">
              <span
                v-for="capability in workspace.activeAgent.value.capabilities"
                :key="`capability-${capability}`"
                class="chip"
              >
                {{ capability }}
              </span>
              <span
                v-for="toolset in workspace.activeAgent.value.toolsets"
                :key="`toolset-${toolset}`"
                class="chip"
              >
                tool: {{ toolset }}
              </span>
              <span
                v-for="role in workspace.activeAgent.value.worker_roles"
                :key="`worker-${role}`"
                class="chip"
              >
                worker: {{ role }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <form class="composer" @submit.prevent="workspace.submitMessage">
        <div
          v-if="workspace.activeSessionId.value"
          class="clarification-banner"
        >
          Clarification session active. Your next message continues the same
          agent turn.
        </div>

        <div class="composer__row">
          <textarea
            v-model="workspace.draft.value"
            rows="3"
            :placeholder="`Ask ${workspace.activeAgent.value?.display_name ?? workspace.activeAgentType.value}…`"
            :disabled="workspace.sending.value"
            @keydown.ctrl.enter.prevent="workspace.submitMessage"
          />
          <button
            class="button button--primary composer__send"
            type="submit"
            :disabled="!workspace.canSend.value"
          >
            {{ workspace.sending.value ? "Running…" : "Send" }}
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

      <div
        v-if="!workspace.latestTurn.value"
        class="empty-state compact"
      >
        Run a turn to inspect routing, workers, and sources.
      </div>

      <template v-else>
        <dl class="fact-list">
          <div>
            <dt>Agent</dt>
            <dd>
              {{
                workspace.activeAgent.value?.display_name ??
                workspace.activeAgentType.value
              }}
            </dd>
          </div>
          <div>
            <dt>Route</dt>
            <dd>{{ workspace.latestTurn.value.route }}</dd>
          </div>
          <div>
            <dt>Docs</dt>
            <dd>
              {{
                workspace.latestTurn.value.use_docs
                  ? "enabled"
                  : "not used"
              }}
            </dd>
          </div>
          <div>
            <dt>Clarification</dt>
            <dd>
              {{
                workspace.latestTurn.value.session_active
                  ? "active"
                  : "complete"
              }}
            </dd>
          </div>
        </dl>

        <section class="trace-section">
          <h3>Reason</h3>
          <p>{{ workspace.latestTurn.value.reason }}</p>
        </section>

        <section
          v-if="workspace.activeAgent.value"
          class="trace-section"
        >
          <h3>Agent capabilities</h3>
          <p>{{ workspace.activeAgent.value.description }}</p>
          <div class="chip-row">
            <span
              v-for="capability in workspace.activeAgent.value.capabilities"
              :key="`trace-capability-${capability}`"
              class="chip"
            >
              {{ capability }}
            </span>
          </div>
        </section>

        <section
          v-if="workspace.latestTurn.value.execution"
          class="trace-section"
        >
          <h3>Workers</h3>
          <div class="chip-row">
            <span
              v-for="worker in (
                workspace.latestTurn.value.execution?.completed_workers ?? []
              )"
              :key="worker"
              class="chip"
            >
              {{ worker }}
            </span>
          </div>
        </section>

        <section
          v-if="workspace.latestTurn.value.runtime_sources.length"
          class="trace-section"
        >
          <h3>Runtime sources</h3>
          <div
            v-for="source in workspace.latestTurn.value.runtime_sources"
            :key="`${source.index}-${source.tool}`"
            class="source-card"
          >
            <strong>{{ source.tool }}</strong>
            <code>{{ source.command.join(" ") }}</code>
          </div>
        </section>

        <section
          v-if="workspace.latestTurn.value.doc_sources.length"
          class="trace-section"
        >
          <h3>Documentation</h3>
          <a
            v-for="source in workspace.latestTurn.value.doc_sources"
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

    <AppDialog
      :open="renameDialogOpen"
      title="Rename conversation"
      description="Use a concise title that makes the issue easy to find later."
      confirm-label="Save title"
      :busy="workspace.renaming.value"
      @close="closeRenameDialog"
      @confirm="confirmRename"
    >
      <label class="field">
        <span>Title</span>
        <input
          v-model="renameTitle"
          maxlength="240"
          autocomplete="off"
          @keydown.enter.prevent="confirmRename"
        />
      </label>
    </AppDialog>

    <AppDialog
      :open="deleteDialogOpen"
      title="Delete conversation"
      description="This permanently deletes the persisted messages and execution history for this conversation."
      confirm-label="Delete conversation"
      :danger="true"
      :busy="workspace.deleting.value"
      @close="closeDeleteDialog"
      @confirm="confirmDelete"
    />
  </section>
</template>
