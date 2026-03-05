import { useState, useMemo } from "react";
import { 
  createContextManager, 
  type BeadsIssue, 
  type Turn 
} from "@context-engineering/core";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Badge } from "lucide-react";

export function CausalPlayground() {
  const [budget, setBudget] = useState(2000);
  const [activeTask, setActiveTask] = useState("task-b");
  const [beadsJson, setBeadsJson] = useState(JSON.stringify([
    { id: "root", title: "Build Auth System", status: "open" },
    { id: "task-a", title: "Debug CI/CD", status: "closed" },
    { id: "task-b", title: "Implement OAuth", status: "open" }
  ], null, 2));

  const [history, setHistory] = useState<Omit<Turn, "tokens" | "timestamp">[]>([
    { role: "user", content: "GOAL: Build secure auth system using OAuth2. NO JWT.", taskId: "root" } as any,
    { role: "assistant", content: "Debugging CI error line 42...", taskId: "task-a" } as any,
    { role: "assistant", content: "CI error fixed by updating docker.", taskId: "task-a" } as any,
    { role: "user", content: "Starting on the OAuth flow.", taskId: "task-b" } as any,
  ]);

  const [newTurn, setNewTurn] = useState({ role: "assistant" as const, content: "", taskId: "task-b" });

  const result = useMemo(() => {
    try {
      const graph = JSON.parse(beadsJson) as BeadsIssue[];
      const ctx = createContextManager({
        budget: { maxTokens: budget },
        tokenEstimator: (text) => text.length / 4, // Simple proxy for tokens
        preserveRecentTurns: 0
      });
      
      ctx.setBeadsGraph(graph);
      ctx.setActiveTask(activeTask);
      
      history.forEach(turn => ctx.addTurn(turn));
      
      return ctx.compile();
    } catch (e) {
      return null;
    }
  }, [budget, activeTask, beadsJson, history]);

  const addTurn = () => {
    if (!newTurn.content) return;
    setHistory([...history, { ...newTurn } as any]);
    setNewTurn({ ...newTurn, content: "" });
  };

  return (
    <div className="grid lg:grid-cols-2 gap-8 my-12">
      <div className="space-y-6">
        <Card className="whiteboard-card bg-card">
          <CardHeader>
            <CardTitle className="font-display text-2xl marker-black">Graph Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-2 block">BEADS Graph (JSON)</label>
              <Textarea 
                value={beadsJson} 
                onChange={(e) => setBeadsJson(e.target.value)}
                className="font-mono text-xs h-32"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-2 block">Token Budget</label>
                <Input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
              </div>
              <div>
                <label className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-2 block">Active Task ID</label>
                <Input value={activeTask} onChange={(e) => setActiveTask(e.target.value)} />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="whiteboard-card bg-card">
          <CardHeader>
            <CardTitle className="font-display text-2xl marker-black">Add Turn</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <select 
                className="bg-background border-2 border-marker-black/10 px-2 py-1 text-sm font-bold rounded-none"
                value={newTurn.taskId}
                onChange={(e) => setNewTurn({ ...newTurn, taskId: e.target.value })}
              >
                <option value="root">Root</option>
                <option value="task-a">Task A (Closed)</option>
                <option value="task-b">Task B (Active)</option>
              </select>
              <Input 
                placeholder="Message content..." 
                value={newTurn.content}
                onChange={(e) => setNewTurn({ ...newTurn, content: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && addTurn()}
              />
              <Button onClick={addTurn} className="bg-marker-blue hover:bg-marker-blue/90 text-white font-bold rounded-none">Add</Button>
            </div>
            <div className="text-[10px] text-muted-foreground italic">
              Hint: Add multiple turns to Task A to see them get pruned when the budget fills up.
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-6">
        <Card className="whiteboard-card bg-marker-black/5 border-dashed border-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="font-display text-2xl marker-black">Compiled Context Window</CardTitle>
            {result && (
              <div className="px-3 py-1 bg-highlight-yellow text-xs font-bold marker-black border border-marker-black/20">
                {Math.round(result.totalTokens)} / {budget} Tokens
              </div>
            )}
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {result?.turns.map((turn, i) => (
                <div key={i} className="bg-card p-3 border-2 border-marker-black/10 relative group">
                  <div className="absolute -top-2 -right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <div className="bg-marker-green text-[8px] text-white px-1 font-bold uppercase">Kept</div>
                  </div>
                  <div className="flex justify-between items-start mb-1">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-marker-blue">{turn.role}</span>
                    <span className="text-[10px] font-mono text-muted-foreground">Task: {turn.taskId}</span>
                  </div>
                  <p className="text-sm leading-snug">{turn.content}</p>
                </div>
              ))}
              {(!result || result.turns.length === 0) && (
                <div className="py-12 text-center text-muted-foreground italic border-2 border-dashed border-marker-black/5">
                  Context window is empty. Add turns or increase budget.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
