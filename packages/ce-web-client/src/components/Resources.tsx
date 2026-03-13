import {
  ExternalLink,
  FileText,
  Github,
  BookOpen,
  Users,
  Video,
} from "lucide-react";

interface Resource {
  title: string;
  description: string;
  url: string;
  type:
    | "paper"
    | "article"
    | "github"
    | "documentation"
    | "community"
    | "video";
  author?: string;
  date?: string;
}

const resources: Resource[] = [
  // Research Papers
  {
    title: "Attention Is All You Need",
    description:
      "The foundational transformer paper that introduced the attention mechanism and KV-cache concept.",
    url: "https://arxiv.org/abs/1706.03762",
    type: "paper",
    author: "Vaswani et al.",
    date: "2017",
  },
  {
    title:
      "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
    description:
      "Demonstrates how structured prompting improves reasoning capabilities.",
    url: "https://arxiv.org/abs/2201.11903",
    type: "paper",
    author: "Wei et al.",
    date: "2022",
  },
  {
    title: "ReAct: Synergizing Reasoning and Acting in Language Models",
    description:
      "Introduces the ReAct pattern for combining reasoning with tool use.",
    url: "https://arxiv.org/abs/2210.03629",
    type: "paper",
    author: "Yao et al.",
    date: "2022",
  },

  // Articles & Blog Posts
  {
    title: "Effective Context Engineering for AI Agents",
    description:
      "Anthropic's comprehensive guide to building production-ready AI agents with proper context management.",
    url: "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents",
    type: "article",
    author: "Anthropic Engineering",
    date: "2025",
  },
  {
    title: "High-Performance Context Windows: Architectural Lessons",
    description:
      "Deep dive into the architecture of production-ready AI systems with 100K+ token context management.",
    url: "#",
    type: "article",
    author: "Engineering Team",
    date: "2025",
  },
  {
    title:
      "Efficient Context Management: Observation Masking and Tool Filtering",
    description:
      "JetBrains Research on reducing context bloat in long-running agent sessions.",
    url: "https://blog.jetbrains.com/research/2025/12/efficient-context-management/",
    type: "article",
    author: "JetBrains Research",
    date: "2025",
  },
  {
    title: "Deep Agents 2.0: Architecture for Production AI Systems",
    description:
      "Detailed breakdown of the four pillars of deep agent architecture.",
    url: "https://www.philschmid.de/agents-2.0-deep-agents",
    type: "article",
    author: "Philipp Schmid",
    date: "2025",
  },

  // GitHub Repositories
  {
    title: "AGENTS.md Specification",
    description:
      "Official specification and examples for the AGENTS.md standard.",
    url: "https://github.com/agents-md/agents.md",
    type: "github",
    author: "AGENTS.md Community",
  },
  {
    title: "LangChain",
    description:
      "Framework for developing applications powered by language models with built-in agent patterns.",
    url: "https://github.com/langchain-ai/langchain",
    type: "github",
    author: "LangChain",
  },
  {
    title: "AutoGPT",
    description:
      "Experimental open-source attempt to make GPT-4 fully autonomous.",
    url: "https://github.com/Significant-Gravitas/AutoGPT",
    type: "github",
    author: "Significant Gravitas",
  },
  {
    title: "Semantic Kernel",
    description:
      "Microsoft's SDK for integrating LLMs with conventional programming languages.",
    url: "https://github.com/microsoft/semantic-kernel",
    type: "github",
    author: "Microsoft",
  },

  // Documentation
  {
    title: "Anthropic Claude Documentation",
    description:
      "Official documentation for Claude API, including best practices for context management.",
    url: "https://docs.anthropic.com/",
    type: "documentation",
    author: "Anthropic",
  },
  {
    title: "OpenAI Function Calling Guide",
    description:
      "Comprehensive guide to using function calling (tool use) with GPT models.",
    url: "https://platform.openai.com/docs/guides/function-calling",
    type: "documentation",
    author: "OpenAI",
  },
  {
    title: "Prompt Engineering Guide",
    description:
      "Community-maintained guide covering all aspects of prompt engineering.",
    url: "https://www.promptingguide.ai/",
    type: "documentation",
    author: "DAIR.AI",
  },

  // Community & Forums
  {
    title: "r/LocalLLaMA",
    description:
      "Reddit community focused on running and optimising LLMs, including context management discussions.",
    url: "https://www.reddit.com/r/LocalLLaMA/",
    type: "community",
    author: "Reddit Community",
  },
  {
    title: "LangChain Discord",
    description:
      "Active community discussing agent patterns, context engineering, and LLM applications.",
    url: "https://discord.gg/langchain",
    type: "community",
    author: "LangChain Community",
  },
  {
    title: "AI Engineer World's Fair",
    description:
      "Annual conference focused on practical AI engineering, including agent systems.",
    url: "https://www.ai.engineer/",
    type: "community",
    author: "Swyx & Team",
  },
];

