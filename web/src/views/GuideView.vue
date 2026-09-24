<script setup lang="ts">
const steps = [
  {
    index: "01",
    title: "选择对话模式",
    body: "推荐优先使用“智能编排”。系统会先判断问题类型，再选择 Docker 支持或基础设施排障专家。需要固定专家时再使用“手动专家”。",
  },
  {
    index: "02",
    title: "直接描述现象",
    body: "尽量写清容器/服务名称、报错、发生时间、已经尝试过的操作。信息越完整，系统越少追问。",
  },
  {
    index: "03",
    title: "查看处理过程",
    body: "右侧会显示智能判断、专家处理、专家转交和综合结论。跨专家转交时会先暂停并请求你的批准。",
  },
  {
    index: "04",
    title: "继续同一对话",
    body: "执行完成后可以直接继续追问。系统会保留最近上下文和上一位专家的公开结果，不需要重复描述全部背景。",
  },
];

const modes = [
  {
    title: "智能编排",
    badge: "推荐",
    body: "适合不知道该找哪个专家、问题可能跨容器与服务层、需要多专家协作的场景。",
    examples: [
      "容器正常，但是 checkout-api 一直返回 503，继续帮我排查。",
      "Docker daemon 连不上，帮我判断应该先查配置还是运行时。",
    ],
  },
  {
    title: "手动专家",
    badge: "精确控制",
    body: "适合你已经知道问题属于哪一类，希望直接进入固定专家能力的场景。",
    examples: [
      "向 Docker 支持询问镜像构建和容器运行问题。",
      "向基础设施排障专家检查服务级故障和依赖异常。",
    ],
  },
];

const concepts = [
  {
    title: "人工审批",
    body: "当智能编排准备把问题交给另一位专家时，系统会先暂停。你可以查看目标专家、能力和转交原因，再决定是否继续。",
  },
  {
    title: "运行观测",
    body: "用于查看最近执行、成功率、耗时、路由和评测记录。它更像开发/运维面板，不是普通聊天必须使用的功能。",
  },
  {
    title: "设置",
    body: "用于调整各专家的可编辑配置。没有显式覆盖的字段会继续继承环境变量或应用默认值。",
  },
];
</script>

<template>
  <section class="guide-page">
    <header class="guide-hero panel">
      <div class="guide-hero__copy">
        <p class="section-label">快速上手</p>
        <h2>Docker 智能支持平台使用指南</h2>
        <p>
          这是一个面向 Docker 与服务故障排查的多专家 Agent 平台。你可以像普通聊天一样描述问题，
          系统会根据需要检索文档、执行只读诊断、转交专家，并把处理过程展示出来。
        </p>
      </div>
      <div class="guide-hero__stats">
        <div><strong>2</strong><span>专业 Agent</span></div>
        <div><strong>自动</strong><span>问题路由</span></div>
        <div><strong>可恢复</strong><span>审批工作流</span></div>
      </div>
    </header>

    <section class="guide-section panel">
      <div class="guide-section__heading">
        <p class="section-label">开始使用</p>
        <h2>四步完成一次排障</h2>
      </div>
      <div class="guide-step-grid">
        <article v-for="step in steps" :key="step.index" class="guide-step">
          <span>{{ step.index }}</span>
          <div>
            <h3>{{ step.title }}</h3>
            <p>{{ step.body }}</p>
          </div>
        </article>
      </div>
    </section>

    <section class="guide-mode-grid">
      <article v-for="mode in modes" :key="mode.title" class="guide-mode-card panel">
        <div class="guide-mode-card__head">
          <div>
            <p class="section-label">对话模式</p>
            <h2>{{ mode.title }}</h2>
          </div>
          <span class="chip">{{ mode.badge }}</span>
        </div>
        <p>{{ mode.body }}</p>
        <div class="guide-example-list">
          <strong>可以这样问</strong>
          <div v-for="example in mode.examples" :key="example">{{ example }}</div>
        </div>
      </article>
    </section>

    <section class="guide-section panel">
      <div class="guide-section__heading">
        <p class="section-label">界面说明</p>
        <h2>你会看到这些功能</h2>
      </div>
      <div class="guide-concept-grid">
        <article v-for="item in concepts" :key="item.title">
          <h3>{{ item.title }}</h3>
          <p>{{ item.body }}</p>
        </article>
      </div>
    </section>

    <section class="guide-tip panel">
      <div>
        <p class="section-label">建议</p>
        <h2>怎样让回答更快、更准确？</h2>
      </div>
      <p>
        优先给出对象名称、错误信息和你已经确认的事实；不要一次塞入大量无关背景。
        如果系统提出补充问题，直接回答它即可。跨专家问题建议留在同一个“智能编排”对话中继续。
      </p>
    </section>
  </section>
</template>
