<script setup lang="ts">
import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";

import AppDialog from "../components/AppDialog.vue";
import MessageContent from "../components/MessageContent.vue";
import { useConversationWorkspace } from "../composables/useConversationWorkspace";

const workspace = useConversationWorkspace();

const messageStream = ref<HTMLElement | null>(null);
const elapsedSeconds = ref(0);
let elapsedTimer: number | null = null;
const renameDialogOpen = ref(false);
const deleteDialogOpen = ref(false);
const renameTitle = ref("");

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function roleLabel(role: string): string {
  if (role === "user") return "你";
  if (role === "assistant") return "助手";
  return role;
}

function openRenameDialog(): void {
  const conversation = workspace.detail.value?.conversation;
  if (!conversation) return;
  renameTitle.value = conversation.title ?? "";
  renameDialogOpen.value = true;
}

function closeRenameDialog(): void {
  if (!workspace.renaming.value) renameDialogOpen.value = false;
}

async function confirmRename(): Promise<void> {
  const renamed = await workspace.renameActiveConversation(renameTitle.value);
  if (renamed) renameDialogOpen.value = false;
}

function openDeleteDialog(): void {
  if (workspace.detail.value) deleteDialogOpen.value = true;
}

function closeDeleteDialog(): void {
  if (!workspace.deleting.value) deleteDialogOpen.value = false;
}

async function confirmDelete(): Promise<void> {
  const deleted = await workspace.deleteActiveConversation();
  if (deleted) deleteDialogOpen.value = false;
}

async function scrollMessagesToBottom(): Promise<void> {
  await nextTick();
  const element = messageStream.value;
  if (!element) return;
  element.scrollTo({
    top: element.scrollHeight,
    behavior: "smooth",
  });
}

