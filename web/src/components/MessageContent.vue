<script setup lang="ts">
import { computed } from "vue";

type InlineSegment = {
  text: string;
  strong: boolean;
};

type MessageBlock =
  | { type: "paragraph"; lines: string[] }
  | { type: "list"; items: string[] }
  | { type: "code"; content: string }
  | { type: "heading"; level: number; text: string };

const props = defineProps<{
  content: string;
}>();

function inlineSegments(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  const pattern = /(\*\*[^*]+\*\*)/g;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({
        text: text.slice(cursor, index),
        strong: false,
      });
    }
    const token = match[0];
    segments.push({
      text: token.slice(2, -2),
      strong: true,
    });
    cursor = index + token.length;
  }

  if (cursor < text.length) {
    segments.push({
      text: text.slice(cursor),
      strong: false,
    });
  }

  return segments.length
    ? segments
    : [{ text, strong: false }];
}

function parseBlocks(input: string): MessageBlock[] {
  const lines = input.replace(/\r\n/g, "\n").split("\n");
  const blocks: MessageBlock[] = [];
  const fence = String.fromCharCode(96).repeat(3);
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] | null = null;

  function flushParagraph(): void {
    if (!paragraph.length) return;
    blocks.push({
      type: "paragraph",
      lines: paragraph,
    });
    paragraph = [];
  }

  function flushList(): void {
    if (!list.length) return;
    blocks.push({
      type: "list",
      items: list,
    });
    list = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.trim().startsWith(fence)) {
      flushParagraph();
      flushList();
      if (code === null) {
        code = [];
      } else {
        blocks.push({
          type: "code",
          content: code.join("\n"),
        });
        code = null;
      }
      continue;
    }

    if (code !== null) {
      code.push(rawLine);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1]?.length ?? 2,
        text: heading[2] ?? "",
      });
      continue;
    }

    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1] ?? "");
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  if (code !== null) {
    blocks.push({
      type: "code",
      content: code.join("\n"),
    });
  }
  flushParagraph();
  flushList();
  return blocks;
}

const blocks = computed(() => parseBlocks(props.content));
</script>

<template>
  <div class="message-content">
    <template
      v-for="(block, blockIndex) in blocks"
      :key="blockIndex"
    >
      <component
        :is="'h' + Math.min(4, block.level + 2)"
        v-if="block.type === 'heading'"
        class="message-content__heading"
      >
        <template
          v-for="(segment, index) in inlineSegments(block.text)"
          :key="index"
        >
          <strong v-if="segment.strong">{{ segment.text }}</strong>
          <template v-else>{{ segment.text }}</template>
        </template>
      </component>

      <ul
        v-else-if="block.type === 'list'"
        class="message-content__list"
      >
        <li
          v-for="(item, itemIndex) in block.items"
          :key="itemIndex"
        >
          <template
            v-for="(segment, index) in inlineSegments(item)"
            :key="index"
          >
            <strong v-if="segment.strong">{{ segment.text }}</strong>
            <template v-else>{{ segment.text }}</template>
          </template>
        </li>
      </ul>

      <pre
        v-else-if="block.type === 'code'"
        class="message-content__code"
      ><code>{{ block.content }}</code></pre>

      <p v-else class="message-content__paragraph">
        <template
          v-for="(line, lineIndex) in block.lines"
          :key="lineIndex"
        >
          <template
            v-for="(segment, index) in inlineSegments(line)"
            :key="index"
          >
            <strong v-if="segment.strong">{{ segment.text }}</strong>
            <template v-else>{{ segment.text }}</template>
          </template>
          <br v-if="lineIndex + 1 < block.lines.length" />
        </template>
      </p>
    </template>
  </div>
</template>
