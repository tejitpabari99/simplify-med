export type StepStatus = 'waiting' | 'active' | 'done';
export type AppState = 'upload' | 'processing' | 'result';

export interface PipelineStep {
  id: number;
  label: string;
  description: string;
  status: StepStatus;
}

export interface GlossaryTerm {
  definition: string;
  source: string;
  imgUrl?: string | null;
  altText?: string | null;
}

export type TermsMap = Record<string, GlossaryTerm>;

export interface DiagnosisDetail {
  title: string;
  plain_name?: string;
  description: string;
  what_it_means_for_you?: string;
  severity?: 'high' | 'medium' | 'low';
}

export interface Medication {
  title: string;
  plain_name?: string;
  why?: string;
  dosage?: string;
  frequency?: string;
  timing?: string;
  duration?: string;
  instructions?: string;
  side_effects_to_watch?: string;
  change?: boolean;
  change_description?: string;
}

export interface WarningSign {
  symptom: string;
  what_it_might_mean?: string;
  what_to_do: string;
  urgency: 'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect';
}

export interface CarePlanContent {
  summary: string;
  reason_for_visit: Array<{ reason: string; description: string }>;
  diagnosis: {
    main_conclusion?: string;
    changed_since_last_visit?: string;
    details: DiagnosisDetail[];
  };
  medications: Medication[];
  tests: Array<{ title: string; plain_name?: string; why?: string; description: string; preparation?: string }>;
  procedures: Array<{ title: string; plain_name?: string; why?: string; what_to_expect?: string; timeframe?: string }>;
  other: Array<{ title: string; why?: string; steps?: string[]; description?: string; frequency?: string; duration?: string }>;
  follow_up: Array<{ time_frame: string; description: string }>;
  warning_signs: WarningSign[];
  questions: string[];
  low_priority: string[];
  terms?: TermsMap;
  additional_info?: string[];
}
