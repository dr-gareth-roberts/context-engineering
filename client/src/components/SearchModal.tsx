import { useState, useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, X, ArrowRight, Command } from "lucide-react";

interface SearchResult {
  id: string;
  title: string;
  section: string;
  excerpt: string;
  href: string;
}

// Searchable content index
const searchableContent: SearchResult[] = [
  // Fundamentals
  {
    id: "fundamentals-1",
    title: "Context Engineering Definition",
    section: "The Fundamentals",
    excerpt:
      "The set of strategies for curating and maintaining the optimal set of tokens during LLM inference.",
    href: "#fundamentals",
  },
  {
    id: "fundamentals-2",
    title: "Attention Budget Problem",
    section: "The Fundamentals",
    excerpt:
      "Transformers compute n² relationships between tokens, making attention a finite and expensive resource. Context rot degrades recall and accuracy.",
    href: "#fundamentals",
  },
  {
    id: "fundamentals-3",
    title: "Economics of Context",
    section: "The Fundamentals",
    excerpt:
      "10x cost difference between cached ($0.30/MTok) and uncached ($3.00/MTok) tokens. Cache hit rate is your most important metric.",
    href: "#fundamentals",
  },
  // System Prompts
  {
    id: "system-1",
    title: "Goldilocks Zone",
    section: "System Prompts",
    excerpt:
      "Instructions should be specific enough to guide behaviour in expected scenarios, flexible enough to handle diverse situations.",
    href: "#system-prompts",
  },
  {
    id: "system-2",
    title: "System Prompt Structure",
    section: "System Prompts",
    excerpt:
      "Use XML tags or Markdown headers to separate concerns: background_information, instructions, tool guidance, output description.",
    href: "#system-prompts",
  },
  {
    id: "system-3",
    title: "Anti-Patterns",
    section: "System Prompts",
    excerpt:
      "Avoid dynamic timestamps at start (invalidates cache), excessive repetition (wastes tokens), contradictory instructions.",
    href: "#system-prompts",
  },
  // Tools
  {
    id: "tools-1",
    title: "Tool Design Principles",
    section: "Tool Engineering",
    excerpt:
      "Token efficiency, minimal overlap, LLM comprehension, consistent naming with prefixes like browser_*, shell_*, file_*.",
    href: "#tools",
  },
  {
    id: "tools-2",
    title: "Tool Explosion Problem",
    section: "Tool Engineering",
    excerpt:
      "Increasing tools from 10 to 100 can cause 30-40% drop in success rate. Agent selects wrong actions and takes inefficient paths.",
    href: "#tools",
  },
  {
    id: "tools-3",
    title: "Mask Don't Remove",
    section: "Tool Engineering",
    excerpt:
      "Keep all tool definitions stable, but mask token logits during decoding to constrain selection. Changing definitions invalidates KV-cache.",
    href: "#tools",
  },
  // KV-Cache
  {
    id: "kv-1",
    title: "KV-Cache Mechanism",
    section: "KV-Cache Optimisation",
    excerpt:
      "Stores precomputed key-value pairs from prefill phase. Identical prefix means cache hit, 10x cost reduction.",
    href: "#kv-cache",
  },
  {
    id: "kv-2",
    title: "Hit Rate Target",
    section: "KV-Cache Optimisation",
    excerpt:
      "Target 90%+ hit rate for 10x cost reduction, dramatically reduced TTFT, and real-time agent performance.",
    href: "#kv-cache",
  },
  {
    id: "kv-3",
    title: "Maximising Cache Hits",
    section: "KV-Cache Optimisation",
    excerpt:
      "Stable prefix, append-only context, deterministic serialisation with sorted keys, explicit cache breakpoints.",
    href: "#kv-cache",
  },
  // AGENTS.md
  {
    id: "agents-1",
    title: "AGENTS.md Standard",
    section: "AGENTS.md Standard",
    excerpt:
      "The README for AI agents. 60,000+ open source projects use this standard for tools like Cursor, Copilot, Devin, Windsurf.",
    href: "#agents-md",
  },
  {
    id: "agents-2",
    title: "Essential Sections",
    section: "AGENTS.md Standard",
    excerpt:
      "Setup commands, code style, testing instructions, PR instructions, security guidelines.",
    href: "#agents-md",
  },
  {
    id: "agents-3",
    title: "Resolution Rules",
    section: "AGENTS.md Standard",
    excerpt:
      "Proximity wins (closest file takes precedence), user prompts override file instructions, child directories inherit from parents.",
    href: "#agents-md",
  },
  // Deep Agents
  {
    id: "deep-1",
    title: "Deep Agent Architecture",
    section: "Deep Agent Architecture",
    excerpt:
      "Four pillars: Explicit Planning, Hierarchical Delegation, Persistent Memory, Extreme Context Engineering.",
    href: "#deep-agents",
  },
  {
    id: "deep-2",
    title: "Explicit Planning",
    section: "Deep Agent Architecture",
    excerpt:
      "Maintain structured plan document updated between every step. Prevents goal drift and enables recovery from failures.",
    href: "#deep-agents",
  },
  {
    id: "deep-3",
    title: "Hierarchical Delegation",
    section: "Deep Agent Architecture",
    excerpt:
      "Orchestrator decomposes tasks and assigns to specialised sub-agents. Each gets clean context, only synthesised results return.",
    href: "#deep-agents",
  },
  {
    id: "deep-4",
    title: "Persistent Memory",
    section: "Deep Agent Architecture",
    excerpt:
      "Shift from remembering everything to knowing where to find information. Use file system, vector DB, structured DB.",
    href: "#deep-agents",
  },
  // Context Management
  {
    id: "context-1",
    title: "Observation Masking",
    section: "Context Management",
    excerpt:
      "Never paste full files into context. Extract specific lines or keys. Use grep, head, jq to filter outputs.",
    href: "#context-management",
  },
  {
    id: "context-2",
    title: "LLM Summarisation",
    section: "Context Management",
    excerpt:
      "Use at milestones to compress context. Lossy compression—never summarise active code or uncommitted changes.",
    href: "#context-management",
  },
  {
    id: "context-3",
    title: "File System as Memory",
    section: "Context Management",
    excerpt:
      "Context is RAM (expensive, limited), file system is hard drive (cheap, infinite). Write large data to files, keep paths in context.",
    href: "#context-management",
  },
  // Cron Jobs
  {
    id: "cron-1",
    title: "Cron Job Lifecycle",
    section: "Cron Jobs",
    excerpt:
      "Wake up with clean context, read state from DB/files, execute deep agent, save state, sleep. Prevents context rot.",
    href: "#cron-jobs",
  },
  {
    id: "cron-2",
    title: "Idempotency",
    section: "Cron Jobs",
    excerpt:
      "Agents might run twice due to retries or scheduling overlaps. Design operations to be safe when repeated.",
    href: "#cron-jobs",
  },
  // Key Takeaways
  {
    id: "takeaway-1",
    title: "Context is the New Prompt",
    section: "Key Takeaways",
    excerpt:
      "The unit of work has shifted from single prompts to entire context lifecycles.",
    href: "#key-takeaways",
  },
  {
    id: "takeaway-2",
    title: "Treat Every Token as a Liability",
    section: "Key Takeaways",
    excerpt:
      "Maximise signal-to-noise ratio through aggressive filtering and compression.",
    href: "#key-takeaways",
  },
];

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => {
    if (!query.trim()) return [];

    const lowerQuery = query.toLowerCase();
    return searchableContent
      .filter(
        item =>
          item.title.toLowerCase().includes(lowerQuery) ||
          item.excerpt.toLowerCase().includes(lowerQuery) ||
          item.section.toLowerCase().includes(lowerQuery)
      )
      .slice(0, 8);
  }, [query]);

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
      setQuery("");
      setSelectedIndex(0);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [results]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex(i => Math.min(i + 1, results.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex(i => Math.max(i - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (results[selectedIndex]) {
            window.location.hash = results[selectedIndex].href;
            onClose();
          }
          break;
        case "Escape":
          e.preventDefault();
          onClose();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, results, selectedIndex, onClose]);

  // Scroll selected item into view
  useEffect(() => {
    if (resultsRef.current) {
      const selectedElement = resultsRef.current.children[
        selectedIndex
      ] as HTMLElement;
      if (selectedElement) {
        selectedElement.scrollIntoView({ block: "nearest" });
      }
    }
  }, [selectedIndex]);

  const highlightMatch = (text: string, query: string) => {
    if (!query.trim()) return text;

    const regex = new RegExp(
      `(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`,
      "gi"
    );
    const parts = text.split(regex);

    return parts.map((part, i) =>
      regex.test(part) ? (
        <mark key={i} className="bg-yellow-200 text-foreground rounded px-0.5">
          {part}
        </mark>
      ) : (
        part
      )
    );
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ duration: 0.15 }}
            className="fixed top-[15%] left-1/2 -translate-x-1/2 w-full max-w-2xl z-50"
          >
            <div className="bg-white rounded-xl shadow-2xl border-2 border-[#2D3436] overflow-hidden mx-4">
              {/* Search Input */}
              <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
                <Search className="w-5 h-5 text-muted-foreground shrink-0" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search techniques, concepts, patterns..."
                  className="flex-1 bg-transparent outline-none font-body text-lg placeholder:text-muted-foreground"
                />
                <button
                  onClick={onClose}
                  className="p-1 rounded hover:bg-muted transition-colors"
                >
                  <X className="w-5 h-5 text-muted-foreground" />
                </button>
              </div>

              {/* Results */}
              <div ref={resultsRef} className="max-h-[60vh] overflow-y-auto">
                {query.trim() === "" ? (
                  <div className="px-4 py-8 text-center text-muted-foreground">
                    <p className="font-body">Start typing to search...</p>
                    <p className="text-sm mt-2">
                      Try: "KV-cache", "observation masking", "AGENTS.md"
                    </p>
                  </div>
                ) : results.length === 0 ? (
                  <div className="px-4 py-8 text-center text-muted-foreground">
                    <p className="font-body">No results found for "{query}"</p>
                    <p className="text-sm mt-2">Try different keywords</p>
                  </div>
                ) : (
                  results.map((result, index) => (
                    <a
                      key={result.id}
                      href={result.href}
                      onClick={onClose}
                      className={`block px-4 py-3 border-b border-border last:border-b-0 transition-colors ${
                        index === selectedIndex ? "bg-accent" : "hover:bg-muted"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <p className="font-body font-medium text-foreground">
                            {highlightMatch(result.title, query)}
                          </p>
                          <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                            {highlightMatch(result.excerpt, query)}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-xs font-mono text-muted-foreground bg-muted px-2 py-1 rounded">
                            {result.section}
                          </span>
                          {index === selectedIndex && (
                            <ArrowRight className="w-4 h-4 text-muted-foreground" />
                          )}
                        </div>
                      </div>
                    </a>
                  ))
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-2 bg-muted/50 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-4">
                  <span className="flex items-center gap-1">
                    <kbd className="px-1.5 py-0.5 bg-white border border-border rounded text-[10px]">
                      ↑
                    </kbd>
                    <kbd className="px-1.5 py-0.5 bg-white border border-border rounded text-[10px]">
                      ↓
                    </kbd>
                    to navigate
                  </span>
                  <span className="flex items-center gap-1">
                    <kbd className="px-1.5 py-0.5 bg-white border border-border rounded text-[10px]">
                      ↵
                    </kbd>
                    to select
                  </span>
                </div>
                <span className="flex items-center gap-1">
                  <kbd className="px-1.5 py-0.5 bg-white border border-border rounded text-[10px]">
                    esc
                  </kbd>
                  to close
                </span>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// Search trigger button component
export function SearchButton({ onClick }: { onClick: () => void }) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + K to open search
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onClick();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClick]);

  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-2 bg-white border-2 border-[#2D3436] rounded-lg hover:bg-muted transition-colors group"
    >
      <Search className="w-4 h-4 text-muted-foreground" />
      <span className="font-body text-sm text-muted-foreground hidden sm:inline">
        Search...
      </span>
      <kbd className="hidden sm:flex items-center gap-0.5 px-1.5 py-0.5 bg-muted border border-border rounded text-[10px] text-muted-foreground">
        <Command className="w-3 h-3" />K
      </kbd>
    </button>
  );
}
