import { InMemoryStore } from "./packages/ce-memory/src/index.js";

async function run() {
  const store = new InMemoryStore();

  console.log("=== MEMORY STORE DEMO ===");

  // 1. Store a memory that expires quickly
  await store.put({
    id: "session-context",
    content: "User is asking about TypeScript.",
    ttlSeconds: 2,
  });

  // 2. Store a high-importance memory
  await store.put({
    id: "user-name",
    content: "User name is Alice.",
    salience: 10,
  });

  console.log("Initial query:");
  let items = await store.query();
  items.forEach(m =>
    console.log(`- [${m.id}] ${m.content} (Salience: ${m.salience})`)
  );

  console.log("\nWaiting 3 seconds for TTL to expire...");
  await new Promise(resolve => setTimeout(resolve, 3000));

  console.log("Query after expiry:");
  items = await store.query();
  items.forEach(m => console.log(`- [${m.id}] ${m.content}`));

  if (items.length === 1) {
    console.log(
      "\nSuccess: 'session-context' expired and was removed automatically."
    );
  }
}

run().catch(console.error);
