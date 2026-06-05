/**
 * End-to-end tests for the `ce` CLI binary.
 *
 * These tests invoke the compiled CLI as a subprocess to verify
 * command parsing, output formatting, error handling, and exit codes.
 */
import { describe, expect, it } from "vitest";
import { execFile } from "child_process";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

const CLI = path.resolve(import.meta.dirname, "..", "dist", "cli.js");
const FIXTURES = path.resolve(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "fixtures"
);
const ITEMS_FILE = path.join(FIXTURES, "context-items.json");

function run(
  args: string[],
  options: { input?: string; env?: Record<string, string> } = {}
): Promise<{ stdout: string; stderr: string; code: number | null }> {
  // Strip FORCE_COLOR from the child env: combined with NO_COLOR it makes
  // commander emit a "NO_COLOR is ignored…" warning to stderr, which would
  // corrupt the JSON-on-stderr that these tests parse. (FORCE_COLOR is set in
  // some terminals/CI-adjacent shells but never in the GitHub CI job.)
  const { FORCE_COLOR: _ignoredForceColor, ...baseEnv } = process.env;
  return new Promise(resolve => {
    const child = execFile(
      process.execPath,
      [CLI, ...args],
      {
        env: { ...baseEnv, NO_COLOR: "1", ...options.env },
        cwd: path.resolve(FIXTURES, ".."),
        maxBuffer: 10 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        resolve({
          stdout: stdout?.toString() ?? "",
          stderr: stderr?.toString() ?? "",
          code: error ? ((error as any).code ?? 1) : 0,
        });
      }
    );
    if (options.input && child.stdin) {
      child.stdin.write(options.input);
      child.stdin.end();
    }
  });
}

// ─── Pack ──────────────────────────────────────────────────────────────

describe("ce pack", () => {
  it("packs items from a file", async () => {
    const { stdout, code } = await run([
      "pack",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.selected).toBeDefined();
    expect(data.totalTokens).toBeGreaterThan(0);
  });

  it("packs items from stdin", async () => {
    const items = JSON.stringify([
      { id: "a", content: "hello", tokens: 10 },
      { id: "b", content: "world", tokens: 20 },
    ]);
    const { stdout, code } = await run(
      ["pack", "-i", "-", "-b", "50", "--json"],
      { input: items }
    );
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.selected.length).toBeGreaterThan(0);
  });

  it("packs context-pack JSON from stdin", async () => {
    const packInput = JSON.stringify({
      selected: [{ id: "a", content: "hello", tokens: 10 }],
      dropped: [{ id: "b", content: "world", tokens: 20 }],
    });
    const { stdout, code } = await run(
      ["pack", "-i", "-", "-b", "50", "--json"],
      { input: packInput }
    );
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    const itemIds = [
      ...data.selected.map((item: { id: string }) => item.id),
      ...data.dropped.map((item: { id: string }) => item.id),
    ];
    expect(itemIds).toContain("a");
    expect(itemIds).toContain("b");
  });

  it("fails with missing input file", async () => {
    const { code } = await run([
      "pack",
      "-i",
      "/nonexistent.json",
      "-b",
      "100",
    ]);
    expect(code).not.toBe(0);
  });
});

// ─── Trace ─────────────────────────────────────────────────────────────

