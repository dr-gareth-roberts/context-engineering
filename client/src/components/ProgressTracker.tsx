import { CheckCircle2, Circle, Trophy, RotateCcw } from "lucide-react";
import { useProgress } from "@/hooks/useProgress";
import { Button } from "@/components/ui/button";

interface Section {
  id: string;
  title: string;
  category: string;
}

const workshopSections: Section[] = [
  { id: "fundamentals", title: "The Fundamentals", category: "Core Concepts" },
  { id: "paradigm-shift", title: "Paradigm Shift", category: "Core Concepts" },
  { id: "economics", title: "Economics & Physics", category: "Core Concepts" },
  { id: "system-prompts", title: "System Prompt Architecture", category: "Implementation" },
  { id: "tool-engineering", title: "Tool Engineering", category: "Implementation" },
  { id: "kv-cache", title: "KV-Cache Optimisation", category: "Implementation" },
  { id: "agents-md", title: "AGENTS.md Standard", category: "Standards" },
  { id: "deep-agents", title: "Deep Agent Architecture", category: "Advanced" },
  { id: "context-management", title: "Context Management", category: "Advanced" },
  { id: "cron-jobs", title: "Cron Jobs & Scheduling", category: "Advanced" },
  { id: "code-examples", title: "Code Examples", category: "Practice" },
  { id: "quiz", title: "Self-Assessment Quiz", category: "Practice" },
  { id: "resources", title: "Resources & References", category: "Learning" }
];

export function ProgressTracker() {
  const {
    progress,
    isSectionComplete,
    getBestQuizScore,
    getCompletionPercentage,
    resetProgress
  } = useProgress();

  const completionPercentage = getCompletionPercentage(workshopSections.length);
  const bestScore = getBestQuizScore();

  const groupedSections = workshopSections.reduce((acc, section) => {
    if (!acc[section.category]) {
      acc[section.category] = [];
    }
    acc[section.category].push(section);
    return acc;
  }, {} as Record<string, Section[]>);

  return (
    <div className="max-w-3xl mx-auto">
      <div className="whiteboard-card p-8 mb-8">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-4xl font-display marker-blue mb-2">
              Your Progress
            </h2>
            <p className="text-gray-700">
              Track your journey through the workshop
            </p>
          </div>
          <Button
            onClick={resetProgress}
            variant="outline"
            size="sm"
            className="flex items-center gap-2"
          >
            <RotateCcw className="w-4 h-4" />
            Reset
          </Button>
        </div>

        {/* Overall Progress */}
        <div className="mb-8 p-6 bg-blue-50 border-2 border-[#0066CC] rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <span className="font-semibold text-gray-900">Overall Completion</span>
            <span className="text-2xl font-display marker-blue">{completionPercentage}%</span>
          </div>
          <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#0066CC] transition-all duration-500"
              style={{ width: `${completionPercentage}%` }}
            />
          </div>
          <div className="mt-3 text-sm text-gray-600">
            {progress.completedSections.length} of {workshopSections.length} sections completed
          </div>
        </div>

        {/* Quiz Score */}
        {bestScore && (
          <div className="mb-8 p-6 bg-green-50 border-2 border-[#27AE60] rounded-lg">
            <div className="flex items-center gap-3 mb-2">
              <Trophy className="w-6 h-6 text-[#27AE60]" />
              <span className="font-semibold text-gray-900">Best Quiz Score</span>
            </div>
            <div className="text-3xl font-display marker-green">
              {bestScore.correct}/{bestScore.total} ({bestScore.percentage.toFixed(0)}%)
            </div>
            <div className="mt-2 text-sm text-gray-600">
              Completed on {new Date(bestScore.timestamp).toLocaleDateString()}
            </div>
          </div>
        )}

        {/* Section Checklist */}
        <div className="space-y-6">
          <h3 className="text-2xl font-display marker-black">Section Checklist</h3>
          
          {Object.entries(groupedSections).map(([category, sections]) => (
            <div key={category}>
              <h4 className="text-lg font-semibold text-gray-700 mb-3">{category}</h4>
              <div className="space-y-2">
                {sections.map(section => {
                  const isComplete = isSectionComplete(section.id);
                  return (
                    <div
                      key={section.id}
                      className={`flex items-center gap-3 p-3 rounded-lg border-2 transition-all ${
                        isComplete
                          ? 'border-[#27AE60] bg-green-50'
                          : 'border-gray-300 bg-white'
                      }`}
                    >
                      {isComplete ? (
                        <CheckCircle2 className="w-5 h-5 text-[#27AE60] flex-shrink-0" />
                      ) : (
                        <Circle className="w-5 h-5 text-gray-400 flex-shrink-0" />
                      )}
                      <span className={`${isComplete ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>
                        {section.title}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Completion Message */}
        {completionPercentage === 100 && (
          <div className="mt-8 p-6 bg-yellow-50 border-l-4 border-[#F39C12] rounded">
            <h4 className="font-display text-xl marker-black mb-2">
              🎉 Workshop Complete!
            </h4>
            <p className="text-sm text-gray-700">
              Congratulations! You've completed the Context Engineering Workshop. Continue practising these techniques in your own projects and stay engaged with the community to keep learning.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
