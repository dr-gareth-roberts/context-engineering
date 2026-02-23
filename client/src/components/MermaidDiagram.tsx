import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { Maximize2, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MermaidDiagramProps {
  chart: string;
  title?: string;
  description?: string;
}

// Initialize Mermaid with custom theme
mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  themeVariables: {
    primaryColor: "#E8F4FD",
    primaryTextColor: "#2D3436",
    primaryBorderColor: "#0066CC",
    lineColor: "#0066CC",
    secondaryColor: "#FFF3CD",
    tertiaryColor: "#F8F9FA",
    fontSize: "16px",
    fontFamily: "Work Sans, sans-serif",
  },
  flowchart: {
    curve: "basis",
    padding: 20,
  },
});

export function MermaidDiagram({
  chart,
  title,
  description,
}: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [svgContent, setSvgContent] = useState<string>("");

  useEffect(() => {
    const renderDiagram = async () => {
      if (containerRef.current) {
        try {
          const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
          const { svg } = await mermaid.render(id, chart);
          setSvgContent(svg);
        } catch (error) {
          console.error("Mermaid rendering error:", error);
        }
      }
    };

    renderDiagram();
  }, [chart]);

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
  };

  return (
    <div
      className={`relative ${isFullscreen ? "fixed inset-0 z-50 bg-background p-8" : ""}`}
    >
      {title && (
        <div className="mb-4">
          <h4 className="text-xl font-display marker-blue mb-2">{title}</h4>
          {description && (
            <p className="text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      )}

      <div className="relative whiteboard-card p-6 bg-white">
        <Button
          onClick={toggleFullscreen}
          variant="outline"
          size="sm"
          className="absolute top-4 right-4 z-10 print:hidden"
          aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        >
          {isFullscreen ? (
            <Minimize2 className="w-4 h-4" />
          ) : (
            <Maximize2 className="w-4 h-4" />
          )}
        </Button>

        <div
          ref={containerRef}
          className={`mermaid-container overflow-x-auto ${isFullscreen ? "flex items-center justify-center h-full" : ""}`}
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
      </div>
    </div>
  );
}

// Pre-defined diagrams for the workshop
export const diagrams = {
  kvCacheFlow: `graph TB
    A[Request 1: System Prompt + Tools + Message] --> B[Compute KV-Cache]
    B --> C[Store in Cache]
    C --> D[Generate Response]
    
    D --> E[Request 2: Same Prefix + New Message]
    E --> F{Cache Hit?}
    
    F -->|Yes - Reuse Cache| G[Skip Computation]
    F -->|No - Cache Miss| H[Recompute Everything]
    
    G --> I[Fast Response - 10x Cheaper]
    H --> J[Slow Response - 10x Cost]
    
    style A fill:#E8F4FD,stroke:#0066CC,stroke-width:2px
    style E fill:#E8F4FD,stroke:#0066CC,stroke-width:2px
    style F fill:#FFF3CD,stroke:#F39C12,stroke-width:2px
    style G fill:#D5F5E3,stroke:#27AE60,stroke-width:2px
    style H fill:#FADBD8,stroke:#E74C3C,stroke-width:2px
    style I fill:#D5F5E3,stroke:#27AE60,stroke-width:3px
    style J fill:#FADBD8,stroke:#E74C3C,stroke-width:3px`,

  deepAgentArchitecture: `graph TB
    subgraph Planning["🎯 Explicit Planning"]
        P1[Break Down Task]
        P2[Create Phase Plan]
        P3[Track Progress]
        P1 --> P2 --> P3
    end
    
    subgraph Delegation["🌳 Hierarchical Delegation"]
        D1[Spawn Subtasks]
        D2[Parallel Execution]
        D3[Aggregate Results]
        D1 --> D2 --> D3
    end
    
    subgraph Memory["💾 Persistent Memory"]
        M1[External State Store]
        M2[File System]
        M3[Database]
        M1 --> M2
        M1 --> M3
    end
    
    subgraph Context["🔧 Extreme Context Engineering"]
        C1[Observation Masking]
        C2[KV-Cache Optimisation]
        C3[Summarisation]
        C1 --> C2 --> C3
    end
    
    Planning --> Delegation
    Delegation --> Memory
    Memory --> Context
    Context --> Planning
    
    style Planning fill:#E8F4FD,stroke:#0066CC,stroke-width:3px
    style Delegation fill:#FFF3CD,stroke:#F39C12,stroke-width:3px
    style Memory fill:#FADBD8,stroke:#E74C3C,stroke-width:3px
    style Context fill:#D5F5E3,stroke:#27AE60,stroke-width:3px`,

  contextLifecycle: `graph LR
    A[System Prompt] --> B[Tool Definitions]
    B --> C[Message History]
    C --> D[New User Message]
    
    D --> E{Context Size?}
    E -->|< 80%| F[Continue]
    E -->|> 90%| G[Summarise Old Messages]
    
    F --> H[Generate Response]
    G --> H
    
    H --> I[Append to History]
    I --> J{Task Complete?}
    
    J -->|No| C
    J -->|Yes| K[End]
    
    style A fill:#E8F4FD,stroke:#0066CC,stroke-width:2px
    style E fill:#FFF3CD,stroke:#F39C12,stroke-width:2px
    style G fill:#FADBD8,stroke:#E74C3C,stroke-width:2px
    style K fill:#D5F5E3,stroke:#27AE60,stroke-width:2px`,

  toolMaskingFlow: `graph TB
    A[All Tool Definitions] --> B[Always in Context]
    B --> C{Current Phase?}
    
    C -->|Browser Open| D[Mask: browser_*]
    C -->|File Editing| E[Mask: file_*]
    C -->|Shell Active| F[Mask: shell_*]
    C -->|Default| G[Mask: core tools only]
    
    D --> H[Logit Masking During Decoding]
    E --> H
    F --> H
    G --> H
    
    H --> I[LLM Can Only Call Allowed Tools]
    
    style A fill:#E8F4FD,stroke:#0066CC,stroke-width:2px
    style B fill:#D5F5E3,stroke:#27AE60,stroke-width:2px
    style C fill:#FFF3CD,stroke:#F39C12,stroke-width:2px
    style H fill:#FADBD8,stroke:#E74C3C,stroke-width:2px
    style I fill:#D5F5E3,stroke:#27AE60,stroke-width:3px`,

  agentsMdResolution: `graph TB
    A[Agent Starts Task] --> B{AGENTS.md Exists?}
    
    B -->|Yes| C[Read AGENTS.md]
    B -->|No| D[Use Generic Instructions]
    
    C --> E[Parse Sections]
    E --> F[Setup Commands]
    E --> G[Code Style]
    E --> H[Testing Instructions]
    E --> I[PR Guidelines]
    
    F --> J[Execute Setup]
    G --> K[Apply Style Rules]
    H --> L[Run Tests]
    I --> M[Follow PR Process]
    
    J --> N[Context-Aware Agent]
    K --> N
    L --> N
    M --> N
    
    D --> O[Generic Agent]
    
    style A fill:#E8F4FD,stroke:#0066CC,stroke-width:2px
    style B fill:#FFF3CD,stroke:#F39C12,stroke-width:2px
    style C fill:#D5F5E3,stroke:#27AE60,stroke-width:2px
    style D fill:#FADBD8,stroke:#E74C3C,stroke-width:2px
    style N fill:#D5F5E3,stroke:#27AE60,stroke-width:3px
    style O fill:#FADBD8,stroke:#E74C3C,stroke-width:2px`,
};
