import type { ContextItem, ContextPack } from "./types.js";
import type { Turn } from "./compaction.js";
import { estimateTokens } from "./estimate.js";

export interface SectionRule {
  kind: string;
  role: "system" | "user" | "assistant";
  order?: number;
  prefix?: string;
  merge?: boolean;
  mergeSeparator?: string;
  cacheBreakpoint?: boolean;
}

export interface PromptTemplateConfig {
  sections?: SectionRule[];
  fallbackRole?: "system" | "user" | "assistant";
  mergeSystemMessages?: boolean;
  provider?: "anthropic" | "openai";
}

export interface PromptMessage {
  role: "system" | "user" | "assistant";
  content: string;
  cacheControl?: { type: "ephemeral" };
  sourceItemIds?: string[];
  sourceKinds?: string[];
}

export interface PromptMessages {
  messages: PromptMessage[];
  totalTokens: number;
  includedItemIds: string[];
  stats: {
    sectionCounts: Record<string, number>;
    systemTokens: number;
    userTokens: number;
    assistantTokens: number;
  };
}

export interface AnthropicMessages {
  system:
    | string
    | Array<{
        type: "text";
        text: string;
        cache_control?: { type: "ephemeral" };
      }>;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface OpenAIMessages {
  messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
}

export const DEFAULT_SECTION_RULES: SectionRule[] = [
  { kind: "system", role: "system", order: 0, merge: true },
  { kind: "instruction", role: "system", order: 1 },
  { kind: "tool", role: "system", order: 2 },
  { kind: "schema", role: "system", order: 3 },
  { kind: "example", role: "system", order: 10, prefix: "[Example]\n" },
  { kind: "memory", role: "system", order: 20, prefix: "[Memory]\n" },
  { kind: "retrieval", role: "system", order: 30, prefix: "[Retrieved]\n" },
  { kind: "history", role: "user", order: 40 },
  { kind: "conversation", role: "user", order: 50 },
  { kind: "tool-result", role: "user", order: 90 },
  { kind: "query", role: "user", order: 100 },
];

/**
 * Convert a ContextPack or ContextItem[] into structured PromptMessages.
 */
export function toMessages(
  input: ContextPack | ContextItem[],
  config: PromptTemplateConfig = {}
): PromptMessages {
  const items: ContextItem[] = Array.isArray(input) ? input : input.selected;
  const sections = config.sections ?? DEFAULT_SECTION_RULES;
  const fallbackRole = config.fallbackRole ?? "system";

  // Build a lookup from kind → SectionRule
  const ruleMap = new Map<string, SectionRule>();
  for (const rule of sections) {
    ruleMap.set(rule.kind, rule);
  }

  // Group items by their section rule
  const groups = new Map<string, { rule: SectionRule; items: ContextItem[] }>();

  for (const item of items) {
    const kind = item.kind ?? "";
    const rule = ruleMap.get(kind);
    const groupKey = rule ? kind : "__fallback__";

    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        rule: rule ?? {
          kind: groupKey,
          role: fallbackRole,
          order: 999,
        },
        items: [],
      });
    }
    const group = groups.get(groupKey);
    if (group) group.items.push(item);
  }

  // Sort groups by order
  const sortedGroups = [...groups.values()].sort(
    (a, b) => (a.rule.order ?? 999) - (b.rule.order ?? 999)
  );

  // Build messages
  const messages: PromptMessage[] = [];
  const sectionCounts: Record<string, number> = {};
  const includedItemIds: string[] = [];

  for (const group of sortedGroups) {
    const { rule, items: groupItems } = group;
    sectionCounts[rule.kind] = groupItems.length;

    if (rule.merge) {
      // Merge all items in this section into one message
      const separator = rule.mergeSeparator ?? "\n\n";
      const contents: string[] = [];
      const ids: string[] = [];
      const kinds = new Set<string>();

      for (const item of groupItems) {
        const prefix = rule.prefix ?? "";
        contents.push(prefix + item.content);
        ids.push(item.id);
        if (item.kind) kinds.add(item.kind);
        includedItemIds.push(item.id);
      }

      const msg: PromptMessage = {
        role: resolveRole(
          groupItems[groupItems.length - 1],
          rule,
          fallbackRole
        ),
        content: contents.join(separator),
        sourceItemIds: ids,
        sourceKinds: [...kinds],
      };

      // Cache breakpoint: on the merged message if rule says so,
      // or if last item has _cacheBreakpoint metadata
      const lastItem = groupItems[groupItems.length - 1];
      if (rule.cacheBreakpoint || lastItem.metadata?._cacheBreakpoint) {
        msg.cacheControl = { type: "ephemeral" };
      }

      messages.push(msg);
    } else {
      // One message per item
      for (const item of groupItems) {
        const prefix = rule.prefix ?? "";
        const msg: PromptMessage = {
          role: resolveRole(item, rule, fallbackRole),
          content: prefix + item.content,
          sourceItemIds: [item.id],
          sourceKinds: item.kind ? [item.kind] : [],
        };

        if (rule.cacheBreakpoint || item.metadata?._cacheBreakpoint) {
          msg.cacheControl = { type: "ephemeral" };
        }

        messages.push(msg);
        includedItemIds.push(item.id);
      }
    }
  }

  // Compute token stats
  let systemTokens = 0;
  let userTokens = 0;
  let assistantTokens = 0;
  let totalTokens = 0;

  for (const msg of messages) {
    const tokens = estimateTokens(msg.content);
    totalTokens += tokens;
    switch (msg.role) {
      case "system":
        systemTokens += tokens;
        break;
      case "user":
        userTokens += tokens;
        break;
      case "assistant":
        assistantTokens += tokens;
        break;
    }
  }

  return {
    messages,
    totalTokens,
    includedItemIds,
    stats: {
      sectionCounts,
      systemTokens,
      userTokens,
      assistantTokens,
    },
  };
}