const iconMap = {
  paper: FileText,
  article: BookOpen,
  github: Github,
  documentation: FileText,
  community: Users,
  video: Video,
};

const colorMap = {
  paper: "marker-blue",
  article: "marker-green",
  github: "marker-black",
  documentation: "marker-blue",
  community: "marker-red",
  video: "marker-green",
};

export function Resources() {
  const groupedResources = resources.reduce(
    (acc, resource) => {
      if (!acc[resource.type]) {
        acc[resource.type] = [];
      }
      acc[resource.type].push(resource);
      return acc;
    },
    {} as Record<string, Resource[]>
  );

  const categoryTitles = {
    paper: "Research Papers",
    article: "Articles & Blog Posts",
    github: "GitHub Repositories",
    documentation: "Official Documentation",
    community: "Community & Forums",
    video: "Video Resources",
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="whiteboard-card p-8 mb-8">
        <h2 className="text-4xl font-display marker-blue mb-4">
          Resources & References
        </h2>
        <p className="text-gray-700 mb-6">
          A curated collection of research papers, articles, tools, and
          community resources to deepen your understanding of context
          engineering.
        </p>

        <div className="space-y-10">
          {Object.entries(groupedResources).map(([type, items]) => {
            const Icon = iconMap[type as keyof typeof iconMap];
            const color = colorMap[type as keyof typeof colorMap];

            return (
              <div key={type}>
                <div className="flex items-center gap-3 mb-4">
                  <Icon className={`w-6 h-6 ${color}`} />
                  <h3 className={`text-2xl font-display ${color}`}>
                    {categoryTitles[type as keyof typeof categoryTitles]}
                  </h3>
                </div>

                <div className="space-y-4">
                  {items.map((resource, index) => (
                    <a
                      key={index}
                      href={resource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block p-4 border-2 border-gray-300 rounded-lg hover:border-[#0066CC] hover:bg-blue-50/50 transition-all group"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <h4 className="font-semibold text-gray-900 group-hover:text-[#0066CC] transition-colors">
                              {resource.title}
                            </h4>
                            <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-[#0066CC] transition-colors" />
                          </div>
                          <p className="text-sm text-gray-600 mb-2">
                            {resource.description}
                          </p>
                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            {resource.author && <span>{resource.author}</span>}
                            {resource.date && <span>• {resource.date}</span>}
                          </div>
                        </div>
                      </div>
                    </a>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-10 p-6 bg-yellow-50 border-l-4 border-[#F39C12] rounded">
          <h4 className="font-display text-xl marker-black mb-2">
            Contributing
          </h4>
          <p className="text-sm text-gray-700">
            Know of a valuable resource that should be included? The context
            engineering community thrives on shared knowledge. Consider
            contributing to the AGENTS.md specification or sharing your
            learnings through blog posts and open-source projects.
          </p>
        </div>
      </div>
    </div>
  );
}