watch(
  () => workspace.sending.value || workspace.approving.value,
  (active) => {
    if (elapsedTimer !== null) {
      window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
    elapsedSeconds.value = 0;
    if (active) {
      const started = Date.now();
      elapsedTimer = window.setInterval(() => {
        elapsedSeconds.value = Math.floor(
          (Date.now() - started) / 1000,
        );
      }, 1000);
    }
  },
);

watch(
  () => [
    workspace.displayMessages.value.length,
    workspace.sending.value,
    workspace.approving.value,
    Boolean(workspace.pendingApproval.value),
  ],
  () => {
    void scrollMessagesToBottom();
  },
);

onMounted(async () => {
  await workspace.initialize();
  await scrollMessagesToBottom();
});

onBeforeUnmount(() => {
  if (elapsedTimer !== null) {
    window.clearInterval(elapsedTimer);
  }
});
</script>

<template>
  <section class="chat-layout">
    <aside class="conversation-panel panel">
      <div class="panel__header conversation-panel__header">
        <div>
          <p class="section-label">历史记录</p>
          <h2>对话</h2>
        </div>
        <button
          class="button button--primary"
          :disabled="
            workspace.sending.value ||
            workspace.approving.value
          "
          @click="workspace.startNewConversation"
        >
          新建
        </button>
      </div>

      <div v-if="workspace.listError.value" class="panel-state panel-state--error">
        <strong>无法加载对话记录</strong>
        <span>{{ workspace.listError.value }}</span>
        <button class="button button--ghost" type="button" @click="workspace.refreshConversations">
          重试
        </button>
      </div>
      <div v-else-if="workspace.loadingList.value" class="empty-state compact">
        正在加载对话…
      </div>
      <div v-else-if="workspace.conversations.value.length === 0" class="empty-state compact">
        暂无历史对话。
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
          :disabled="
            workspace.sending.value ||
            workspace.approving.value
          "
          @click="workspace.openConversation(conversation.id)"
        >
          <strong>{{ conversation.title || "未命名对话" }}</strong>
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
              workspace.activeMode.value === "auto"
                ? "智能编排"
                : workspace.agentDisplayName(workspace.activeAgentType.value)
            }}
          </p>
          <h2>{{ workspace.activeTitle.value }}</h2>
        </div>

        <div class="chat-header-controls">
          <div
            v-if="!workspace.activeConversationId.value"
            class="chat-mode-switch"
            aria-label="对话模式"
          >
            <button
              type="button"
              :class="{
                'chat-mode-switch__item--active':
                  workspace.selectedMode.value === 'manual',
              }"
              :disabled="!workspace.canSelectMode.value"
              @click="workspace.selectedMode.value = 'manual'"
            >
              手动专家
            </button>
            <button
              type="button"
              :class="{
                'chat-mode-switch__item--active':
                  workspace.selectedMode.value === 'auto',
              }"
              :disabled="!workspace.canSelectMode.value"
              @click="workspace.selectedMode.value = 'auto'"
            >
              <span class="auto-dot" />
              智能编排
            </button>
          </div>

          <div v-else class="mode-lock">
            <span>模式</span>
            <strong>
              {{ workspace.activeMode.value === "auto" ? "智能编排" : "手动专家" }}
            </strong>
          </div>

          <label
            v-if="
              !workspace.activeConversationId.value &&
              workspace.selectedMode.value === 'manual'
            "
            class="agent-picker"
          >
            <span>专家</span>
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
                {{ workspace.agentDisplayName(agent.agent_type) }}
              </option>
            </select>
          </label>

          <div
            v-else-if="
              workspace.activeConversationId.value &&
              workspace.activeMode.value === 'manual'
            "
            class="agent-lock"
          >
            <span>专家</span>
            <strong>{{ workspace.agentDisplayName(workspace.activeAgentType.value) }}</strong>
          </div>

          <div v-else-if="workspace.activeMode.value === 'auto'" class="agent-lock agent-lock--auto">
            <span>当前专家</span>
            <strong>
              {{
                workspace.latestAutoTurn.value?.current_agent_type
                  ? workspace.agentDisplayName(
                      workspace.latestAutoTurn.value.current_agent_type,
                    )
                  : "自动选择"
              }}
            </strong>
          </div>

          <div v-if="workspace.detail.value" class="header-actions">
            <button
              class="button button--ghost"
              :disabled="
                workspace.sending.value ||
                workspace.approving.value ||
                workspace.renaming.value ||
                workspace.deleting.value
              "
              @click="openRenameDialog"
            >
              重命名
            </button>
            <button
              class="button button--danger"
              :disabled="
                workspace.sending.value ||
                workspace.approving.value ||
                workspace.renaming.value ||
                workspace.deleting.value
              "
              @click="openDeleteDialog"
            >
              删除
            </button>
          </div>
        </div>
      </div>

      <div v-if="workspace.agentError.value" class="alert alert--error">
        <span>{{ workspace.agentError.value }}</span>
        <button class="button button--ghost" type="button" @click="workspace.refreshAgents">
          重新加载专家
        </button>
      </div>

      <div v-if="workspace.actionError.value" class="alert alert--error alert--dismissible">
        <span>{{ workspace.actionError.value }}</span>
        <button type="button" aria-label="关闭错误提示" @click="workspace.actionError.value = ''">
          ×
        </button>
      </div>

      <div
        v-if="
          workspace.syncingConversation.value &&
          !workspace.sending.value
        "
        class="conversation-sync-note"
        aria-live="polite"
      >
        <span class="conversation-sync-note__dot" />
        回答已完成，正在同步对话记录…
      </div>

      <div
        v-if="workspace.sending.value && workspace.activeMode.value === 'auto'"
        class="auto-running"
      >
        <div class="auto-running__pulse"><span /><span /><span /></div>
        <div>
          <strong>正在智能编排</strong>
          <p>
            {{
              elapsedSeconds > 0
                ? `${workspace.autoProgressText.value} · 已处理 ${elapsedSeconds}s`
                : workspace.autoProgressText.value
            }}
          </p>
        </div>
      </div>

      <section
        v-if="workspace.pendingApproval.value"
        class="approval-card"
        aria-live="polite"
      >
        <div class="approval-card__accent" />
        <div class="approval-card__content">
          <div class="approval-card__header">
            <div>
              <span class="approval-card__eyebrow">需要你的批准</span>
              <h3>是否允许继续跨专家处理？</h3>
            </div>
            <span class="approval-card__status">已暂停</span>
          </div>

          <div class="approval-route">
            <div>
              <span>当前</span>
              <strong>
                {{
                  workspace.pendingApproval.value.source_agent_type
                    ? workspace.agentDisplayName(
                        workspace.pendingApproval.value.source_agent_type,
                      )
                    : "智能编排"
                }}
              </strong>
            </div>
            <span class="approval-route__arrow">→</span>
            <div>
              <span>下一位专家</span>
              <strong>
                {{
                  workspace.agentDisplayName(
                    workspace.pendingApproval.value.target_agent_type,
                  )
                }}
              </strong>
            </div>
          </div>

          <div class="approval-card__reason">
            <span>转交原因</span>
            <p>{{ workspace.pendingApproval.value.reason }}</p>
          </div>

          <div class="approval-card__meta">
            <span class="chip chip--soft">
              能力：{{
                workspace.capabilityDisplayName(
                  workspace.pendingApproval.value.capability,
                )
              }}
            </span>
            <span class="approval-card__question">
              当前问题：{{ workspace.pendingApproval.value.question }}
            </span>
          </div>

          <div class="approval-card__actions">
            <button
              class="button button--ghost approval-card__deny"
              type="button"
              :disabled="workspace.approving.value"
              @click="workspace.resolvePendingApproval(false)"
            >
              拒绝
            </button>
            <button
              class="button button--primary approval-card__approve"
              type="button"
              :disabled="workspace.approving.value"
              @click="workspace.resolvePendingApproval(true)"
            >
              {{
                workspace.approving.value
                  ? "正在处理…"
                  : "允许继续"
              }}
            </button>
          </div>
        </div>
      </section>

      <div ref="messageStream" class="message-stream">
        <div v-if="workspace.loadingConversation.value" class="empty-state">
          正在加载对话…
        </div>

        <div
          v-else-if="workspace.conversationError.value"
          class="panel-state panel-state--error panel-state--centered"
        >
          <strong>无法打开该对话</strong>
          <span>{{ workspace.conversationError.value }}</span>
          <button
            v-if="workspace.activeConversationId.value"
            class="button button--ghost"
            type="button"
            @click="workspace.openConversation(workspace.activeConversationId.value)"
          >
            重试
          </button>
        </div>

        <template v-else-if="workspace.displayMessages.value.length">
          <article
            v-for="message in workspace.displayMessages.value"
            :key="message.id"
            class="message"
            :class="'message--' + message.role"
          >
            <div class="message__meta">
              <span>{{ roleLabel(message.role) }}</span>
              <span>{{ formatDate(message.created_at) }}</span>
            </div>
            <MessageContent :content="message.content" />

            <div
              v-if="message.execution && workspace.activeMode.value === 'manual'"
              class="message__execution"
            >
              <span>
                执行链：
                {{
                  message.execution.completed_workers
                    .map(workspace.workerDisplayName)
                    .join(" → ") || "无"
                }}
              </span>
            </div>
          </article>

          <article
            v-if="workspace.pendingUserMessage.value"
            class="message message--user message--pending"
          >
            <div class="message__meta">
              <span>你</span>
              <span>发送中</span>
            </div>
            <MessageContent :content="workspace.pendingUserMessage.value" />
          </article>

          <article
            v-if="workspace.pendingUserMessage.value"
            class="message message--assistant message--thinking"
          >
            <div class="message__meta">
              <span>助手</span>
              <span>处理中</span>
            </div>
            <div class="thinking-indicator">
              <span /><span /><span />
              <strong>
                {{
                  workspace.activeMode.value === "auto"
                    ? elapsedSeconds > 0
                      ? `${workspace.autoProgressText.value} · ${elapsedSeconds}s`
                      : workspace.autoProgressText.value
                    : elapsedSeconds > 0
                      ? `正在处理 · ${elapsedSeconds}s`
                      : "正在处理"
                }}
              </strong>
            </div>
          </article>
        </template>

        <template v-else-if="workspace.pendingUserMessage.value">
          <article class="message message--user message--pending">
            <div class="message__meta">
              <span>你</span>
              <span>发送中</span>
            </div>
            <MessageContent :content="workspace.pendingUserMessage.value" />
          </article>
          <article class="message message--assistant message--thinking">
            <div class="message__meta">
              <span>助手</span>
              <span>处理中</span>
            </div>
            <div class="thinking-indicator">
              <span /><span /><span />
              <strong>
                {{
                  workspace.activeMode.value === "auto"
                    ? elapsedSeconds > 0
                      ? `${workspace.autoProgressText.value} · ${elapsedSeconds}s`
                      : workspace.autoProgressText.value
                    : elapsedSeconds > 0
                      ? `正在处理 · ${elapsedSeconds}s`
                      : "正在处理"
                }}
              </strong>
            </div>
          </article>
        </template>

        <div v-else class="empty-state chat-empty-state">
          <div
            class="empty-state__badge"
            :class="{
              'empty-state__badge--auto':
                workspace.activeMode.value === 'auto',
            }"
          >
            {{ workspace.activeMode.value === "auto" ? "AUTO" : "AI" }}
          </div>

          <template v-if="workspace.activeMode.value === 'auto'">
            <h3>直接描述问题，剩下的交给智能编排</h3>
            <p>系统会快速判断问题类型，选择合适专家，并在需要时安全转交与综合结果。</p>
            <div class="auto-feature-grid">
              <div><strong>快速判断</strong><span>自动选择合适专家</span></div>
              <div><strong>受控转交</strong><span>跨专家前先请求批准</span></div>
              <div><strong>清晰结果</strong><span>保留来源与处理过程</span></div>
            </div>
            <div class="quick-prompt-list" aria-label="示例问题">
              <button
                type="button"
                @click="workspace.draft.value = '介绍一下这个平台'"
              >
                <span>了解平台</span>
                <strong>介绍一下这个平台</strong>
              </button>
              <button
                type="button"
                @click="workspace.draft.value = 'Docker daemon 连不上，帮我排查一下'"
              >
                <span>Docker 问题</span>
                <strong>Docker daemon 连不上</strong>
              </button>
              <button
                type="button"
                @click="workspace.draft.value = '容器正常，但 checkout-api 持续返回 503，继续帮我排查'"
              >
                <span>跨专家排障</span>
                <strong>容器正常但服务持续 503</strong>
              </button>
            </div>
            <RouterLink class="button button--ghost chat-guide-link" to="/guide">
              不知道怎么用？查看使用指南
            </RouterLink>
          </template>

          <template v-else>
            <h3>
              开始与 {{ workspace.agentDisplayName(workspace.activeAgentType.value) }} 对话
            </h3>
            <p>
              {{
                workspace.agentDescription(workspace.activeAgentType.value) ||
                "选择一个专家，然后描述你希望解决的问题。"
              }}
            </p>
            <div v-if="workspace.activeAgent.value" class="agent-capability-summary">
              <div class="chip-row">
                <span
                  v-for="capability in workspace.activeAgent.value.capabilities"
                  :key="'capability-' + capability"
                  class="chip"
                >
                  {{ workspace.capabilityDisplayName(capability) }}
                </span>
                <span
                  v-for="toolset in workspace.activeAgent.value.toolsets"
                  :key="'toolset-' + toolset"
                  class="chip"
                >
                  工具：{{ toolset }}
                </span>
              </div>
            </div>
          </template>
        </div>
      </div>

      <form class="composer" @submit.prevent="workspace.submitMessage">
        <div
          v-if="
            workspace.activeSessionId.value &&
            workspace.activeMode.value === 'manual'
          "
          class="clarification-banner"
        >
          当前正在等待补充信息。你的下一条消息会继续同一个专家回合。
        </div>

        <div class="composer__row">
          <textarea
            v-model="workspace.draft.value"
            rows="3"
            :placeholder="
              workspace.pendingApproval.value
                ? '请先处理上方审批，再继续发送消息…'
                : workspace.activeMode.value === 'auto'
                  ? '直接描述问题，例如：容器正常，但 checkout-api 仍持续返回 503…'
                  : '向 ' + workspace.agentDisplayName(workspace.activeAgentType.value) + ' 提问…'
            "
            :disabled="
              workspace.sending.value ||
              workspace.approving.value ||
              Boolean(workspace.pendingApproval.value)
            "
            @keydown.ctrl.enter.prevent="workspace.submitMessage"
          />
          <button
            class="button button--primary composer__send"
            type="submit"
            :disabled="!workspace.canSend.value"
          >
            {{
              workspace.pendingApproval.value
                ? "等待审批"
                : workspace.sending.value
                  ? elapsedSeconds > 0
                    ? `处理中 ${elapsedSeconds}s`
                    : workspace.activeMode.value === "auto"
                      ? "处理中…"
                      : "执行中…"
                  : "发送"
            }}
          </button>
        </div>
        <p class="composer__hint">
          {{
            workspace.pendingApproval.value
              ? "当前工作流已暂停，审批后会从原位置继续。"
              : "Ctrl + Enter 发送"
          }}
        </p>
      </form>
    </section>

    <aside class="trace-panel panel">
      <div class="panel__header">
        <div>
          <p class="section-label">
            {{ workspace.activeMode.value === "auto" ? "智能编排" : "最近回合" }}
          </p>
          <h2>{{ workspace.activeMode.value === "auto" ? "处理过程" : "执行详情" }}</h2>
        </div>
      </div>

      <template v-if="workspace.activeMode.value === 'auto'">
        <div v-if="!workspace.latestAutoTurn.value" class="empty-state compact trace-empty-guide">
          <strong>这里会显示处理过程</strong>
          <span>包括智能判断、专家处理、跨专家转交和综合结论。</span>
          <span>普通问题会走快速路径，不会额外增加审批步骤。</span>
        </div>

        <template v-else>
          <div class="auto-status-card">
            <div class="auto-status-card__icon">✦</div>
            <div>
              <span>当前处理专家</span>
              <strong>
                {{
                  workspace.latestAutoTurn.value.current_agent_type
                    ? workspace.agentDisplayName(
                        workspace.latestAutoTurn.value.current_agent_type,
                      )
                    : "等待选择"
                }}
              </strong>
            </div>
            <span
              class="auto-status-badge"
              :class="{
                'auto-status-badge--synthesis':
                  workspace.latestAutoTurn.value.synthesized,
                'auto-status-badge--approval':
                  workspace.latestAutoTurn.value.needs_approval,
              }"
            >
              {{
                workspace.latestAutoTurn.value.needs_approval
                  ? "等待批准"
                  : workspace.latestAutoTurn.value.synthesized
                    ? "已综合"
                    : "快速路径"
              }}
            </span>
          </div>

          <div class="orchestration-timeline">
            <div
              v-for="(step, index) in workspace.latestAutoTurn.value.trace"
              :key="index + '-' + step.stage + '-' + step.agent_type"
              class="orchestration-step"
              :class="'orchestration-step--' + step.stage"
            >
              <div class="orchestration-step__rail">
                <span class="orchestration-step__dot" />
              </div>
              <div class="orchestration-step__body">
                <div class="orchestration-step__head">
                  <strong>{{ workspace.traceStageDisplayName(step.stage) }}</strong>
                  <span v-if="step.agent_type">
                    {{ workspace.agentDisplayName(step.agent_type) }}
                  </span>
                </div>
                <p>{{ step.reason }}</p>
                <span v-if="step.capability" class="chip chip--soft">
                  {{ workspace.capabilityDisplayName(step.capability) }}
                </span>
              </div>
            </div>
          </div>

          <section
            v-if="workspace.latestAutoTurn.value.specialist_results.length"
            class="trace-section"
          >
            <h3>专家公开结果</h3>
            <div
              v-for="result in workspace.latestAutoTurn.value.specialist_results"
              :key="result.agent_type + '-' + result.route"
              class="specialist-result-card"
            >
              <div>
                <strong>{{ workspace.agentDisplayName(result.agent_type) }}</strong>
                <span>{{ workspace.routeDisplayName(result.route) }}</span>
              </div>
              <p v-if="result.summary">{{ result.summary }}</p>
              <p v-else-if="result.clarification">{{ result.clarification }}</p>
            </div>
          </section>
        </template>
      </template>

      <template v-else>
        <div v-if="!workspace.latestTurn.value" class="empty-state compact">
          执行一个回合后，这里会显示路由、Worker 与来源信息。
        </div>

        <template v-else>
          <dl class="fact-list">
            <div>
              <dt>专家</dt>
              <dd>{{ workspace.agentDisplayName(workspace.activeAgentType.value) }}</dd>
            </div>
            <div>
              <dt>路由</dt>
              <dd>{{ workspace.routeDisplayName(workspace.latestTurn.value.route) }}</dd>
            </div>
            <div>
              <dt>文档</dt>
              <dd>{{ workspace.latestTurn.value.use_docs ? "已启用" : "未使用" }}</dd>
            </div>
            <div>
              <dt>补充信息</dt>
              <dd>{{ workspace.latestTurn.value.session_active ? "等待中" : "已完成" }}</dd>
            </div>
          </dl>

          <section class="trace-section">
            <h3>判断原因</h3>
            <p>{{ workspace.latestTurn.value.reason }}</p>
          </section>

          <section v-if="workspace.activeAgent.value" class="trace-section">
            <h3>专家能力</h3>
            <p>{{ workspace.agentDescription(workspace.activeAgentType.value) }}</p>
            <div class="chip-row">
              <span
                v-for="capability in workspace.activeAgent.value.capabilities"
                :key="'trace-capability-' + capability"
                class="chip"
              >
                {{ workspace.capabilityDisplayName(capability) }}
              </span>
            </div>
          </section>

          <section v-if="workspace.latestTurn.value.execution" class="trace-section">
            <h3>Worker</h3>
            <div class="chip-row">
              <span
                v-for="worker in (workspace.latestTurn.value.execution?.completed_workers ?? [])"
                :key="worker"
                class="chip"
              >
                {{ workspace.workerDisplayName(worker) }}
              </span>
            </div>
          </section>

          <section v-if="workspace.latestTurn.value.runtime_sources.length" class="trace-section">
            <h3>运行时来源</h3>
            <div
              v-for="source in workspace.latestTurn.value.runtime_sources"
              :key="source.index + '-' + source.tool"
              class="source-card"
            >
              <strong>{{ source.tool }}</strong>
              <code>{{ source.command.join(" ") }}</code>
            </div>
          </section>

          <section v-if="workspace.latestTurn.value.doc_sources.length" class="trace-section">
            <h3>文档来源</h3>
            <a
              v-for="source in workspace.latestTurn.value.doc_sources"
              :key="source.index + '-' + source.source_url"
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
      </template>
    </aside>

    <AppDialog
      :open="renameDialogOpen"
      title="重命名对话"
      description="使用简洁标题，方便之后快速找到这次问题。"
      confirm-label="保存标题"
      :busy="workspace.renaming.value"
      @close="closeRenameDialog"
      @confirm="confirmRename"
    >
      <label class="field">
        <span>标题</span>
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
      title="删除对话"
      description="这会永久删除该对话的消息与执行记录。"
      confirm-label="删除对话"
      :danger="true"
      :busy="workspace.deleting.value"
      @close="closeDeleteDialog"
      @confirm="confirmDelete"
    />
  </section>
</template>
