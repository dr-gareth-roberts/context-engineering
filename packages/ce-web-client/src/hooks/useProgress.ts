import { useState, useEffect } from "react";

export interface QuizScore {
  correct: number;
  total: number;
  percentage: number;
  timestamp: string;
}

export interface ProgressData {
  completedSections: string[];
  quizScores: QuizScore[];
  lastVisit: string;
}

const STORAGE_KEY = "context-engineering-progress";

const defaultProgress: ProgressData = {
  completedSections: [],
  quizScores: [],
  lastVisit: new Date().toISOString(),
};

export function useProgress() {
  const [progress, setProgress] = useState<ProgressData>(defaultProgress);

  // Load progress from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        setProgress(parsed);
      }
    } catch (error) {
      console.error("Failed to load progress:", error);
    }
  }, []);

  // Save progress to localStorage whenever it changes
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
    } catch (error) {
      console.error("Failed to save progress:", error);
    }
  }, [progress]);

  const markSectionComplete = (sectionId: string) => {
    setProgress(prev => ({
      ...prev,
      completedSections: prev.completedSections.includes(sectionId)
        ? prev.completedSections
        : [...prev.completedSections, sectionId],
      lastVisit: new Date().toISOString(),
    }));
  };

  const isSectionComplete = (sectionId: string): boolean => {
    return progress.completedSections.includes(sectionId);
  };

  const addQuizScore = (score: Omit<QuizScore, "timestamp">) => {
    setProgress(prev => ({
      ...prev,
      quizScores: [
        ...prev.quizScores,
        { ...score, timestamp: new Date().toISOString() },
      ],
      lastVisit: new Date().toISOString(),
    }));
  };

  const getBestQuizScore = (): QuizScore | null => {
    if (progress.quizScores.length === 0) return null;
    return progress.quizScores.reduce((best, current) =>
      current.percentage > best.percentage ? current : best
    );
  };

  const getLatestQuizScore = (): QuizScore | null => {
    if (progress.quizScores.length === 0) return null;
    return progress.quizScores[progress.quizScores.length - 1];
  };

  const getCompletionPercentage = (totalSections: number): number => {
    return Math.round(
      (progress.completedSections.length / totalSections) * 100
    );
  };

  const resetProgress = () => {
    setProgress(defaultProgress);
    localStorage.removeItem(STORAGE_KEY);
  };

  return {
    progress,
    markSectionComplete,
    isSectionComplete,
    addQuizScore,
    getBestQuizScore,
    getLatestQuizScore,
    getCompletionPercentage,
    resetProgress,
  };
}
