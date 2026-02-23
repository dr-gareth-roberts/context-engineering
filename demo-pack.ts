import { pack } from "./packages/ce-core/src/index.js";
import { openaiTokenEstimator } from "./packages/ce-providers/src/index.js";

const items = [
  {
    id: "system",
    content: "You are a helpful AI assistant specialized in engineering.",
    priority: 10,
  },
  {
    id: "project-description",
    content: "The user is working on a Context Engineering Toolkit that helps managed token budgets for LLMs.",
    priority: 8,
  },
  {
    id: "huge-log-file",
    content: "DEBUG: 10:00:01 - System started. 10:00:02 - Initializing modules. 10:00:03 - Warning: Memory high. 10:00:04 - Error: Connection lost. 10:00:05 - Retrying...",
    priority: 3,
    compressions: [
      { content: "Log summary: System started with a connection error at 10:00:04.", note: "summarized" }
    ]
  }
];

const budget = { maxTokens: 60 };

const result = pack(items, budget, {
  tokenEstimator: openaiTokenEstimator
});

console.log("=== CONTEXT PACKING RESULT ===");
console.log(`Budget: ${budget.maxTokens} tokens`);
console.log(`Used: ${result.totalTokens} tokens`);
console.log("\n--- Selected Items ---");
result.selected.forEach(item => {
  console.log(`[${item.id}] (Priority: ${item.priority})`);
  console.log(`Content: "${item.content}"`);
});

console.log("\n--- Dropped Items ---");
result.dropped.forEach(item => {
  console.log(`[${item.id}]`);
});
