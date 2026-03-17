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
  return new Promise(resolve => {
    const child = execFile(
      process.execPath,
      [CLI, ...args],
      {
        env: { ...process.env, NO_COLOR: "1", ...options.env },
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
