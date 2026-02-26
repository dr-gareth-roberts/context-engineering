#!/usr/bin/env node
import { Command } from "commander";
import { promises as fs } from "fs";
import type { ContextItem } from "@ce/core";
import {
  loadItemsFromFile,
  runPack,
  runTrace,
  runDiff,
  runBudget,
  lintFile,
  runPlace,
  runQuality,
  runEffectiveBudget,
  runHandoff,
  runPickup,
  runCost,
} from "./lib.js";
import {
  fmt,
  outputResult,
  outputError,
  readStdin,
  setForceJson,
  setNoColor,
  isJsonMode,
} from "./output.js";

const program = new Command();

program
  .name("ce")
  .description(
    "Context engineering CLI — pack, trace, diff, place, quality, handoff, pickup, cost, lint, and budget"
  )
  .version("0.1.0")
  .option("--no-color", "Disable colored output")
  .hook("preAction", thisCommand => {
    const opts = thisCommand.opts();
    if (opts.color === false) setNoColor(true);
  });

function parsePositiveInt(value: string, name: string): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0 || Math.floor(n) !== n) {
    return outputError(`${name} must be a positive integer, got: ${value}`);
  }
  return n;
}

async function loadItems(input: string): Promise<ContextItem[]> {
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
      return outputError(
        `File not found: ${input}`,
        "Check the file path and try again"
      );
    }
    return outputError(`Failed to load items: ${msg}`);
  }
}

// Environment variable defaults for CI/CD ergonomics
const ENV_BUDGET = process.env.CE_BUDGET ?? "4096";
const ENV_PROVIDER = process.env.CE_PROVIDER ?? "heuristic";

program
  .command("pack")
  .description("Pack context items into a token budget")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const result = runPack(
        items,
        parsePositiveInt(options.budget, "budget"),
        {
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
        }
      );
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
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const trace = runTrace(
        items,
        parsePositiveInt(options.budget, "budget"),
        {
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
        }
      );
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
    "Schema: context-item | context-pack | context-plan | context-trace | memory-item | cache-aware-pack | cost-estimate | beads-issue | pipeline-result"
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
    ENV_PROVIDER
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

