// TypeScript types mirroring the backend output envelope models.

import type { CarePlanContent } from './carePlan';

export interface GradingEntry {
  name: string;
  target: 'before' | 'after';
  grade: number;
  grade_breakdown: Record<string, unknown> | null;
  reasoning: string | null;
}

export interface Grading {
  entries: GradingEntry[];
  enabled: boolean;
  graded_at: string | null;
}

export interface Metrics {
  session_id: string;
  pipeline_version: string;  // "v1" | "v1-1" | "v1-2"
  input_type: string;        // "file" | "text"
  created_at: string;        // ISO8601
  total_duration_ms: number | null;
  step_durations_ms: Record<string, number>;
}

// SimplifiedCarePlan is the CarePlanContent shape returned by the pipeline.
export type SimplifiedCarePlan = CarePlanContent;

export interface CarePlanInternal {
  metrics: Metrics;
  grading: Grading;
  care_plan: SimplifiedCarePlan;
}
