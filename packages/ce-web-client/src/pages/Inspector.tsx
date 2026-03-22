import { useMemo, useState } from "react";
import { Brain, Search, ArrowLeft, Eye, EyeOff } from "lucide-react";
import {
  tracePack,
  diff,
  type ContextItem,
  type TraceStep,
} from "@context-engineering/core";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useTheme } from "@/contexts/ThemeContext";
import { TokenBudgetBar } from "@/components/inspector/TokenBudgetBar";
import { TraceTimeline } from "@/components/inspector/TraceTimeline";
import { ItemCard } from "@/components/inspector/ItemCard";
import { DiffView } from "@/components/inspector/DiffView";

const sampleItems = `[
  {
    "id": "system-prompt",
    "content": "You are a senior software engineer. Follow the user's instructions carefully. Think step by step.",
    "priority": 10,
    "recency": 5,
    "tokens": 24
  },
  {
    "id": "project-readme",
    "content": "# Context Engineering Toolkit\\nA production-grade library for managing LLM context windows with scoring, packing, and compression algorithms.",
    "priority": 7,
    "recency": 3,
    "tokens": 35,
    "compressions": [
      { "content": "CE Toolkit: LLM context window management lib.", "tokens": 10, "note": "one-liner" }
    ]
  },
  {
    "id": "recent-code-change",
    "content": "diff --git a/src/pack.ts\\n+ export function packAsync(items, budget, options) {\\n+   return internalPack(items, budget, options);\\n+ }",
    "priority": 8,
    "recency": 9,
    "tokens": 45
  },
  {
    "id": "old-discussion",
    "content": "Earlier we discussed whether to use a greedy or knapsack approach. We decided greedy is fast enough for real-time use and knapsack is only needed for batch processing with very tight budgets.",
    "priority": 3,
    "recency": 1,
    "tokens": 55
  },
  {
    "id": "test-results",
    "content": "All 35 tests passing. Coverage: 92% statements, 88% branches. No regressions from the async refactor.",
    "priority": 5,
    "recency": 7,
    "tokens": 28
  },
  {
    "id": "user-preferences",
    "content": "User prefers: TypeScript strict mode, functional style, small focused functions under 30 lines, descriptive naming over short naming.",
    "priority": 6,
    "recency": 2,
    "tokens": 30
  },
  {
    "id": "api-docs",
    "content": "The pack() function accepts items: ContextItem[], budget: Budget, and options?: PackOptions. Returns ContextPack with selected, dropped, totalTokens, and stats fields. Budget requires maxTokens and optionally reserveTokens.",
    "priority": 4,
    "recency": 4,
    "tokens": 50,
    "compressions": [
      { "content": "pack(items, budget, options?) -> { selected, dropped, totalTokens, stats }", "tokens": 15, "note": "signature only" }
    ]
  }
]`;

function parseItems(raw: string): { items: ContextItem[]; error?: string } {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return { items: parsed };
    return { items: [], error: "Expected a JSON array" };
  } catch (error) {
    return { items: [], error: (error as Error).message };
  }
}

type ActiveTab = "trace" | "items" | "diff";

