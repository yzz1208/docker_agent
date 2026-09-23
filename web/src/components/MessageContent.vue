<script setup lang="ts">
import { computed } from "vue";

type InlineSegment = {
  kind: "text" | "strong" | "code";
  text: string;
};

type ContentBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "code"; text: string };

const props = defineProps<{
  content: string;
}>();

const blocks = computed(() => parseContent(props.content));

function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  const pattern = /(\*\*[^*]+\*\*|\x60[^\x60]+\x60)/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({
        kind: "text",
        text: text.slice(cursor, index),
      });
    }

    const token = match[0];
    if (token.startsWith("**")) {
      segments.push({
        kind: "strong",
        text: token.slice(2, -2),
      });
    } else {
      segments.push({
        kind: "code",
        text: token.slice(1, -1),
      });
    }
    cursor = index + token.length;
  }

  if (cursor < text.length) {
    segments.push({
      kind: "text",
      text: text.slice(cursor),
    });
  }

  return segments.length
    ? segments
    : [{ kind: "text", text }];
}

function parseContent(content: string): ContentBlock[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const result: ContentBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    const text = paragraph.join("\n").trim();
    if (text) {
      result.push({ kind: "paragraph", text });
    }
    paragraph = [];
  };

  const flushList = () => {
    if (listItems.length) {
      result.push({ kind: "list", items: listItems });
    }
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.trim().startsWith("\x60\x60\x60")) {
      flushParagraph();
      flushList();
      if (inCode) {
        result.push({
          kind: "code",
          text: codeLines.join("\n"),
        });
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }

    if (inCode) {
      codeLines.push(rawLine);
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line.trim());
    if (heading) {
      flushParagraph();
      flushList();
      result.push({
        kind: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      continue;
    }

    const listItem = /^[-*]\s+(.+)$/.exec(line.trim());
    if (listItem) {
      flushParagraph();
      listItems.push(listItem[1]);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  if (codeLines.length) {
    result.push({ kind: "code", text: codeLines.join("\n") });
  }
  return result;
}
</script>

<template>
  <div class="message-content">
    <template v-for="(block, blockIndex) in blocks" :key="blockIndex">
      <h3
        v-if="block.kind === 'heading'"
        :class="'message-content__heading message-content__heading--' + block.level"
      >
        <template
          v-for="(segment, index) in parseInline(block.text)"
          :key="index"
        >
          <strong v-if="segment.kind === 'strong'">{{ segment.text }}</strong>
          <code v-else-if="segment.kind === 'code'">{{ segment.text }}</code>
          <span v-else>{{ segment.text }}</span>
        </template>
      </h3>

      <p v-else-if="block.kind === 'paragraph'">
        <template
          v-for="(segment, index) in parseInline(block.text)"
          :key="index"
        >
          <strong v-if="segment.kind === 'strong'">{{ segment.text }}</strong>
          <code v-else-if="segment.kind === 'code'">{{ segment.text }}</code>
          <span v-else>{{ segment.text }}</span>
        </template>
      </p>

      <ul v-else-if="block.kind === 'list'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <template
            v-for="(segment, index) in parseInline(item)"
            :key="index"
          >
            <strong v-if="segment.kind === 'strong'">{{ segment.text }}</strong>
            <code v-else-if="segment.kind === 'code'">{{ segment.text }}</code>
            <span v-else>{{ segment.text }}</span>
          </template>
        </li>
      </ul>

      <pre v-else><code>{{ block.text }}</code></pre>
    </template>
  </div>
</template>
