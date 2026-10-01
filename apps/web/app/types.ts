export type Entry = {
  rank: number;
  team: string;
  score: number;
  submissions: number;
  last_submission: string;
};
export type User = {
  id: number;
  display_name: string;
  team_name: string;
  email: string;
  role: string;
};
export type Submission = {
  id: number;
  filename: string;
  public_score: number | null;
  private_score?: number;
  status: string;
  error_message?: string;
  created_at: string;
  team?: string;
  user?: string;
  previous_best?: number | null;
  remaining?: number;
};
export type Settings = {
  is_open: boolean;
  start_time: string | null;
  end_time: string | null;
  daily_limit: number;
  frozen: boolean;
  finalized: boolean;
};
export type Meta = {
  stats: {
    total: number;
    classes: number;
    train: number;
    test: number;
    sequence_length: { mean: number; median: number; min: number; max: number };
    samples_per_class: Record<string, number>;
  };
  files: Record<string, { rows?: number; columns?: string[]; bytes: number }>;
  labels: string[];
};
export type Competition = {
  dataset_available: boolean;
  settings: Settings;
  dataset: Meta | null;
  participants: number;
  submissions: number;
};