/**
 * Resolve the role for a message.
 * Priority: item.metadata.role > rule.role > fallbackRole
 */
function resolveRole(
  item: ContextItem,
  rule: SectionRule,
  fallbackRole: "system" | "user" | "assistant"
): "system" | "user" | "assistant" {
  const metadataRole = item.metadata?.role;
  if (
    metadataRole === "system" ||
    metadataRole === "user" ||
    metadataRole === "assistant"
  ) {
    return metadataRole;
  }
  return rule.role ?? fallbackRole;
}

/**
 * Format PromptMessages for the Anthropic API.
 * Extracts system messages into a separate `system` param.
 */
export function formatForAnthropic(
  prompt: PromptMessages,
  options?: { cacheBreakpoints?: boolean }
): AnthropicMessages {
  const systemMessages: PromptMessage[] = [];
  const nonSystemMessages: PromptMessage[] = [];

  for (const msg of prompt.messages) {
    if (msg.role === "system") {
      systemMessages.push(msg);
    } else {
      nonSystemMessages.push(msg);
    }
  }

  // Build system param
  let system: AnthropicMessages["system"];

  if (options?.cacheBreakpoints && systemMessages.some(m => m.cacheControl)) {
    // Use content block format for cache control
    system = systemMessages.map(msg => {
      const block: {
        type: "text";
        text: string;
        cache_control?: { type: "ephemeral" };
      } = {
        type: "text",
        text: msg.content,
      };
      if (msg.cacheControl) {
        block.cache_control = msg.cacheControl;
      }
      return block;
    });
  } else {
    system = systemMessages.map(m => m.content).join("\n\n");
  }

  const messages = nonSystemMessages.map(msg => ({
    role: msg.role as "user" | "assistant",
    content: msg.content,
  }));

  return { system, messages };
}

/**
 * Format PromptMessages for the OpenAI API.
 * System messages come first, then user/assistant in order.
 */
export function formatForOpenAI(prompt: PromptMessages): OpenAIMessages {
  const systemMessages: Array<{
    role: "system" | "user" | "assistant";
    content: string;
  }> = [];
  const otherMessages: Array<{
    role: "system" | "user" | "assistant";
    content: string;
  }> = [];

  for (const msg of prompt.messages) {
    const formatted = { role: msg.role, content: msg.content };
    if (msg.role === "system") {
      systemMessages.push(formatted);
    } else {
      otherMessages.push(formatted);
    }
  }

  return { messages: [...systemMessages, ...otherMessages] };
}

/**
 * Bridge ContextManager.compile() output into PromptMessages.
 */
export function compileToMessages(
  compiled: { turns: Turn[]; items: ContextItem[]; totalTokens: number },
  config: PromptTemplateConfig = {}
): PromptMessages {
  const messages: PromptMessage[] = [];
  const sectionCounts: Record<string, number> = {};
  const includedItemIds: string[] = [];

  // Convert turns to messages
  for (const turn of compiled.turns) {
    const role = turn.role === "tool" ? "user" : turn.role;
    const content = turn.content;

    messages.push({
      role: role as "system" | "user" | "assistant",
      content,
      sourceItemIds: [],
      sourceKinds: [],
    });

    const kind = turn.role;
    sectionCounts[kind] = (sectionCounts[kind] ?? 0) + 1;
  }

  // Convert context items using section rules
  if (compiled.items.length > 0) {
    const itemMessages = toMessages(compiled.items, config);
    messages.push(...itemMessages.messages);
    includedItemIds.push(...itemMessages.includedItemIds);
    for (const [kind, count] of Object.entries(
      itemMessages.stats.sectionCounts
    )) {
      sectionCounts[kind] = (sectionCounts[kind] ?? 0) + count;
    }
  }

  // Compute token stats
  let systemTokens = 0;
  let userTokens = 0;
  let assistantTokens = 0;
  let totalTokens = 0;

  for (const msg of messages) {
    const tokens = estimateTokens(msg.content);
    totalTokens += tokens;
    switch (msg.role) {
      case "system":
        systemTokens += tokens;
        break;
      case "user":
        userTokens += tokens;
        break;
      case "assistant":
        assistantTokens += tokens;
        break;
    }
  }

  return {
    messages,
    totalTokens,
    includedItemIds,
    stats: {
      sectionCounts,
      systemTokens,
      userTokens,
      assistantTokens,
    },
  };
}
