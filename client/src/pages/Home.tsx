import { useMemo, useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Brain,
  Terminal,
  Layers,
  Settings,
  ChevronRight,
  BookOpen,
  Code,
  Github,
  CheckCircle2,
  AlertCircle,
  FileCode,
  Cpu,
  Zap,
  Box,
} from "lucide-react";
import { pack, diff, type ContextItem } from "@ce/core";
import { CodeBlock, codeExamples } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useTheme } from "@/contexts/ThemeContext";

const fadeInUp = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const defaultItems = `[
  {
    "id": "system",
    "content": "You are a concise, rigorous assistant.",
    "priority": 10,
    "recency": 3,
    "tokens": 12
  },
  {
    "id": "project-context",
    "content": "Building a Context Engineering Toolkit for production agents.",
    "priority": 8,
    "recency": 5,
    "tokens": 16
  },
  {
    "id": "long-documentation",
    "content": "Context engineering is the practice of surgically selecting and compressing information to fit within an LLM's finite token budget. It differs from simple RAG by being budget-aware and priority-driven.",
    "priority": 4,
    "recency": 1,
    "tokens": 60,
    "compressions": [
      { "content": "Context engineering is budget-aware info selection for LLMs.", "tokens": 15, "note": "summary" }
    ]
  }
]`;

const defaultTrace = `{"type":"pack","pack":{"budget":{"maxTokens":120},"selected":[{"id":"system","content":"You are a helpful assistant.","tokens":12}],"dropped":[{"id":"notes","content":"User prefers concise answers.","tokens":8}],"totalTokens":12}}
{"type":"step","id":"system","decision":"include","tokens":12,"score":10,"reason":"fits_budget"}
{"type":"step","id":"notes","decision":"exclude","tokens":8,"score":4,"reason":"over_budget"}`;

function parseItems(raw: string): { items: ContextItem[]; error?: string } {
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return { items: parsed };
    if (parsed?.items && Array.isArray(parsed.items))
      return { items: parsed.items };
    return { items: [], error: "Expected an array or { items: [] }" };
  } catch (error) {
    return { items: [], error: (error as Error).message };
  }
}

function parseTrace(raw: string): {
  pack?: any;
  steps: Array<Record<string, any>>;
  error?: string;
} {
  const trimmed = raw.trim();
  if (!trimmed) return { steps: [], error: "Provide trace JSON or JSONL" };
  try {
    const lines = trimmed.split(/\r?\n/).filter(Boolean);
    const steps: Array<Record<string, any>> = [];
    let pack: any | undefined;
    for (const line of lines) {
      const entry = JSON.parse(line);
      if (entry.type === "pack") pack = entry.pack;
      else steps.push(entry);
    }
    return { pack, steps };
  } catch (error) {
    return { steps: [], error: (error as Error).message };
  }
}

