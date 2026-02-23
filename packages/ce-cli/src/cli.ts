#!/usr/bin/env node
import { Command } from "commander";
import { promises as fs } from "fs";
import {
  loadItemsFromFile,
  runPack,
  runTrace,
  runDiff,
  runBudget,
  lintFile,
} from "./lib";
import {
  fmt,
  outputResult,
  outputError,
  readStdin,
  setForceJson,
  setNoColor,
  isJsonMode,
} from "./output";

const program = new Command();

program
  .name("ce")
  .description(
    "Context engineering CLI — pack, trace, diff, lint, and estimate tokens"
  )
  .version("0.1.0")
  .option("--no-color", "Disable colored output")
  .hook("preAction", thisCommand => {
    const opts = thisCommand.opts();
    if (opts.color === false) setNoColor(true);
  });

async function loadItems(input: string) {
  try {
    if (input === "-") {
      const raw = await readStdin();
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : (parsed.items ?? []);
    }
    return await loadItemsFromFile(input);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("ENOENT")) {
      outputError(
        `File not found: ${input}`,
        "Check the file path and try again"
      );
    }
    outputError(`Failed to load items: ${msg}`);
  }
}

program
  .command("pack")
  .description("Pack context items into a token budget")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", "4096")
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    "heuristic"
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const result = runPack(items, Number(options.budget), {
        provider:
          options.provider === "heuristic" ? undefined : options.provider,
      });
      outputResult(result, () => {
        console.log(
          fmt.bold(`Selected ${result.selected.length} items`) +
            fmt.dim(` (dropped ${result.dropped.length})`)
        );
        console.log(`Total tokens: ${fmt.cyan(String(result.totalTokens))}`);
        if (result.selected.length > 0) {
          console.log(fmt.dim("\nSelected:"));
          result.selected.forEach(item =>
            console.log(
              `  ${fmt.green("•")} ${item.id} ${fmt.dim(`(${item.tokens ?? "?"} tokens)`)}`
            )
          );
        }
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("trace")
  .description("Pack with step-by-step decision trace")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", "4096")
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    "heuristic"
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const trace = runTrace(items, Number(options.budget), {
        provider:
          options.provider === "heuristic" ? undefined : options.provider,
      });
      outputResult(trace, () => {
        console.log(fmt.bold(`Pack tokens: ${trace.pack.totalTokens}`));
        console.log(fmt.dim("\nDecisions:"));
        trace.steps.forEach(step => {
          const icon =
            step.decision === "include"
              ? fmt.green("✓")
              : step.decision === "compress"
                ? fmt.yellow("~")
                : fmt.red("✗");
          console.log(
            `  ${icon} ${step.id}: ${step.decision} ${fmt.dim(`(${step.reason ?? ""})`)}`
          );
        });
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("diff")
  .description("Compare two context packs or item lists")
  .requiredOption("--before <file>", "Before JSON file")
  .requiredOption("--after <file>", "After JSON file")
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const beforeRaw = await fs.readFile(options.before, "utf-8");
      const afterRaw = await fs.readFile(options.after, "utf-8");
      const before = JSON.parse(beforeRaw);
      const after = JSON.parse(afterRaw);
      const result = runDiff(before, after);
      outputResult(result, () => {
        console.log(fmt.green(`+ Added: ${result.added.length}`));
        console.log(fmt.red(`- Removed: ${result.removed.length}`));
        console.log(fmt.yellow(`~ Changed: ${result.changed.length}`));
        console.log(fmt.dim(`= Kept: ${result.kept.length}`));
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("ENOENT")) {
        outputError("File not found", "Check --before and --after paths");
      }
      outputError(msg);
    }
  });

program
  .command("lint")
  .description("Validate data against a JSON schema")
  .requiredOption(
    "-s, --schema <name>",
    "Schema: context-item | context-pack | context-plan | context-trace | memory-item"
  )
  .requiredOption("-i, --input <file>", "Path to JSON/JSONL")
  .action(async options => {
    try {
      const raw = await fs.readFile(options.input, "utf-8");
      const trimmed = raw.trim();

      if (!trimmed) {
        outputError("Input file is empty");
      }

      if (options.input.endsWith(".jsonl")) {
        const lines = trimmed.split(/\r?\n/).filter(Boolean);
        for (const [index, line] of lines.entries()) {
          const data = JSON.parse(line);
          const result = await lintFile(options.schema, data);
          if (!result.valid) {
            outputError(
              `Line ${index + 1} failed validation`,
              JSON.stringify(result.errors, null, 2)
            );
          }
        }
        if (isJsonMode()) {
          console.log(JSON.stringify({ valid: true, lines: lines.length }));
        } else {
          console.log(fmt.success(`All ${lines.length} lines valid`));
        }
        return;
      }

      const data = JSON.parse(trimmed);
      const result = await lintFile(options.schema, data);
      if (!result.valid) {
        outputError(
          "Validation failed",
          JSON.stringify(result.errors, null, 2)
        );
      }
      if (isJsonMode()) {
        console.log(JSON.stringify({ valid: true }));
      } else {
        console.log(fmt.success("Valid"));
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes("ENOENT")) {
        outputError(`File not found: ${options.input}`);
      }
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("budget")
  .description("Estimate token count for text or a file")
  .option("-t, --text <text>", "Text to measure")
  .option("-f, --file <file>", "File to measure")
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    "heuristic"
  )
  .action(async options => {
    try {
      let text = options.text as string | undefined;
      if (!text && options.file) {
        text = await fs.readFile(options.file, "utf-8");
      }
      if (!text) {
        outputError("Provide --text or --file");
      }
      const tokens = runBudget(text, {
        provider:
          options.provider === "heuristic" ? undefined : options.provider,
      });
      if (isJsonMode()) {
        console.log(JSON.stringify({ tokens, provider: options.provider }));
      } else {
        console.log(
          `${fmt.cyan(String(tokens))} tokens ${fmt.dim(`(${options.provider})`)}`
        );
      }
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program.parseAsync(process.argv);
