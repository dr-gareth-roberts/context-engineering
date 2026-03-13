import { useState, useEffect, useRef } from "react";
import { Check, Copy } from "lucide-react";
import hljs from "highlight.js/lib/core";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import yaml from "highlight.js/lib/languages/yaml";
import bash from "highlight.js/lib/languages/bash";
import "highlight.js/styles/github-dark.css";

// Register languages
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("bash", bash);

interface CodeBlockProps {
  code: string;
  language?: string;
  title?: string;
  showLineNumbers?: boolean;
}

export function CodeBlock({
  code,
  language = "text",
  title,
  showLineNumbers = false,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (codeRef.current && language !== "text") {
      hljs.highlightElement(codeRef.current);
    }
  }, [code, language]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lines = code.split("\n");

  return (
    <div className="relative group rounded-lg overflow-hidden border-2 border-marker-black bg-[#FDFDFD] my-4 shadow-[4px_4px_0_0_rgba(45,52,54,0.1)]">
      {title && (
        <div className="flex items-center justify-between px-4 py-2 bg-white border-b-2 border-marker-black/10">
          <span className="text-sm font-mono marker-black">{title}</span>
          <span className="text-xs font-mono text-muted-foreground uppercase">
            {language}
          </span>
        </div>
      )}
      <div className="relative">
        <button
          onClick={handleCopy}
          className="absolute top-3 right-3 p-2 rounded-md bg-white border border-marker-black/20 hover:bg-gray-50 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100 z-10"
          aria-label="Copy code"
        >
          {copied ? (
            <Check className="w-4 h-4 text-green-600" />
          ) : (
            <Copy className="w-4 h-4 marker-black/60" />
          )}
        </button>
        <pre className="p-4 overflow-x-auto text-sm bg-transparent">
          <code ref={codeRef} className={`language-${language} text-slate-900`}>
            {showLineNumbers
              ? lines.map((line, i) => (
                  <div key={i} className="flex">
                    <span className="select-none text-muted-foreground/40 w-8 text-right mr-4 shrink-0 font-mono">
                      {i + 1}
                    </span>
                    <span>{line}</span>
                  </div>
                ))
              : code}
          </code>
        </pre>
      </div>
      {copied && (
        <div className="absolute bottom-3 right-3 px-2 py-1 bg-marker-green text-white text-xs rounded animate-fade-in shadow-sm">
          Copied!
        </div>
      )}
    </div>
  );
}

