#!/usr/bin/env node
import { Command } from "commander";
import { promises as fs } from "fs";
import {
  loadItemsFromFile,
  runPack,
  runTrace,
  runDiff,
  runBudget,
  lintFile
} from "./lib";

const program = new Command();

program
  .name("ce")
  .description("Context engineering CLI")
  .version("0.1.0");

program
  .command("pack")
  .description("Pack context items into a budget")
  .requiredOption("-i, --input <file>", "Path to items JSON/JSONL")
  .option("-b, --budget <number>", "Token budget", "4096")
  .option("-p, --provider <provider>", "openai | anthropic | heuristic", "heuristic")
  .option("--json", "Output JSON only", false)
  .action(async (options) => {
    const items = await loadItemsFromFile(options.input);
    const packResult = runPack(items, Number(options.budget), {
      provider: options.provider === "heuristic" ? undefined : options.provider
    });

    if (options.json) {
      console.log(JSON.stringify(packResult, null, 2));
      return;
    }

    console.log(`Selected ${packResult.selected.length} items`);
    console.log(`Dropped ${packResult.dropped.length} items`);
    console.log(`Total tokens: ${packResult.totalTokens}`);
    console.log("Selected IDs:");
    packResult.selected.forEach((item) => console.log(`- ${item.id}`));
  });

program
  .command("trace")
  .description("Pack with trace output")
  .requiredOption("-i, --input <file>", "Path to items JSON/JSONL")
  .option("-b, --budget <number>", "Token budget", "4096")
  .option("-p, --provider <provider>", "openai | anthropic | heuristic", "heuristic")
  .option("--json", "Output JSON only", false)
  .action(async (options) => {
    const items = await loadItemsFromFile(options.input);
    const trace = runTrace(items, Number(options.budget), {
      provider: options.provider === "heuristic" ? undefined : options.provider
    });

    if (options.json) {
      console.log(JSON.stringify(trace, null, 2));
      return;
    }

    console.log(`Pack tokens: ${trace.pack.totalTokens}`);
    console.log("Decisions:");
    trace.steps.forEach((step) =>
      console.log(`- ${step.id}: ${step.decision}`)
    );
  });

program
  .command("diff")
  .description("Diff two packs or item lists")
  .requiredOption("--before <file>", "Before JSON file")
  .requiredOption("--after <file>", "After JSON file")
  .option("--json", "Output JSON only", false)
  .action(async (options) => {
    const beforeRaw = await fs.readFile(options.before, "utf-8");
    const afterRaw = await fs.readFile(options.after, "utf-8");
    const before = JSON.parse(beforeRaw);
    const after = JSON.parse(afterRaw);
    const diffResult = runDiff(before, after);

    if (options.json) {
      console.log(JSON.stringify(diffResult, null, 2));
      return;
    }

    console.log(`Added: ${diffResult.added.length}`);
    console.log(`Removed: ${diffResult.removed.length}`);
    console.log(`Changed: ${diffResult.changed.length}`);
  });

program
  .command("lint")
  .description("Validate data against a schema")
  .requiredOption("-s, --schema <name>", "Schema name")
  .requiredOption("-i, --input <file>", "Path to JSON/JSONL")
  .action(async (options) => {
    const raw = await fs.readFile(options.input, "utf-8");
    const trimmed = raw.trim();
    const schemaName = options.schema as any;

    if (!trimmed) {
      console.error("Input file is empty");
      process.exit(1);
    }

    if (options.input.endsWith(".jsonl")) {
      const lines = trimmed.split(/\r?\n/).filter(Boolean);
      for (const [index, line] of lines.entries()) {
        const data = JSON.parse(line);
        const result = await lintFile(schemaName, data);
        if (!result.valid) {
          console.error(`Line ${index + 1} failed validation`);
          console.error(result.errors);
          process.exit(1);
        }
      }
      console.log("All lines valid");
      return;
    }

    const data = JSON.parse(trimmed);
    const result = await lintFile(schemaName, data);
    if (!result.valid) {
      console.error(result.errors);
      process.exit(1);
    }
    console.log("Valid");
  });

program
  .command("budget")
  .description("Estimate token usage for text")
  .option("-t, --text <text>", "Text to measure")
  .option("-f, --file <file>", "File to measure")
  .option("-p, --provider <provider>", "openai | anthropic | heuristic", "heuristic")
  .action(async (options) => {
    let text = options.text as string | undefined;
    if (!text && options.file) {
      text = await fs.readFile(options.file, "utf-8");
    }
    if (!text) {
      console.error("Provide --text or --file");
      process.exit(1);
    }
    const tokens = runBudget(text, {
      provider: options.provider === "heuristic" ? undefined : options.provider
    });
    console.log(tokens);
  });

program.parseAsync(process.argv);
