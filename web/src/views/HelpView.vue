<script setup lang="ts">
const quickStarts = [
  {
    title: "概念与文档问答",
    description: "适合学习 Docker、Compose、网络、存储、镜像等概念。",
    example: "Docker volume 和 bind mount 有什么区别？",
  },
  {
    title: "容器运行时排查",
    description: "适合检查容器状态、日志、资源使用和重启原因。",
    example: "web-1 容器为什么反复重启？",
  },
  {
    title: "服务级故障分诊",
    description: "当容器本身正常但服务仍异常时，智能编排可以转交基础设施排障专家。",
    example: "容器正常，但 checkout-api 持续返回 503，继续排查服务级问题。",
  },
];

const workflow = [
  "理解你的问题与当前对话上下文",
  "选择 Docker 支持或基础设施排障专家",
  "按需检索 Docker 文档或执行只读运行时检查",
  "跨专家转交前请求你的批准",
  "综合公开结果，并明确区分事实、推测和待确认项",
];
</script>

<template>
  <section class="help-page">
    <header class="help-hero panel">
      <div>
        <p class="section-label">产品介绍与使用指南</p>
        <h2>Docker 智能支持平台</h2>
        <p>
          这是一个面向 Docker 与服务故障排查的多 Agent 支持系统。
          你可以直接描述问题，让系统自动选择专家，也可以手动固定某个专家进行连续对话。
        </p>
      </div>
      <RouterLink class="button button--primary" to="/">
        开始对话
      </RouterLink>
    </header>

    <section class="help-grid">
      <article class="panel help-card help-card--accent">
        <span class="help-card__number">01</span>
        <h3>推荐使用：智能编排</h3>
        <p>
          不需要先判断问题属于哪个模块。直接描述现象，系统会先做短路由判断，
          再选择最合适的专家。只有跨专家转交时才会出现人工审批。
        </p>
      </article>

      <article class="panel help-card">
        <span class="help-card__number">02</span>
        <h3>手动专家模式</h3>
        <p>
          当你已经明确需要 Docker 文档问答或固定专家诊断时，可以使用手动模式，
          对话会一直保留在当前专家中。
        </p>
      </article>

      <article class="panel help-card">
        <span class="help-card__number">03</span>
        <h3>安全边界</h3>
        <p>
          默认运行时工具为只读能力。跨 Agent 转交使用持久化审批，
          刷新页面后仍可以恢复，不会因为页面关闭而重复执行前面的步骤。
        </p>
      </article>
    </section>

    <section class="panel help-section">
      <div class="panel__header">
        <div>
          <p class="section-label">快速开始</p>
          <h2>你可以这样提问</h2>
        </div>
      </div>

      <div class="help-example-grid">
        <article v-for="item in quickStarts" :key="item.title">
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
          <code>{{ item.example }}</code>
        </article>
      </div>
    </section>

    <section class="panel help-section">
      <div class="panel__header">
        <div>
          <p class="section-label">智能编排流程</p>
          <h2>系统在一次请求里做什么</h2>
        </div>
      </div>

      <ol class="help-workflow">
        <li v-for="(item, index) in workflow" :key="item">
          <span>{{ String(index + 1).padStart(2, "0") }}</span>
          <p>{{ item }}</p>
        </li>
      </ol>
    </section>

    <section class="help-two-column">
      <article class="panel help-section">
        <div class="panel__header">
          <div>
            <p class="section-label">页面说明</p>
            <h2>主要功能</h2>
          </div>
        </div>
        <dl class="help-facts">
          <div>
            <dt>聊天</dt>
            <dd>进行智能编排或手动专家对话，查看执行过程和证据来源。</dd>
          </div>
          <div>
            <dt>运行观测</dt>
            <dd>查看执行次数、成功率、延迟、路由分布、运行详情与评测结果。</dd>
          </div>
          <div>
            <dt>设置</dt>
            <dd>调整 Agent 的模型、检索和运行时偏好，并查看当前生效来源。</dd>
          </div>
        </dl>
      </article>

      <article class="panel help-section">
        <div class="panel__header">
          <div>
            <p class="section-label">使用建议</p>
            <h2>怎样获得更好的结果</h2>
          </div>
        </div>
        <ul class="help-tips">
          <li>描述“现象 + 对象 + 你已经知道的信息”，比只说“有问题”更有效。</li>
          <li>运行时问题尽量提供容器名，例如 <code>web-1</code>。</li>
          <li>服务故障最好说明错误码、影响范围和是否持续发生。</li>
          <li>回答完成后可以直接继续追问，系统会保留当前对话上下文。</li>
          <li>首次文档问答需要加载本地 Embedding/Reranker 模型，后续请求会复用模型并明显更快。</li>
        </ul>
      </article>
    </section>
  </section>
</template>