program
  .command("place")
  .description("Pack and reorder items for optimal attention placement")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option(
    "-s, --strategy <strategy>",
    "Placement strategy: score-order | attention-optimized",
    "attention-optimized"
  )
  .option(
    "-m, --model <model>",
    "Model family: claude | gpt4 | default",
    "default"
  )
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const result = runPlace(
        items,
        parsePositiveInt(options.budget, "budget"),
        {
          strategy: options.strategy,
          model: options.model,
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
        }
      );
      outputResult(result, () => {
        console.log(
          fmt.bold(`Placed ${result.selected.length} items`) +
            fmt.dim(` (${result.strategy})`)
        );
        console.log(`Total tokens: ${fmt.cyan(String(result.totalTokens))}`);
        result.selected.forEach((item, i) =>
          console.log(
            `  ${fmt.dim(`${i + 1}.`)} ${item.id} ${fmt.dim(`(${item.tokens ?? "?"} tokens)`)}`
          )
        );
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("quality")
  .description(
    "Analyze context quality metrics (density, diversity, redundancy)"
  )
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const quality = runQuality(
        items,
        parsePositiveInt(options.budget, "budget"),
        {
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
        }
      );
      outputResult(quality, () => {
        console.log(fmt.bold("Context Quality Analysis"));
        console.log(`  Items:      ${fmt.cyan(String(quality.itemCount))}`);
        console.log(`  Tokens:     ${fmt.cyan(String(quality.totalTokens))}`);
        console.log(`  Density:    ${colorMetric(quality.density)}`);
        console.log(`  Diversity:  ${colorMetric(quality.diversity)}`);
        console.log(`  Freshness:  ${colorMetric(quality.freshness)}`);
        console.log(
          `  Redundancy: ${colorMetric(1 - quality.redundancy)} ${fmt.dim(`(${quality.redundancy} raw)`)}`
        );
        console.log(
          `  ${fmt.bold("Overall:")}    ${colorMetric(quality.overall)}`
        );
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("effective-budget")
  .description(
    "Calculate effective token budget for a model (accounts for context degradation)"
  )
  .requiredOption("-t, --tokens <number>", "Advertised context window size")
  .option(
    "-m, --model <model>",
    "Model family: claude | gpt4 | default",
    "default"
  )
  .option("--json", "Force JSON output")
  .action(options => {
    if (options.json) setForceJson(true);
    const result = runEffectiveBudget(
      parsePositiveInt(options.tokens, "tokens"),
      options.model
    );
    outputResult(result, () => {
      console.log(
        `${fmt.bold("Advertised:")} ${fmt.cyan(String(result.advertised))} tokens`
      );
      console.log(
        `${fmt.bold("Effective:")}  ${fmt.green(String(result.effective))} tokens ${fmt.dim(`(${Math.round(result.ratio * 100)}%)`)}`
      );
      console.log(fmt.dim(`Model: ${result.model}`));
    });
  });

program
  .command("handoff")
  .description("Create BEADS JSONL handoff from context items")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option("-o, --output <file>", "Output file (default: stdout)")
  .option("--cache-topology", "Use cache-topology-aware packing")
  .option("--include-dropped", "Include dropped items as deferred issues")
  .option("--agent <name>", "Agent identity for handoff")
  .option("--session-id <id>", "Session identifier")
  .option("--notes <text>", "Handoff notes")
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output (outputs stats, not JSONL)")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const result = runHandoff(
        items,
        parsePositiveInt(options.budget, "budget"),
        {
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
          cacheTopology: options.cacheTopology,
          includeDropped: options.includeDropped,
          agent: options.agent,
          sessionId: options.sessionId,
          notes: options.notes,
        }
      );

      if (options.output) {
        await fs.writeFile(options.output, result.jsonl + "\n");
      }

      if (isJsonMode()) {
        console.log(
          JSON.stringify(
            options.output
              ? result.stats
              : { jsonl: result.jsonl, stats: result.stats },
            null,
            2
          )
        );
      } else if (options.output) {
        console.log(
          fmt.success(
            `Wrote ${result.stats.totalIssues} issues to ${options.output}`
          )
        );
        console.log(
          `  Active:   ${fmt.green(String(result.stats.activeItems))}`
        );
        console.log(
          `  Deferred: ${fmt.dim(String(result.stats.deferredItems))}`
        );
      } else {
        // Write JSONL to stdout
        console.log(result.jsonl);
      }
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("pickup")
  .description("Pick up context from a BEADS JSONL handoff")
  .requiredOption(
    "-i, --input <file>",
    "Path to BEADS JSONL file (use - for stdin)"
  )
  .option(
    "--ready",
    "Only include ready items (open, non-blocked, non-deferred)"
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      let jsonl: string;
      if (options.input === "-") {
        jsonl = await readStdin();
      } else {
        jsonl = await fs.readFile(options.input, "utf-8");
      }
      const result = runPickup(jsonl, { ready: options.ready });
      outputResult(result, () => {
        console.log(fmt.bold("Pickup Summary"));
        console.log(
          `  Context items: ${fmt.green(String(result.stats.contextItems))}`
        );
        console.log(
          `  Deferred:      ${fmt.dim(String(result.stats.deferredItems))}`
        );
        console.log(
          `  Work items:    ${fmt.cyan(String(result.stats.workItems))}`
        );
        if (result.stats.handoffSessionId) {
          console.log(
            `  Session:       ${fmt.dim(result.stats.handoffSessionId)}`
          );
        }
        if (result.items.length > 0) {
          console.log(fmt.dim("\nRecovered items:"));
          result.items.forEach(item =>
            console.log(
              `  ${fmt.green("•")} ${item.id} ${fmt.dim(`[${item.kind ?? "unknown"}] (${item.tokens ?? "?"} tokens)`)}`
            )
          );
        }
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

program
  .command("cost")
  .description("Estimate API costs with prefix cache savings")
  .requiredOption(
    "-i, --input <file>",
    "Path to items JSON/JSONL (use - for stdin)"
  )
  .requiredOption(
    "-m, --model <model>",
    "Model: claude-opus-4-6 | claude-sonnet-4-6 | claude-haiku-4-5 | gpt-4.1 | gpt-4o | o3 | o4-mini"
  )
  .option("-b, --budget <number>", "Token budget", ENV_BUDGET)
  .option("--output-tokens <number>", "Estimated output tokens", "500")
  .option("--requests <number>", "Number of requests to project")
  .option(
    "--requests-per-day <number>",
    "Requests per day (for monthly estimate)"
  )
  .option(
    "-p, --provider <provider>",
    "Token estimator: openai | anthropic | heuristic",
    ENV_PROVIDER
  )
  .option("--json", "Force JSON output")
  .action(async options => {
    if (options.json) setForceJson(true);
    try {
      const items = await loadItems(options.input);
      const { estimate, projection } = runCost(
        items,
        parsePositiveInt(options.budget, "budget"),
        options.model,
        {
          provider:
            options.provider === "heuristic" ? undefined : options.provider,
          outputTokens: parsePositiveInt(options.outputTokens, "output-tokens"),
          requestCount: options.requests
            ? parsePositiveInt(options.requests, "requests")
            : undefined,
          requestsPerDay: options.requestsPerDay
            ? parsePositiveInt(options.requestsPerDay, "requests-per-day")
            : undefined,
        }
      );

      outputResult(projection ?? estimate, () => {
        console.log(fmt.bold(`Cost Estimate — ${estimate.model}`));
        console.log(
          `  Input tokens:  ${fmt.cyan(String(estimate.inputTokens))}`
        );
        console.log(
          `  Cached:        ${fmt.green(String(estimate.cachedTokens))} ${fmt.dim(`(${Math.round(estimate.cacheEfficiency * 100)}% cache hit)`)}`
        );
        console.log(
          `  Uncached:      ${fmt.dim(String(estimate.uncachedTokens))}`
        );
        console.log(
          `  Output tokens: ${fmt.dim(String(estimate.outputTokens))}`
        );
        console.log();
        console.log(
          `  Without cache: ${fmt.dim("$" + estimate.costWithoutCache.toFixed(6))}`
        );
        console.log(
          `  With cache:    ${fmt.green("$" + estimate.costWithCache.toFixed(6))}`
        );
        console.log(
          `  ${fmt.bold("Savings:")}      ${fmt.green("$" + estimate.savings.toFixed(6))} ${fmt.dim(`(${estimate.savingsPercent}%)`)}`
        );

        if (projection) {
          console.log();
          console.log(
            fmt.bold(`Projection — ${projection.requestCount} requests`)
          );
          console.log(
            `  Without cache: $${projection.totalWithoutCache.toFixed(2)}`
          );
          console.log(
            `  With cache:    ${fmt.green("$" + projection.totalWithCache.toFixed(2))}`
          );
          console.log(
            `  ${fmt.bold("Total savings:")} ${fmt.green("$" + projection.totalSavings.toFixed(2))}`
          );

          if (projection.monthlyEstimate) {
            const m = projection.monthlyEstimate;
            console.log();
            console.log(fmt.bold(`Monthly — ${m.requestsPerDay} req/day`));
            console.log(
              `  Without cache: $${m.monthlyCostWithoutCache.toFixed(2)}/mo`
            );
            console.log(
              `  With cache:    ${fmt.green("$" + m.monthlyCostWithCache.toFixed(2) + "/mo")}`
            );
            console.log(
              `  ${fmt.bold("Monthly savings:")} ${fmt.green("$" + m.monthlySavings.toFixed(2) + "/mo")}`
            );
          }
        }
      });
    } catch (err) {
      outputError(err instanceof Error ? err.message : String(err));
    }
  });

/** Color a 0-1 metric value: green if good, yellow if mid, red if bad */
function colorMetric(value: number): string {
  const text = value.toFixed(3);
  if (value >= 0.7) return fmt.green(text);
  if (value >= 0.4) return fmt.yellow(text);
  return fmt.red(text);
}

program.parseAsync(process.argv).catch(err => {
  const msg = err instanceof Error ? err.message : String(err);
  outputError(msg);
});