export default function Inspector() {
  const { theme, toggleTheme } = useTheme();
  const [itemsJson, setItemsJson] = useState(sampleItems);
  const [budgetA, setBudgetA] = useState("120");
  const [budgetB, setBudgetB] = useState("80");
  const [activeTab, setActiveTab] = useState<ActiveTab>("trace");
  const [selectedStepId, setSelectedStepId] = useState<string>();
  const [showContent, setShowContent] = useState(true);

  const parsed = useMemo(() => parseItems(itemsJson), [itemsJson]);

  const traceA = useMemo(() => {
    if (parsed.error || !parsed.items.length) return null;
    try {
      return tracePack(
        parsed.items,
        { maxTokens: Number(budgetA) || 0 },
        { allowCompression: true }
      );
    } catch {
      return null;
    }
  }, [parsed, budgetA]);

  const traceB = useMemo(() => {
    if (parsed.error || !parsed.items.length) return null;
    try {
      return tracePack(
        parsed.items,
        { maxTokens: Number(budgetB) || 0 },
        { allowCompression: true }
      );
    } catch {
      return null;
    }
  }, [parsed, budgetB]);

  const packDiff = useMemo(() => {
    if (!traceA || !traceB) return null;
    return diff(traceA.pack, traceB.pack);
  }, [traceA, traceB]);

  const selectedStep = useMemo(() => {
    if (!selectedStepId || !traceA) return null;
    return traceA.steps.find(s => s.id === selectedStepId) ?? null;
  }, [selectedStepId, traceA]);

  const selectedItem = useMemo(() => {
    if (!selectedStepId || !parsed.items.length) return null;
    return parsed.items.find(i => i.id === selectedStepId) ?? null;
  }, [selectedStepId, parsed.items]);

  const tabs: { id: ActiveTab; label: string }[] = [
    { id: "trace", label: "Decision Trace" },
    { id: "items", label: "Items" },
    { id: "diff", label: "A / B Diff" },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground transition-colors duration-300">
      {/* Header */}
      <header className="border-b border-marker-black/10 bg-background/80 backdrop-blur-md sticky top-0 z-50">
        <div className="container flex items-center justify-between py-3 px-4">
          <div className="flex items-center gap-3">
            <a
              href="/"
              className="flex items-center gap-2 hover:opacity-70 transition-opacity"
            >
              <ArrowLeft className="w-4 h-4 text-muted-foreground" />
            </a>
            <div className="w-10 h-10 rounded-full bg-marker-blue/10 flex items-center justify-center border-2 border-marker-blue/20">
              <Search className="w-5 h-5 marker-blue" />
            </div>
            <div>
              <p className="font-display text-2xl marker-black leading-none">
                Context Inspector
              </p>
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest mt-1">
                Debug your context window
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleTheme}
              className="rounded-full"
            >
              {theme === "dark" ? "light" : "dark"}
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href="/">
                <Brain className="w-4 h-4 mr-1" /> Home
              </a>
            </Button>
          </div>
        </div>
      </header>

      <main className="container py-6 px-4">
        <div className="grid lg:grid-cols-[380px_1fr] gap-6">
          {/* LEFT PANEL: Input */}
          <div className="space-y-4">
            <Card className="whiteboard-card">
              <CardHeader className="pb-2 border-b-2 border-marker-black/5">
                <CardTitle className="font-display text-xl marker-black">
                  Context Items
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <Textarea
                  value={itemsJson}
                  onChange={e => setItemsJson(e.target.value)}
                  className="font-mono text-[10px] min-h-[280px] bg-marker-black/[0.02] border-2 border-marker-black/10 text-foreground leading-relaxed"
                />
                {parsed.error && (
                  <div className="mt-2 p-2 bg-marker-red/10 border border-marker-red/20 marker-red text-[10px] font-mono rounded">
                    {parsed.error}
                  </div>
                )}
                <div className="mt-2 text-[10px] text-muted-foreground font-mono">
                  {parsed.items.length} items,{" "}
                  {parsed.items.reduce((s, i) => s + (i.tokens ?? 0), 0)} total
                  tokens
                </div>
              </CardContent>
            </Card>

            {/* Budget controls */}
            <Card className="whiteboard-card">
              <CardContent className="pt-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label
                      htmlFor="inspector-budget-a"
                      className="text-[10px] font-bold marker-black uppercase ml-1"
                    >
                      Budget A
                    </label>
                    <Input
                      id="inspector-budget-a"
                      type="number"
                      value={budgetA}
                      onChange={e => setBudgetA(e.target.value)}
                      className="font-mono text-sm border-2 border-marker-green/30 bg-marker-green/5"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="inspector-budget-b"
                      className="text-[10px] font-bold marker-black uppercase ml-1"
                    >
                      Budget B
                    </label>
                    <Input
                      id="inspector-budget-b"
                      type="number"
                      value={budgetB}
                      onChange={e => setBudgetB(e.target.value)}
                      className="font-mono text-sm border-2 border-marker-blue/30 bg-marker-blue/5"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Item detail panel */}
            {selectedItem && selectedStep && (
              <Card className="whiteboard-card border-2 border-marker-blue/30">
                <CardHeader className="pb-2 border-b-2 border-marker-blue/10">
                  <CardTitle className="font-display text-lg marker-blue">
                    {selectedStep.id}
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-3 space-y-2">
                  <div className="flex flex-wrap gap-2 text-[10px] font-mono">
                    <span
                      className={`px-2 py-0.5 rounded font-bold uppercase ${
                        selectedStep.decision === "include"
                          ? "bg-marker-green/10 marker-green"
                          : selectedStep.decision === "exclude"
                            ? "bg-marker-red/10 marker-red"
                            : "bg-marker-blue/10 marker-blue"
                      }`}
                    >
                      {selectedStep.decision}
                    </span>
                    {selectedStep.score !== undefined && (
                      <span className="text-muted-foreground">
                        score: {selectedStep.score.toFixed(3)}
                      </span>
                    )}
                    {selectedStep.tokens !== undefined && (
                      <span className="text-muted-foreground">
                        {selectedStep.tokens}t
                      </span>
                    )}
                  </div>
                  {selectedStep.reason && (
                    <p className="text-[10px] text-muted-foreground italic">
                      {selectedStep.reason}
                    </p>
                  )}
                  <div className="p-2 bg-marker-black/[0.02] rounded border border-marker-black/5">
                    <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
                      {selectedItem.content}
                    </pre>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* RIGHT PANEL: Visualization */}
          <div className="space-y-4">
            {/* Budget bars */}
            {traceA && (
              <Card className="whiteboard-card">
                <CardContent className="pt-4 space-y-4">
                  <TokenBudgetBar pack={traceA.pack} label="Budget A" />
                  {traceB && (
                    <TokenBudgetBar pack={traceB.pack} label="Budget B" />
                  )}
                </CardContent>
              </Card>
            )}

            {/* Tab navigation */}
            <div className="flex gap-1 border-b-2 border-marker-black/10">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 text-xs font-bold uppercase tracking-wider transition-all border-b-3 -mb-[2px] ${
                    activeTab === tab.id
                      ? "marker-blue border-marker-blue"
                      : "text-muted-foreground border-transparent hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </button>
              ))}

              <div className="ml-auto flex items-center">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowContent(!showContent)}
                  className="text-[10px] gap-1"
                >
                  {showContent ? (
                    <EyeOff className="w-3 h-3" />
                  ) : (
                    <Eye className="w-3 h-3" />
                  )}
                  {showContent ? "Hide" : "Show"} content
                </Button>
              </div>
            </div>

            {/* Tab content */}
            <Card className="whiteboard-card">
              <CardContent className="pt-4 max-h-[600px] overflow-y-auto">
                {activeTab === "trace" && traceA && (
                  <TraceTimeline
                    steps={traceA.steps}
                    selectedStepId={selectedStepId}
                    onStepClick={(step: TraceStep) =>
                      setSelectedStepId(
                        step.id === selectedStepId ? undefined : step.id
                      )
                    }
                  />
                )}

                {activeTab === "items" && traceA && (
                  <div className="space-y-4">
                    <div>
                      <h4 className="text-[10px] font-bold uppercase tracking-widest marker-green mb-2">
                        Selected ({traceA.pack.selected.length})
                      </h4>
                      <div className="space-y-2">
                        {traceA.pack.selected.map(item => (
                          <ItemCard
                            key={item.id}
                            item={item}
                            variant="selected"
                            showContent={showContent}
                          />
                        ))}
                      </div>
                    </div>
                    {traceA.pack.dropped.length > 0 && (
                      <div>
                        <h4 className="text-[10px] font-bold uppercase tracking-widest marker-red mb-2">
                          Dropped ({traceA.pack.dropped.length})
                        </h4>
                        <div className="space-y-2">
                          {traceA.pack.dropped.map(item => (
                            <ItemCard
                              key={item.id}
                              item={item}
                              variant="dropped"
                              showContent={showContent}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {activeTab === "diff" && packDiff && (
                  <DiffView diff={packDiff} />
                )}

                {!traceA && (
                  <div className="text-center py-12 text-muted-foreground text-sm italic">
                    Enter valid context items to begin inspecting.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
