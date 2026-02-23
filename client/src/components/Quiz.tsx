import { useState } from "react";
import { Check, X, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface QuizQuestion {
  id: number;
  question: string;
  options: string[];
  correctAnswer: number;
  explanation: string;
  category: string;
}

const quizQuestions: QuizQuestion[] = [
  {
    id: 1,
    question: "What is the primary goal of context engineering?",
    options: [
      "Writing better prompts",
      "Curating and maintaining optimal token sets during inference",
      "Reducing API costs",
      "Improving model training",
    ],
    correctAnswer: 1,
    explanation:
      "Context engineering focuses on curating and maintaining the optimal set of tokens presented to the model during inference, going beyond simple prompt writing to manage the entire context lifecycle.",
    category: "Fundamentals",
  },
  {
    id: 2,
    question:
      "What is the approximate cost multiplier of a KV-cache miss compared to a cache hit?",
    options: ["2x", "5x", "10x", "20x"],
    correctAnswer: 2,
    explanation:
      "A KV-cache miss can cost approximately 10x more than a cache hit due to the need to recompute all previous token representations, making cache optimisation critical for production systems.",
    category: "KV-Cache",
  },
  {
    id: 3,
    question: "Which technique is NOT recommended for managing tool explosion?",
    options: [
      "Dynamic tool loading based on context",
      "Tool masking with logit manipulation",
      "Removing tool definitions from context entirely",
      "Hierarchical tool categorisation",
    ],
    correctAnswer: 2,
    explanation:
      "Removing tool definitions breaks KV-cache stability. Instead, keep all definitions constant and use masking or dynamic loading to control which tools are available in different contexts.",
    category: "Tool Engineering",
  },
  {
    id: 4,
    question: "What are the four pillars of Deep Agent architecture?",
    options: [
      "Planning, Execution, Memory, Feedback",
      "Explicit Planning, Hierarchical Delegation, Persistent Memory, Extreme Context Engineering",
      "Context, Tools, Memory, Reasoning",
      "Input, Processing, Output, Storage",
    ],
    correctAnswer: 1,
    explanation:
      "Deep Agents are built on four pillars: Explicit Planning (structured task decomposition), Hierarchical Delegation (spawning subtasks), Persistent Memory (external state), and Extreme Context Engineering (managing 100K+ tokens).",
    category: "Deep Agents",
  },
  {
    id: 5,
    question: "What is observation masking?",
    options: [
      "Hiding tool outputs from the user",
      "Compressing tool outputs to reduce context consumption",
      "Preventing the agent from seeing certain tools",
      "Encrypting sensitive data in observations",
    ],
    correctAnswer: 1,
    explanation:
      "Observation masking is the practice of compressing or filtering tool outputs before adding them to context, preserving signal whilst reducing token consumption. This is critical for long-running agents.",
    category: "Context Management",
  },
  {
    id: 6,
    question:
      "Which of these is a valid strategy for maximising KV-cache hit rates?",
    options: [
      "Randomising message order for variety",
      "Frequently modifying the system prompt",
      "Using append-only message history",
      "Inserting timestamps in every message",
    ],
    correctAnswer: 2,
    explanation:
      "Append-only message history ensures that the prefix of the context remains stable across requests, maximising cache reuse. Never modify or reorder existing messages.",
    category: "KV-Cache",
  },
  {
    id: 7,
    question: "What is the purpose of AGENTS.md?",
    options: [
      "To document API endpoints",
      "To provide project-specific context and instructions for AI agents",
      "To store agent conversation history",
      "To define agent personality traits",
    ],
    correctAnswer: 1,
    explanation:
      "AGENTS.md is a standardised file that provides project-specific context, setup commands, coding conventions, and instructions to AI agents, enabling them to work effectively in your codebase.",
    category: "AGENTS.md",
  },
  {
    id: 8,
    question: "When should you use context summarisation?",
    options: [
      "After every 10 messages",
      "Only when approaching the context window limit",
      "Never, it always loses critical information",
      "At the start of every session",
    ],
    correctAnswer: 1,
    explanation:
      "Context summarisation should be used strategically when approaching the context window limit (typically 80-90% full). It's lossy compression, so preserve recent context and critical data structures.",
    category: "Context Management",
  },
  {
    id: 9,
    question: "What is the 'Goldilocks Zone' for system prompts?",
    options: [
      "Between 500-1000 tokens",
      "The optimal balance between specificity and flexibility",
      "Exactly 2048 tokens",
      "As short as possible",
    ],
    correctAnswer: 1,
    explanation:
      "The Goldilocks Zone refers to finding the right balance: specific enough to guide behaviour consistently, but flexible enough to handle edge cases without constant updates.",
    category: "System Prompts",
  },
  {
    id: 10,
    question: "Which pattern is essential for cron job agents?",
    options: [
      "Maintaining conversation state across runs",
      "Starting each run with fresh context and external state persistence",
      "Using the same context window indefinitely",
      "Avoiding any state storage",
    ],
    correctAnswer: 1,
    explanation:
      "Cron job agents should start each run with fresh context to avoid token accumulation, but persist state externally (database, file system) to maintain continuity across scheduled executions.",
    category: "Cron Jobs",
  },
];

interface QuizProps {
  onComplete?: (score: {
    correct: number;
    total: number;
    percentage: number;
  }) => void;
}

export function Quiz({ onComplete }: QuizProps = {}) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [showResults, setShowResults] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState(0);

  const handleAnswer = (questionId: number, answerIndex: number) => {
    setAnswers(prev => ({ ...prev, [questionId]: answerIndex }));
  };

  const handleSubmit = () => {
    setShowResults(true);
    const score = calculateScore();
    if (onComplete) {
      onComplete(score);
    }
  };

  const handleReset = () => {
    setAnswers({});
    setShowResults(false);
    setCurrentQuestion(0);
  };

  const calculateScore = () => {
    let correct = 0;
    quizQuestions.forEach(q => {
      if (answers[q.id] === q.correctAnswer) {
        correct++;
      }
    });
    return {
      correct,
      total: quizQuestions.length,
      percentage: (correct / quizQuestions.length) * 100,
    };
  };

  const score = showResults ? calculateScore() : null;

  return (
    <div className="max-w-3xl mx-auto">
      <div className="whiteboard-card p-8 mb-8">
        <h2 className="text-4xl font-display marker-blue mb-4">
          Self-Assessment Quiz
        </h2>
        <p className="text-gray-700 mb-6">
          Test your understanding of context engineering concepts. Select the
          best answer for each question.
        </p>

        {showResults && score && (
          <div
            className={`p-6 rounded-lg mb-6 ${
              score.percentage >= 80
                ? "bg-green-50 border-2 border-green-500"
                : score.percentage >= 60
                  ? "bg-yellow-50 border-2 border-yellow-500"
                  : "bg-red-50 border-2 border-red-500"
            }`}
          >
            <h3 className="text-2xl font-display mb-2">
              Your Score: {score.correct}/{score.total} (
              {score.percentage.toFixed(0)}%)
            </h3>
            <p className="text-gray-700">
              {score.percentage >= 80 &&
                "Excellent! You have a strong grasp of context engineering principles."}
              {score.percentage >= 60 &&
                score.percentage < 80 &&
                "Good work! Review the explanations below to strengthen your understanding."}
              {score.percentage < 60 &&
                "Keep learning! Review the workshop content and explanations to improve your knowledge."}
            </p>
            <Button onClick={handleReset} className="mt-4" variant="outline">
              <RefreshCw className="w-4 h-4 mr-2" />
              Retake Quiz
            </Button>
          </div>
        )}

        <div className="space-y-8">
          {quizQuestions.map((q, index) => (
            <div key={q.id} className="border-l-4 border-[#0066CC] pl-6 py-4">
              <div className="flex items-start gap-3 mb-4">
                <span className="flex-shrink-0 w-8 h-8 rounded-full bg-[#0066CC] text-white flex items-center justify-center font-bold text-sm">
                  {index + 1}
                </span>
                <div className="flex-1">
                  <p className="text-sm text-gray-600 mb-1">{q.category}</p>
                  <p className="text-lg font-semibold text-gray-900">
                    {q.question}
                  </p>
                </div>
              </div>

              <div className="space-y-3 ml-11">
                {q.options.map((option, optionIndex) => {
                  const isSelected = answers[q.id] === optionIndex;
                  const isCorrect = optionIndex === q.correctAnswer;
                  const showCorrectness = showResults && isSelected;

                  return (
                    <button
                      key={optionIndex}
                      onClick={() =>
                        !showResults && handleAnswer(q.id, optionIndex)
                      }
                      disabled={showResults}
                      className={`w-full text-left p-4 rounded-lg border-2 transition-all ${
                        showResults && isCorrect
                          ? "border-green-500 bg-green-50"
                          : showResults && isSelected && !isCorrect
                            ? "border-red-500 bg-red-50"
                            : isSelected
                              ? "border-[#0066CC] bg-blue-50"
                              : "border-gray-300 hover:border-gray-400 bg-white"
                      } ${showResults ? "cursor-default" : "cursor-pointer"}`}
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={`${isSelected ? "font-semibold" : ""}`}
                        >
                          {option}
                        </span>
                        {showResults && isCorrect && (
                          <Check className="w-5 h-5 text-green-600 flex-shrink-0" />
                        )}
                        {showResults && isSelected && !isCorrect && (
                          <X className="w-5 h-5 text-red-600 flex-shrink-0" />
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>

              {showResults && (
                <div className="ml-11 mt-4 p-4 bg-blue-50 rounded-lg border-l-4 border-[#0066CC]">
                  <p className="text-sm font-semibold text-gray-900 mb-2">
                    Explanation:
                  </p>
                  <p className="text-sm text-gray-700">{q.explanation}</p>
                </div>
              )}
            </div>
          ))}
        </div>

        {!showResults &&
          Object.keys(answers).length === quizQuestions.length && (
            <div className="mt-8 text-center">
              <Button onClick={handleSubmit} size="lg" className="px-8">
                Submit Quiz
              </Button>
            </div>
          )}
      </div>
    </div>
  );
}
