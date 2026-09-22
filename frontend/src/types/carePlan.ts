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

export type ItemStatus = 'to_do' | 'done';

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
  why?: string | null;
  dosage?: string;
  frequency?: string;
  timing?: string;
  duration?: string;
  instructions?: string;
  side_effects_to_watch?: string;
  change: string;          // "" means nothing to report; non-empty is a plain-language change note
  status: ItemStatus;
}

export interface Test {
  title: string;
  plain_name?: string;
  why?: string | null;
  description: string;
  preparation?: string;
  status: ItemStatus;
}

export interface Procedure {
  title: string;
  plain_name?: string;
  why?: string | null;
  what_to_expect?: string;
  timeframe?: string;
  status: ItemStatus;
}

export interface OtherInstruction {
  title: string;
  why?: string | null;
  steps?: string[];
  description?: string;
  frequency?: string;
  duration?: string;
  status: ItemStatus;
}

export interface FollowUp {
  time_frame: string;
  description: string;
  status: ItemStatus;
}

export interface WarningSign {
  symptom: string;
  what_it_might_mean?: string;
  what_to_do: string;
  urgency: 'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect' | null;
  related_to?: string;
}

export interface CarePlanContent {
  summary: string;
  summary_fact_ids: number[];   // internal provenance; never rendered (brief §3.10 — the ledger is not shown to the patient)
  reason_for_visit: Array<{ reason: string; description: string }>;
  diagnosis: {
    changed_since_last_visit?: string;
    details: DiagnosisDetail[];
  };
  medications: Medication[];
  tests: Test[];
  procedures: Procedure[];
  other: OtherInstruction[];
  follow_up: FollowUp[];
  warning_signs: WarningSign[];
  questions: string[];
  low_priority: string[];
  terms?: TermsMap;
}
