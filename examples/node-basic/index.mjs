import { pack } from "@ce/core";
import { InMemoryStore } from "@ce/memory";
import { OpenAIProvider } from "@ce/providers";

const items = [
  {
    id: "system",
    content: "You are a helpful assistant.",
    priority: 10,
    tokens: 12,
  },
  {
    id: "policy",
    content: "Always cite sources when available.",
    priority: 6,
    tokens: 10,
  },
  {
    id: "notes",
    content: "User prefers concise answers.",
    priority: 4,
    tokens: 8,
  },
];

const packResult = pack(items, { maxTokens: 24 });
console.log("Pack result", packResult);

const memory = new InMemoryStore();
await memory.put({
  id: "m1",
  content: "Project uses PNPM",
  createdAt: new Date().toISOString(),
});
console.log("Memory query", await memory.query());

try {
  const provider = new OpenAIProvider();
  console.log("Provider ready", provider ? "yes" : "no");
} catch {
  console.log(
    "Skipping LLM generation (set OPENAI_API_KEY to enable)"
  );
}