export default function Home() {
  const { theme, toggleTheme } = useTheme();
  const [itemsJson, setItemsJson] = useState(defaultItems);
  const [budgetA, setBudgetA] = useState("128");
  const [budgetB, setBudgetB] = useState("64");
  const [traceInput, setTraceInput] = useState(defaultTrace);

  const parsed = useMemo(() => parseItems(itemsJson), [itemsJson]);

  const packA = useMemo(() => {
    if (parsed.error || !parsed.items.length) return null;
    try {
      return pack(
        parsed.items,
        { maxTokens: Number(budgetA) || 0 },
        { allowCompression: true }
      );
    } catch (e) {
      return null;
    }
  }, [parsed, budgetA]);

  const packB = useMemo(() => {
    if (parsed.error || !parsed.items.length) return null;
    try {
      return pack(
        parsed.items,
        { maxTokens: Number(budgetB) || 0 },
        { allowCompression: true }
      );
    } catch (e) {
      return null;
    }
  }, [parsed, budgetB]);

  const packDiff = useMemo(() => {
    if (!packA || !packB) return null;
    return diff(packA, packB);
  }, [packA, packB]);

  const traceParsed = useMemo(() => parseTrace(traceInput), [traceInput]);
  const decisionCounts = useMemo(() => {
    const counts = { include: 0, exclude: 0, compress: 0 };
    traceParsed.steps.forEach(step => {
      const d = step.decision;
      if (d === "include") counts.include++;
      else if (d === "exclude") counts.exclude++;
      else if (d === "compress") counts.compress++;
    });
    return counts;
  }, [traceParsed.steps]);

  const navItems = [
    { label: "Why CE?", id: "why" },
    { label: "Patterns", id: "patterns" },
    { label: "Playground", id: "playground" },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground transition-colors duration-300">
      {/* HEADER */}
      <header className="border-b border-marker-black/10 bg-background/80 backdrop-blur-md sticky top-0 z-50">
        <div className="container flex items-center justify-between py-3 px-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-marker-blue/10 flex items-center justify-center border-2 border-marker-blue/20">
              <Brain className="w-6 h-6 marker-blue" />
            </div>
            <div>
              <p className="font-display text-2xl marker-black leading-none">
                CE Toolkit
              </p>
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest mt-1">
                Production Ready
              </p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-8">
            {navItems.map(item => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className="text-sm font-bold marker-black/60 hover:marker-blue transition-all uppercase tracking-tight"
              >
                {item.label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleTheme}
              className="rounded-full"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </Button>
            <Button className="bg-marker-black hover:bg-marker-black/90 text-background shadow-[3px_3px_0_0_rgba(0,0,0,0.2)] font-bold">
              <Github className="w-4 h-4 mr-2" /> Local Repo
            </Button>
          </div>
        </div>
      </header>

      <main className="container py-12 px-4">
        {/* HERO */}
        <motion.section
          id="hero"
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
          className="grid lg:grid-cols-[1.1fr_0.9fr] gap-12 items-center mb-24"
        >
          <motion.div variants={fadeInUp} className="space-y-6">
            <div className="inline-block px-3 py-1 bg-highlight-yellow text-foreground text-xs font-bold rounded-sm rotate-[-1deg]">
              CONTEXT AS AN ENGINEERING PROBLEM
            </div>
            <h1 className="font-display text-6xl md:text-8xl leading-[0.9] marker-black">
              Pack context <br />
              <span className="marker-blue">not prompts.</span>
            </h1>
            <p className="text-xl text-muted-foreground max-w-xl leading-relaxed">
              Stop guessing if your agent's context will fit. CE Toolkit
              provides the algorithms to score, rank, and compress context items
              into deterministic token budgets.
            </p>
            <div className="flex flex-wrap gap-5 pt-4">
              <Button
                size="lg"
                className="bg-marker-blue hover:bg-marker-blue/90 text-white h-14 px-8 text-lg rounded-none shadow-[6px_6px_0_0_rgba(0,102,204,0.2)] font-display"
                asChild
              >
                <a href="#playground">
                  Try the Playground <ChevronRight className="w-5 h-5 ml-2" />
                </a>
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="h-14 px-8 text-lg rounded-none border-2 border-marker-black hover:bg-marker-black/5 font-display"
                asChild
              >
                <a href="#patterns">Read Patterns</a>
              </Button>
            </div>
          </motion.div>

          <motion.div variants={fadeInUp} className="relative">
            <div className="absolute -top-4 -left-4 w-full h-full border-2 border-dashed border-marker-blue/30 rounded-lg -z-10 rotate-1"></div>
            <Card className="whiteboard-card p-2 overflow-hidden bg-card">
              <div className="bg-marker-black/5 p-4 border-b-2 border-marker-black/10 flex items-center justify-between">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-marker-red/40" />
                  <div className="w-3 h-3 rounded-full bg-highlight-yellow" />
                  <div className="w-3 h-3 rounded-full bg-marker-green/40" />
                </div>
                <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
                  example-pack.ts
                </span>
              </div>
              <CodeBlock
                language="typescript"
                code={`import { pack } from "@ce/core";\n\nconst items = [\n  { id: "sys", content: "...", priority: 10 },\n  { id: "mem", content: "...", priority: 5 }\n];\n\nconst result = pack(items, { maxTokens: 512 });\n// result.selected now contains exactly what fits.`}
              />
            </Card>
          </motion.div>
        </motion.section>

        {/* WHY SECTION */}
        <section id="why" className="scroll-mt-24 mb-32">
          <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
            <h2 className="font-display text-5xl marker-black underline decoration-marker-red/20 decoration-8 underline-offset-8">
              Why Context Engineering?
            </h2>
            <p className="text-muted-foreground text-lg">
              Modern agents fail when context overflows or becomes irrelevant.
              We treat context as a finite resource that needs management.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <div className="whiteboard-card p-8 bg-card space-y-4">
              <div className="w-12 h-12 rounded-lg bg-marker-blue/10 flex items-center justify-center border-2 border-marker-blue/20">
                <Zap className="w-6 h-6 marker-blue" />
              </div>
              <h3 className="font-display text-2xl marker-black">
                Deterministic Packing
              </h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                RAG gives you "relevant" documents. CE Toolkit gives you the
                *best* documents that fit into your *specific* token budget,
                every time.
              </p>
            </div>
            <div className="whiteboard-card p-8 bg-card space-y-4 rotate-1">
              <div className="w-12 h-12 rounded-lg bg-marker-green/10 flex items-center justify-center border-2 border-marker-green/20">
                <BookOpen className="w-6 h-6 marker-green" />
              </div>
              <h3 className="font-display text-2xl marker-black">
                Progressive Compression
              </h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                If a 500-token document won't fit, CE can automatically swap it
                for a 50-token summary rather than dropping the information
                entirely.
              </p>
            </div>
            <div className="whiteboard-card p-8 bg-card space-y-4 -rotate-1">
              <div className="w-12 h-12 rounded-lg bg-marker-red/10 flex items-center justify-center border-2 border-marker-red/20">
                <Cpu className="w-6 h-6 marker-red" />
              </div>
              <h3 className="font-display text-2xl marker-black">
                Cross-Platform SDKs
              </h3>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Identical algorithms in TypeScript and Python ensure your
                frontend demos and backend production logic behave exactly the
                same way.
              </p>
            </div>
          </div>
        </section>

        {/* PATTERNS SECTION */}
        <section id="patterns" className="scroll-mt-24 mb-32">
          <div className="flex items-center gap-4 mb-12">
            <h2 className="font-display text-5xl marker-black">
              Context Patterns
            </h2>
            <div className="flex-1 h-[2px] bg-marker-black/10" />
            <div className="px-3 py-1 bg-highlight-yellow marker-black text-xs font-mono font-bold rounded-full border border-marker-black/20">
              CORE DESIGNS
            </div>
          </div>

          <div className="space-y-16">
            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Box className="w-6 h-6 marker-blue" />
                  <h3 className="font-display text-3xl marker-black">
                    Observation Masking
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Compress tool output to preserve signal while reducing tokens.
                  Instead of sending raw JSON, you truncate and extract key
                  fields.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden">
                <CodeBlock
                  language="python"
                  code={codeExamples.observationMasking}
                />
              </Card>
            </div>

            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4 lg:order-2">
                <div className="flex items-center gap-3">
                  <Layers className="w-6 h-6 marker-green" />
                  <h3 className="font-display text-3xl marker-black">
                    KV-Cache Optimisation
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Keep your system prompt and tool definitions static. Only
                  append new messages to maximize KV-Cache hits across agent
                  steps.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden lg:order-1 rotate-1">
                <CodeBlock
                  language="python"
                  code={codeExamples.kvCacheOptimisation}
                />
              </Card>
            </div>

            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Terminal className="w-6 h-6 marker-red" />
                  <h3 className="font-display text-3xl marker-black">
                    Deep Agent Planning
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Provide agents with structured phases. They can easily track
                  what has been done and what to do next without hallucinating
                  plans.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden -rotate-1">
                <CodeBlock
                  language="python"
                  code={codeExamples.deepAgentPlanning}
                />
              </Card>
            </div>

            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4 lg:order-2">
                <div className="flex items-center gap-3">
                  <Settings className="w-6 h-6 marker-black" />
                  <h3 className="font-display text-3xl marker-black">
                    Tool Masking
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Pass ALL tools to the LLM definitions to keep KV-cache stable,
                  but use \`tool_choice\` masking to enforce state machines and
                  prevent invalid tool calls.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden lg:order-1">
                <CodeBlock language="python" code={codeExamples.toolMasking} />
              </Card>
            </div>

            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Database className="w-6 h-6 marker-blue" />
                  <h3 className="font-display text-3xl marker-black">
                    Cron Job Pattern
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Stateless execution for scheduled tasks. The agent wakes up,
                  loads its context, executes, and saves summary states for the
                  next run.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden rotate-1">
                <CodeBlock
                  language="python"
                  code={codeExamples.cronJobPattern}
                />
              </Card>
            </div>

            <div className="grid lg:grid-cols-2 gap-8">
              <div className="space-y-4 lg:order-2">
                <div className="flex items-center gap-3">
                  <FileCode className="w-6 h-6 marker-green" />
                  <h3 className="font-display text-3xl marker-black">
                    Context Summarisation
                  </h3>
                </div>
                <p className="text-muted-foreground">
                  Intelligently summarize older message history when approaching
                  the context window limits, preserving recent crucial context.
                </p>
              </div>
              <Card className="whiteboard-card p-0 bg-card overflow-hidden lg:order-1 -rotate-1">
                <CodeBlock
                  language="python"
                  code={codeExamples.contextSummarisation}
                />
              </Card>
            </div>
          </div>
        </section>

        {/* PLAYGROUND */}
        <section id="playground" className="mt-24 scroll-mt-24 mb-32">
          <div className="flex items-center gap-4 mb-8">
            <h2 className="font-display text-5xl marker-black">
              Real-time Playground
            </h2>
            <div className="flex-1 h-[2px] bg-marker-black/10" />
            <div className="px-3 py-1 bg-marker-green/10 marker-green text-xs font-mono font-bold rounded-full border border-marker-green/20">
              LIVE FRAMEWORK
            </div>
          </div>

          <div className="grid lg:grid-cols-2 gap-10">
            <div className="space-y-6">
              <Card className="whiteboard-card">
                <CardHeader className="flex flex-row items-center justify-between pb-2 border-b-2 border-marker-black/5">
                  <CardTitle className="font-display text-2xl marker-black">
                    1. Define Context Items
                  </CardTitle>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setItemsJson(defaultItems)}
                    className="text-[10px] font-mono uppercase marker-blue underline font-bold"
                  >
                    Reset
                  </Button>
                </CardHeader>
                <CardContent className="pt-6">
                  <Textarea
                    value={itemsJson}
                    onChange={e => setItemsJson(e.target.value)}
                    className="font-mono text-xs min-h-[350px] bg-marker-black/[0.02] border-2 border-marker-black/10 text-foreground"
                  />
                  {parsed.error && (
                    <div className="mt-3 p-3 bg-marker-red/10 border-2 border-marker-red/20 marker-red text-xs font-mono rounded">
                      <AlertCircle className="w-4 h-4 inline mr-2" /> Error:{" "}
                      {parsed.error}
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-bold marker-black uppercase ml-1">
                    Budget A (Tokens)
                  </label>
                  <Input
                    type="number"
                    value={budgetA}
                    onChange={e => setBudgetA(e.target.value)}
                    className="font-mono border-2 border-marker-black/10 bg-background"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-bold marker-black uppercase ml-1">
                    Budget B (Tokens)
                  </label>
                  <Input
                    type="number"
                    value={budgetB}
                    onChange={e => setBudgetB(e.target.value)}
                    className="font-mono border-2 border-marker-black/10 bg-background"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-6">
              <Card className="whiteboard-card bg-marker-black text-background shadow-[8px_8px_0_0_rgba(45,52,54,0.3)]">
                <CardHeader className="border-b border-background/10">
                  <div className="flex items-center justify-between">
                    <CardTitle className="font-display text-3xl text-background">
                      Live Pack Result
                    </CardTitle>
                    <div className="flex gap-4">
                      <div className="text-center">
                        <p className="text-[10px] uppercase text-background/50 tracking-tighter font-bold">
                          A: {packA?.totalTokens ?? 0}t
                        </p>
                      </div>
                      <div className="text-center">
                        <p className="text-[10px] uppercase text-background/50 tracking-tighter font-bold">
                          B: {packB?.totalTokens ?? 0}t
                        </p>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-6 max-h-[500px] overflow-y-auto">
                  <div className="space-y-6">
                    <div>
                      <h4 className="text-[10px] font-bold uppercase tracking-widest text-marker-green mb-4">
                        Selection Diffs (A → B)
                      </h4>
                      {packDiff ? (
                        <div className="space-y-2 font-mono text-[11px]">
                          {packDiff.removed.map(item => (
                            <div
                              key={item.id}
                              className="p-2 border border-marker-red/30 bg-marker-red/10 rounded flex items-center justify-between"
                            >
                              <span className="marker-red">- {item.id}</span>
                              <span className="text-background/40 text-[9px] uppercase font-bold">
                                Dropped in B
                              </span>
                            </div>
                          ))}
                          {packDiff.added.map(item => (
                            <div
                              key={item.id}
                              className="p-2 border border-marker-green/30 bg-marker-green/10 rounded flex items-center justify-between"
                            >
                              <span className="marker-green">+ {item.id}</span>
                              <span className="text-background/40 text-[9px] uppercase font-bold">
                                Added in B
                              </span>
                            </div>
                          ))}
                          {packDiff.kept.map(item => (
                            <div
                              key={item.id}
                              className="p-2 border border-background/10 bg-background/5 rounded flex items-center justify-between"
                            >
                              <span className="text-background/60">
                                • {item.id}
                              </span>
                              <span className="text-background/20 text-[9px] uppercase font-bold">
                                Constant
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-background/40 italic text-center py-4">
                          Waiting for items...
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              <div className="p-6 bg-marker-blue/5 border-2 border-dashed border-marker-blue/20 rounded-lg text-center space-y-3">
                <FileCode className="w-8 h-8 marker-blue mx-auto opacity-50" />
                <p className="font-display text-xl marker-black">
                  Interactive Trace
                </p>
                <p className="text-xs text-muted-foreground">
                  Adjust the budgets above to see how the ranking engine makes
                  inclusion decisions.
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* FOOTER */}
      <footer className="border-t-2 border-marker-black/10 bg-background/50 py-16 px-4">
        <div className="container grid md:grid-cols-3 gap-12 mb-12">
          <div className="col-span-2 space-y-4">
            <div className="flex items-center gap-3">
              <Brain className="w-6 h-6 marker-black" />
              <p className="font-display text-2xl marker-black">
                Context Engineering Toolkit
              </p>
            </div>
            <p className="text-sm text-muted-foreground max-w-xs">
              A professional-grade suite for managing LLM context windows with
              precision and transparency.
            </p>
          </div>
          <div className="space-y-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              Navigation
            </p>
            <ul className="space-y-2 text-sm font-medium">
              <li>
                <a href="#why" className="hover:marker-blue transition-colors">
                  Why CE?
                </a>
              </li>
              <li>
                <a
                  href="#patterns"
                  className="hover:marker-blue transition-colors"
                >
                  Patterns
                </a>
              </li>
              <li>
                <a
                  href="#playground"
                  className="hover:marker-blue transition-colors"
                >
                  Playground
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="container flex flex-col md:flex-row justify-between items-center gap-4 pt-12 border-t border-marker-black/5">
          <p className="text-[10px] text-muted-foreground font-mono">
            © 2026 CE-TOOLKIT. LOCAL MONOREPO VERSION.
          </p>
          <div className="flex gap-6 grayscale opacity-50">
            <Code className="w-4 h-4" />
            <Terminal className="w-4 h-4" />
            <Settings className="w-4 h-4" />
          </div>
        </div>
      </footer>
    </div>
  );
}