// Pre-defined code examples for the workshop
export const codeExamples = {
  agentsMdTemplate: `# AGENTS.md

## Project Overview
This is a TypeScript monorepo using pnpm workspaces.

## Setup Commands
\`\`\`bash
pnpm install
pnpm dev
\`\`\`

## Code Style
- TypeScript strict mode enabled
- No semicolons (Prettier configured)
- Use functional components with hooks
- Prefer named exports over default exports

## Testing Instructions
\`\`\`bash
pnpm test:unit        # Run unit tests
pnpm test:e2e         # Run end-to-end tests
pnpm test:coverage    # Generate coverage report
\`\`\`
Target coverage: 80% for all new code.

## PR Instructions
- Use conventional commits (feat:, fix:, docs:, etc.)
- Ensure all tests pass before requesting review
- Include screenshots for UI changes

## Security
- NEVER commit API keys or secrets
- Use environment variables for sensitive data
- All user input must be validated`,

  observationMasking: `# Observation Masking Implementation (Python)

def mask_observation(raw_output: str, max_tokens: int = 500) -> str:
    """
    Compress tool output to preserve signal while reducing tokens.
    
    Strategies:
    1. Extract only relevant fields from JSON
    2. Truncate with meaningful boundaries
    3. Summarise verbose content
    """
    import json
    
    # Strategy 1: JSON field extraction
    try:
        data = json.loads(raw_output)
        if isinstance(data, dict):
            # Keep only essential fields
            essential_keys = ['id', 'status', 'result', 'error', 'message']
            filtered = {k: v for k, v in data.items() if k in essential_keys}
            return json.dumps(filtered, indent=2)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Line-based truncation
    lines = raw_output.split('\\n')
    if len(lines) > 20:
        # Keep first 10 and last 5 lines
        truncated = lines[:10] + ['... [truncated] ...'] + lines[-5:]
        return '\\n'.join(truncated)
    
    # Strategy 3: Character limit with word boundary
    if len(raw_output) > max_tokens * 4:  # ~4 chars per token
        cutoff = raw_output[:max_tokens * 4].rfind(' ')
        return raw_output[:cutoff] + '... [truncated]'
    
    return raw_output`,

  kvCacheOptimisation: `# KV-Cache Optimisation Patterns

## 1. Stable System Prompt Structure
system_prompt = """
<identity>
You are a helpful coding assistant.
</identity>

<instructions>
- Write clean, maintainable code
- Follow best practices for the language
- Include error handling
</instructions>

<tools>
{tool_definitions}  # Static, never changes
</tools>
"""

## 2. Append-Only Message History
class ConversationManager:
    def __init__(self):
        self.messages = []
        self._cache_breakpoint = 0
    
    def add_message(self, role: str, content: str):
        # NEVER modify existing messages
        self.messages.append({
            "role": role,
            "content": content
        })
    
    def get_context(self):
        # Return messages in stable order
        return self.messages.copy()
    
    def mark_cache_breakpoint(self):
        # Mark current position for cache retention
        self._cache_breakpoint = len(self.messages)

## 3. Deterministic JSON Serialisation
import json

def serialise_tools(tools: list) -> str:
    # Always use sorted keys for consistent ordering
    return json.dumps(tools, sort_keys=True, separators=(',', ':'))`,

  deepAgentPlanning: `# Deep Agent Planning Pattern

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class PhaseStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Phase:
    id: int
    title: str
    description: str
    status: PhaseStatus = PhaseStatus.PENDING
    result: Optional[str] = None

@dataclass
class TaskPlan:
    goal: str
    phases: List[Phase]
    current_phase_id: int = 1
    
    def to_context(self) -> str:
        """Generate context-friendly plan representation."""
        lines = [f"# Task Plan", f"Goal: {self.goal}", "", "## Phases"]
        
        for phase in self.phases:
            status_icon = {
                PhaseStatus.PENDING: "⬜",
                PhaseStatus.IN_PROGRESS: "🔄",
                PhaseStatus.COMPLETED: "✅",
                PhaseStatus.FAILED: "❌"
            }[phase.status]
            
            current = " ← CURRENT" if phase.id == self.current_phase_id else ""
            lines.append(f"{status_icon} {phase.id}. {phase.title}{current}")
            
            if phase.result:
                lines.append(f"   Result: {phase.result[:100]}...")
        
        return "\\n".join(lines)
    
    def advance(self):
        """Move to the next phase."""
        current = self.get_current_phase()
        if current:
            current.status = PhaseStatus.COMPLETED
            self.current_phase_id += 1
            next_phase = self.get_current_phase()
            if next_phase:
                next_phase.status = PhaseStatus.IN_PROGRESS`,

  toolMasking: `# Tool Masking Implementation

from typing import List, Set, Callable
from dataclasses import dataclass

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    category: str  # e.g., "browser", "file", "shell"

class ToolManager:
    def __init__(self, all_tools: List[Tool]):
        self.all_tools = all_tools
        self._active_categories: Set[str] = set()
    
    def get_tool_definitions(self) -> List[dict]:
        """
        Return ALL tool definitions (for stable KV-cache).
        The definitions never change during a session.
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters
            }
            for t in self.all_tools
        ]
    
    def get_allowed_tools(self, context: dict) -> List[str]:
        """
        Return list of tool names allowed in current state.
        Used for logit masking during decoding.
        """
        allowed = []
        
        # Context-aware tool filtering
        if context.get("browser_open"):
            allowed.extend(self._get_tools_by_category("browser"))
        
        if context.get("file_editing"):
            allowed.extend(self._get_tools_by_category("file"))
        
        # Always allow core tools
        allowed.extend(self._get_tools_by_category("core"))
        
        return allowed
    
    def _get_tools_by_category(self, category: str) -> List[str]:
        return [t.name for t in self.all_tools if t.category == category]

# Usage with function calling
def call_llm_with_masking(messages, tool_manager, context):
    response = llm.chat(
        messages=messages,
        tools=tool_manager.get_tool_definitions(),  # Always stable
        tool_choice={
            "type": "required",
            "allowed": tool_manager.get_allowed_tools(context)  # Dynamic masking
        }
    )
    return response`,

  cronJobPattern: `# Cron Job Agent Pattern

import asyncio
from datetime import datetime
from typing import Optional
import json

class ScheduledAgent:
    """
    Agent designed for scheduled execution.
    Each run starts with fresh context but persists state externally.
    """
    
    def __init__(self, agent_id: str, state_store: "StateStore"):
        self.agent_id = agent_id
        self.state_store = state_store
    
    async def run(self, task_prompt: str) -> dict:
        """
        Execute a scheduled task with proper state management.
        """
        run_id = f"{self.agent_id}_{datetime.now().isoformat()}"
        
        # 1. Wake up with clean context
        context = self._build_fresh_context(task_prompt)
        
        # 2. Load persisted state
        previous_state = await self.state_store.load(self.agent_id)
        if previous_state:
            context["previous_run"] = previous_state.get("summary")
            context["accumulated_data"] = previous_state.get("data", [])
        
        # 3. Execute the agent loop
        try:
            result = await self._execute_agent_loop(context)
            
            # 4. Persist state for next run
            await self.state_store.save(self.agent_id, {
                "last_run": run_id,
                "summary": result.get("summary"),
                "data": result.get("accumulated_data", []),
                "status": "success"
            })
            
            return {"status": "success", "result": result}
            
        except Exception as e:
            # Persist failure state
            await self.state_store.save(self.agent_id, {
                "last_run": run_id,
                "status": "failed",
                "error": str(e)
            })
            raise
    
    def _build_fresh_context(self, task_prompt: str) -> dict:
        """Build a clean context for this run."""
        return {
            "system_prompt": self._get_system_prompt(),
            "task": task_prompt,
            "timestamp": datetime.now().isoformat(),
            "run_number": 1  # Will be updated from state
        }
    
    async def _execute_agent_loop(self, context: dict) -> dict:
        # Implementation of the agent loop
        pass

# Idempotency decorator for safe retries
def idempotent(func):
    """Ensure operation is safe to retry."""
    async def wrapper(*args, **kwargs):
        # Check if operation was already completed
        operation_id = kwargs.get('operation_id')
        if operation_id and await check_completed(operation_id):
            return await get_cached_result(operation_id)
        
        result = await func(*args, **kwargs)
        
        if operation_id:
            await cache_result(operation_id, result)
        
        return result
    return wrapper`,

  contextSummarisation: `# Context Summarisation Strategy

from typing import List, Dict
import tiktoken

class ContextManager:
    """
    Manages context window with intelligent summarisation.
    """
    
    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.warning_threshold = 0.8  # 80% triggers warning
        self.summarisation_threshold = 0.9  # 90% triggers summarisation
        self.encoder = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, messages: List[Dict]) -> int:
        """Count tokens in message list."""
        total = 0
        for msg in messages:
            total += len(self.encoder.encode(msg.get("content", "")))
        return total
    
    def should_summarise(self, messages: List[Dict]) -> bool:
        """Check if context needs summarisation."""
        current = self.count_tokens(messages)
        return current > self.max_tokens * self.summarisation_threshold
    
    def summarise_context(
        self, 
        messages: List[Dict],
        preserve_recent: int = 10
    ) -> List[Dict]:
        """
        Summarise older messages while preserving recent context.
        
        WARNING: This is lossy compression. Never summarise:
        - Active code being edited
        - Critical data structures
        - Uncommitted changes
        """
        if len(messages) <= preserve_recent:
            return messages
        
        # Split into old (to summarise) and recent (to preserve)
        old_messages = messages[:-preserve_recent]
        recent_messages = messages[-preserve_recent:]
        
        # Generate summary of old messages
        summary = self._generate_summary(old_messages)
        
        # Create new context with summary + recent
        summarised_context = [
            {
                "role": "system",
                "content": f"[Previous context summary]\\n{summary}"
            }
        ] + recent_messages
        
        return summarised_context
    
    def _generate_summary(self, messages: List[Dict]) -> str:
        """
        Generate a summary of messages.
        In production, use an LLM for this.
        """
        # Extract key information
        actions_taken = []
        results_obtained = []
        
        for msg in messages:
            content = msg.get("content", "")
            if "completed" in content.lower():
                actions_taken.append(content[:100])
            if "result" in content.lower():
                results_obtained.append(content[:100])
        
        summary_parts = []
        if actions_taken:
            summary_parts.append(f"Actions: {len(actions_taken)} completed")
        if results_obtained:
            summary_parts.append(f"Results: {len(results_obtained)} obtained")
        
        return " | ".join(summary_parts) if summary_parts else "No significant events"`,
};