describe("ce trace", () => {
  it("traces packing decisions", async () => {
    const { stdout, code } = await run([
      "trace",
      "-i",
      ITEMS_FILE,
      "-b",
      "50",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.steps).toBeDefined();
    expect(Array.isArray(data.steps)).toBe(true);
  });
});

// ─── Diff ──────────────────────────────────────────────────────────────

describe("ce diff", () => {
  it("diffs two item files", async () => {
    const tmpBefore = path.join(os.tmpdir(), "ce-test-before.json");
    const tmpAfter = path.join(os.tmpdir(), "ce-test-after.json");
    await fs.writeFile(
      tmpBefore,
      JSON.stringify([{ id: "a", content: "old", tokens: 10 }])
    );
    await fs.writeFile(
      tmpAfter,
      JSON.stringify([{ id: "b", content: "new", tokens: 10 }])
    );

    try {
      const { stdout, code } = await run([
        "diff",
        "--before",
        tmpBefore,
        "--after",
        tmpAfter,
        "--json",
      ]);
      expect(code).toBe(0);
      const data = JSON.parse(stdout);
      expect(data.added).toBeDefined();
      expect(data.removed).toBeDefined();
    } finally {
      await fs.unlink(tmpBefore).catch(() => {});
      await fs.unlink(tmpAfter).catch(() => {});
    }
  });
});

// ─── Budget ────────────────────────────────────────────────────────────

describe("ce budget", () => {
  it("estimates tokens for text", async () => {
    const { stdout, code } = await run(["budget", "-t", "hello world"]);
    expect(code).toBe(0);
    expect(stdout.trim()).toMatch(/\d+/);
  });

  it("fails without --text or --file", async () => {
    const { code } = await run(["budget"]);
    expect(code).not.toBe(0);
  });
});

// ─── Lint ──────────────────────────────────────────────────────────────

describe("ce lint", () => {
  it("validates items against context-item schema", async () => {
    const { stdout, code } = await run([
      "lint",
      "-s",
      "context-item",
      "-i",
      ITEMS_FILE,
    ]);
    expect(code).toBe(0);
    expect(stdout.toLowerCase()).toContain("valid");
  });

  it("rejects invalid data", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-invalid.json");
    await fs.writeFile(tmp, JSON.stringify({ noId: true }));
    try {
      const { code } = await run(["lint", "-s", "context-item", "-i", tmp]);
      expect(code).not.toBe(0);
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });

  it("validates beads-issue schema", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-beads.json");
    await fs.writeFile(
      tmp,
      JSON.stringify({
        id: "bd-1",
        title: "Test",
        status: "open",
        priority: 2,
        issue_type: "task",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:00:00Z",
      })
    );
    try {
      const { stdout, code } = await run([
        "lint",
        "-s",
        "beads-issue",
        "-i",
        tmp,
      ]);
      expect(code).toBe(0);
      expect(stdout.toLowerCase()).toContain("valid");
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });

  it("validates cost-estimate schema", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-cost-est.json");
    await fs.writeFile(
      tmp,
      JSON.stringify({
        model: "claude-sonnet-4-6",
        inputTokens: 1000,
        cachedTokens: 500,
        uncachedTokens: 500,
        outputTokens: 100,
        costWithoutCache: 0.01,
        costWithCache: 0.005,
        savings: 0.005,
        savingsPercent: 50,
        cacheEfficiency: 0.5,
      })
    );
    try {
      const { stdout, code } = await run([
        "lint",
        "-s",
        "cost-estimate",
        "-i",
        tmp,
      ]);
      expect(code).toBe(0);
      expect(stdout.toLowerCase()).toContain("valid");
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });

  it("validates pipeline-result schema", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-pipeline.json");
    await fs.writeFile(
      tmp,
      JSON.stringify({
        selected: [],
        dropped: [],
        totalTokens: 0,
        budget: { maxTokens: 4096 },
        inputCount: 0,
        stages: ["pack"],
      })
    );
    try {
      const { stdout, code } = await run([
        "lint",
        "-s",
        "pipeline-result",
        "-i",
        tmp,
      ]);
      expect(code).toBe(0);
      expect(stdout.toLowerCase()).toContain("valid");
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });
});

// ─── Place ─────────────────────────────────────────────────────────────

describe("ce place", () => {
  it("places items with attention-optimized strategy", async () => {
    const { stdout, code } = await run([
      "place",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.selected).toBeDefined();
    expect(data.strategy).toBe("attention-optimized");
  });

  it("places items with score-order strategy", async () => {
    const { stdout, code } = await run([
      "place",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "-s",
      "score-order",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.strategy).toBe("score-order");
  });
});

// ─── Quality ───────────────────────────────────────────────────────────

describe("ce quality", () => {
  it("analyzes context quality", async () => {
    const { stdout, code } = await run([
      "quality",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.itemCount).toBeGreaterThan(0);
    expect(data.overall).toBeGreaterThan(0);
    expect(data.density).toBeDefined();
    expect(data.diversity).toBeDefined();
  });
});

// ─── Effective Budget ──────────────────────────────────────────────────

describe("ce effective-budget", () => {
  it("computes effective budget", async () => {
    const { stdout, code } = await run([
      "effective-budget",
      "-t",
      "8000",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.advertised).toBe(8000);
    expect(data.effective).toBeLessThanOrEqual(8000);
    expect(data.effective).toBeGreaterThan(0);
  });

  it("computes for specific model", async () => {
    const { stdout, code } = await run([
      "effective-budget",
      "-t",
      "8000",
      "-m",
      "claude",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.model).toBe("claude");
    expect(data.effective).toBeLessThan(8000);
  });

  it("rejects non-positive tokens", async () => {
    const { code } = await run(["effective-budget", "-t", "-5"]);
    expect(code).not.toBe(0);
  });
});

// ─── Handoff ───────────────────────────────────────────────────────────

describe("ce handoff", () => {
  it("creates BEADS JSONL handoff", async () => {
    // When piped (non-TTY), handoff outputs JSON { jsonl, stats }
    const { stdout, code } = await run([
      "handoff",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.jsonl).toBeDefined();
    expect(data.stats.activeItems).toBeGreaterThan(0);
    // Verify JSONL lines are valid
    const lines = data.jsonl.trim().split("\n").filter(Boolean);
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) {
      expect(() => JSON.parse(line)).not.toThrow();
    }
  });

  it("creates handoff with agent metadata", async () => {
    const { stdout, code } = await run([
      "handoff",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "--agent",
      "test-agent",
      "--session-id",
      "test-session",
      "--notes",
      "Test handoff",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    const lines = data.jsonl.trim().split("\n").filter(Boolean);
    const manifest = JSON.parse(lines[0]);
    expect(manifest.metadata._ce_handoff.sessionId).toBe("test-session");
  });

  it("outputs stats when writing to file", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-handoff.jsonl");
    try {
      const { stdout, code } = await run([
        "handoff",
        "-i",
        ITEMS_FILE,
        "-b",
        "100",
        "-o",
        tmp,
        "--json",
      ]);
      expect(code).toBe(0);
      const stats = JSON.parse(stdout);
      expect(stats.activeItems).toBeGreaterThan(0);
      expect(stats.totalIssues).toBeGreaterThan(0);
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });
});

// ─── Pickup ────────────────────────────────────────────────────────────

describe("ce pickup", () => {
  it("picks up items from handoff JSONL", async () => {
    // First create a handoff (piped output is JSON { jsonl, stats })
    const { stdout: handoffOut } = await run([
      "handoff",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
    ]);
    const handoffData = JSON.parse(handoffOut);

    // Write the actual JSONL to temp file
    const tmp = path.join(os.tmpdir(), "ce-test-pickup.jsonl");
    await fs.writeFile(tmp, handoffData.jsonl);

    try {
      const { stdout, code } = await run(["pickup", "-i", tmp, "--json"]);
      expect(code).toBe(0);
      const data = JSON.parse(stdout);
      expect(data.items).toBeDefined();
      expect(data.items.length).toBeGreaterThan(0);
      expect(data.stats).toBeDefined();
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });
});

// ─── Cost ──────────────────────────────────────────────────────────────

describe("ce cost", () => {
  it("estimates cost for claude-sonnet-4-6", async () => {
    const { stdout, code } = await run([
      "cost",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "-m",
      "claude-sonnet-4-6",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.model).toBe("claude-sonnet-4-6");
    expect(data.inputTokens).toBeGreaterThan(0);
    expect(data.costWithCache).toBeLessThanOrEqual(data.costWithoutCache);
  });

  it("estimates with projection", async () => {
    const { stdout, code } = await run([
      "cost",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "-m",
      "claude-sonnet-4-6",
      "--requests",
      "1000",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.requestCount).toBe(1000);
    expect(data.totalSavings).toBeGreaterThanOrEqual(0);
  });

  it("fails with unknown model", async () => {
    const { code } = await run([
      "cost",
      "-i",
      ITEMS_FILE,
      "-b",
      "100",
      "-m",
      "unknown-model-xyz",
    ]);
    expect(code).not.toBe(0);
  });
});

// ─── Input Validation ──────────────────────────────────────────────────

describe("input validation", () => {
  it("rejects non-integer budget", async () => {
    const { code } = await run(["pack", "-i", ITEMS_FILE, "-b", "abc"]);
    expect(code).not.toBe(0);
  });

  it("rejects zero budget", async () => {
    const { code } = await run(["pack", "-i", ITEMS_FILE, "-b", "0"]);
    expect(code).not.toBe(0);
  });

  it("rejects negative budget", async () => {
    const { code } = await run(["pack", "-i", ITEMS_FILE, "-b", "-100"]);
    expect(code).not.toBe(0);
  });

  it("shows help with --help", async () => {
    const { stdout, code } = await run(["--help"]);
    expect(code).toBe(0);
    expect(stdout).toContain("ce");
    expect(stdout).toContain("pack");
    expect(stdout).toContain("trace");
  });
});

// ─── Regression tests for audit fixes ───────────────────────────────────

describe("loadItems validation for unrecognized JSON (H5)", () => {
  it("rejects unrecognized JSON shape from stdin with error", async () => {
    // A plain object with no items/selected/array shape should error, not return []
    const badInput = JSON.stringify({ foo: "bar", baz: 42 });
    const { code, stderr } = await run(["pack", "-i", "-", "-b", "100"], {
      input: badInput,
    });
    expect(code).not.toBe(0);
    // The error output (JSON since non-TTY) should contain the validation message
    const errorData = JSON.parse(stderr);
    expect(errorData.error).toContain("Invalid input");
  });

  it("rejects a plain string value from stdin", async () => {
    const { code, stderr } = await run(["pack", "-i", "-", "-b", "100"], {
      input: JSON.stringify("just a string"),
    });
    expect(code).not.toBe(0);
    const errorData = JSON.parse(stderr);
    expect(errorData.error).toContain("Invalid input");
  });

  it("rejects a number value from stdin", async () => {
    const { code, stderr } = await run(["pack", "-i", "-", "-b", "100"], {
      input: JSON.stringify(42),
    });
    expect(code).not.toBe(0);
    const errorData = JSON.parse(stderr);
    expect(errorData.error).toContain("Invalid input");
  });

  it("rejects JSON null from stdin with the clean validation error", async () => {
    // JSON null must fall through to the guarded validation error rather than
    // leaking an internal TypeError from dereferencing null.items
    const { code, stderr } = await run(["pack", "-i", "-", "-b", "100"], {
      input: JSON.stringify(null),
    });
    expect(code).not.toBe(0);
    const errorData = JSON.parse(stderr);
    expect(errorData.error).toContain("Invalid input");
  });
});

describe("--json flag on budget command (H1)", () => {
  it("produces JSON output with --json flag", async () => {
    const { stdout, code } = await run([
      "budget",
      "-t",
      "hello world tokens",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.tokens).toBeGreaterThan(0);
    expect(data.provider).toBeDefined();
  });

  it("JSON output includes provider field", async () => {
    const { stdout, code } = await run([
      "budget",
      "-t",
      "test input",
      "-p",
      "openai",
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.provider).toBe("openai");
    expect(data.tokens).toBeGreaterThan(0);
  });
});

describe("--json flag on lint command (H1)", () => {
  it("produces JSON output with --json flag for valid data", async () => {
    const { stdout, code } = await run([
      "lint",
      "-s",
      "context-item",
      "-i",
      ITEMS_FILE,
      "--json",
    ]);
    expect(code).toBe(0);
    const data = JSON.parse(stdout);
    expect(data.valid).toBe(true);
  });

  it("produces JSON error output with --json flag for invalid data", async () => {
    const tmp = path.join(os.tmpdir(), "ce-test-lint-json.json");
    await fs.writeFile(tmp, JSON.stringify({ noId: true }));
    try {
      const { code, stderr } = await run([
        "lint",
        "-s",
        "context-item",
        "-i",
        tmp,
        "--json",
      ]);
      expect(code).not.toBe(0);
      // Error should be JSON since --json forces JSON mode
      const errorData = JSON.parse(stderr);
      expect(errorData.error).toContain("Validation failed");
    } finally {
      await fs.unlink(tmp).catch(() => {});
    }
  });
});

// ─── Schema resolution (hardening regression) ───────────────────────────

/**
 * Run the CLI binary from an arbitrary working directory. The shared `run`
 * helper pins cwd to the repo fixtures root, which masks cwd-dependent schema
 * resolution bugs, so this regression needs its own cwd-aware runner.
 */
function runIn(
  cwd: string,
  args: string[]
): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise(resolve => {
    execFile(
      process.execPath,
      [CLI, ...args],
      {
        env: { ...process.env, NO_COLOR: "1" },
        cwd,
        maxBuffer: 10 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        resolve({
          stdout: stdout?.toString() ?? "",
          stderr: stderr?.toString() ?? "",
          code: error ? ((error as any).code ?? 1) : 0,
        });
      }
    );
  });
}

describe("ce lint schema resolution", () => {
  it("ignores an unrelated cwd schemas/ directory and uses bundled schemas", async () => {
    // Reproduces the bug: a project that contains its own unrelated `schemas/`
    // folder (JSON Schema, GraphQL, Avro, DB migrations, ...) must not break
    // `ce lint`. Previously findSchemasDir(cwd) returned this folder, the ce
    // schema files ENOENT'd, and the lint catch block misreported it as
    // "File not found: <input>" even though the input clearly exists.
    const dir = await fs.mkdtemp(
      path.join(os.tmpdir(), "ce-unrelated-schemas-")
    );
    try {
      const unrelated = path.join(dir, "schemas");
      await fs.mkdir(unrelated, { recursive: true });
      // An unrelated schema file -- NOT part of the ce schema set.
      await fs.writeFile(
        path.join(unrelated, "unrelated.json"),
        JSON.stringify({ type: "object" })
      );
      const itemsFile = path.join(dir, "items.json");
      await fs.writeFile(
        itemsFile,
        JSON.stringify([{ id: "a", content: "hello" }])
      );

      const { stdout, stderr, code } = await runIn(dir, [
        "lint",
        "-s",
        "context-item",
        "-i",
        "items.json",
        "--json",
      ]);

      expect(stderr).not.toContain("File not found");
      expect(code).toBe(0);
      expect(JSON.parse(stdout).valid).toBe(true);
    } finally {
      await fs.rm(dir, { recursive: true, force: true });
    }
  });

  it("honours a complete bring-your-own schemas/ override in cwd", async () => {
    // The legitimate override path: when cwd's schemas/ contains the FULL ce
    // schema set it should still be used (not silently bypassed).
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "ce-full-schemas-"));
    try {
      const override = path.join(dir, "schemas");
      await fs.mkdir(override, { recursive: true });
      // Copy the complete bundled schema set into the override directory.
      const bundled = path.resolve(import.meta.dirname, "..", "schemas");
      for (const f of await fs.readdir(bundled)) {
        if (f.endsWith(".json")) {
          await fs.copyFile(path.join(bundled, f), path.join(override, f));
        }
      }
      const itemsFile = path.join(dir, "items.json");
      await fs.writeFile(
        itemsFile,
        JSON.stringify([{ id: "a", content: "hello" }])
      );

      const { stdout, code } = await runIn(dir, [
        "lint",
        "-s",
        "context-item",
        "-i",
        "items.json",
        "--json",
      ]);

      expect(code).toBe(0);
      expect(JSON.parse(stdout).valid).toBe(true);
    } finally {
      await fs.rm(dir, { recursive: true, force: true });
    }
  });
});
