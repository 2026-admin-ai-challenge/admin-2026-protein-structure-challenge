// Mirrors docs/api-contract.md. Change both together.
export type Entry = {
  rank: number;
  team: string;
  score: number;
  submissions: number;
  last_submission: string;
};
export type User = {
  id: number;
  username: string;
  display_name: string;
  team_id: number;
  team_name: string;
  role: string;
};
export type SubmissionStatus = "queued" | "running" | "succeeded" | "failed";
export type Evaluator = "mock" | "docker";
export type Submission = {
  id: number;
  filename: string;
  status: SubmissionStatus;
  failure_code: string | null;
  error_message: string | null;
  public_score: number | null;
  counted: boolean;
  size_bytes: number | null;
  sha256: string | null;
  file_deleted: boolean;
  evaluator: string | null;
  queue_position: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  submitted_by?: string | null;
};
export type Quota = { used: number; limit: number; remaining: number };
export type SubmissionHistory = Quota & { entries: Submission[] };
export type AdminSubmission = Submission & {
  private_score: number | null;
  team_id: number;
  team: string;
  user: string;
  attempts: number;
  worker_id: string | null;
  file_id: number | null;
  on_leaderboard: boolean;
  log_tail?: string | null;
  file_present?: boolean;
  file_deleted_at?: string | null;
  file_deleted_by?: string | null;
  file_delete_reason?: string | null;
};
type FileRef = { file_id: number; submission_id: number; team_id: number };
export type FileCheck = {
  ok: boolean;
  checked: number;
  missing: FileRef[];
  size_mismatch: FileRef[];
  hash_mismatch: FileRef[];
  deleted_present: FileRef[];
  orphans: string[];
  stale_uploads: number;
};
export type Settings = {
  is_open: boolean;
  start_time: string | null;
  end_time: string | null;
  team_submission_limit: number;
  frozen: boolean;
  finalized: boolean;
};
export type AdminSettings = Settings & {
  count_failed: boolean;
  final_selection: "best_public" | "best_private";
};
export type Limits = {
  zip_bytes: number;
  inference_seconds: number;
  team_submissions: number;
  required_entries: string[];
};
export type Meta = {
  version?: string;
  stats?: {
    total: number;
    classes: number;
    train: number;
    test: number;
    sequence_length?: { mean: number; median: number; min: number; max: number };
    samples_per_class?: Record<string, number>;
  };
  files: Record<string, { rows?: number; columns?: string[]; bytes: number }>;
  labels: string[];
};
export type Competition = {
  title: string;
  settings: Settings;
  submission_open: boolean;
  dataset_available: boolean;
  dataset: Meta | null;
  limits: Limits;
  evaluator: Evaluator;
  teams: number;
  submissions: number;
};
export type Account = {
  id: number;
  username: string;
  display_name: string;
  role: string;
  banned: boolean;
  created_at: string;
};
export type IssuedAccount = Account & { temporary_password: string };
export type AdminTeam = {
  id: number;
  name: string;
  created_at: string;
  users: Account[];
  used: number;
  limit: number;
  submissions: number;
  best_public: number | null;
  files: number;
  storage_bytes: number;
};
export type WorkerInfo = {
  id: string;
  evaluator: string;
  ready: boolean;
  detail: string | null;
  submission_id: number | null;
  last_seen: string;
  alive: boolean;
};
export type Overview = {
  settings: AdminSettings;
  limits: Limits;
  evaluator: Evaluator;
  queue: Record<SubmissionStatus, number>;
  failures: Record<string, number>;
  oldest_queued_at: string | null;
  workers: WorkerInfo[];
};
export type DatasetFile = {
  kind: string;
  name: string;
  present: boolean;
  rows: number | null;
  bytes?: number;
  approved_sha256: string | null;
};
export type DatasetReport = {
  metadata_present: boolean;
  version: string | null;
  validation: { passed?: boolean; [key: string]: unknown } | null;
  stats: Meta["stats"] | null;
  files: DatasetFile[];
  approved: {
    version: string | null;
    at: string | null;
    by: string | null;
    locked: boolean;
  };
};
export type AuditEntry = {
  id: number;
  created_at: string;
  actor: string;
  action: string;
  target: string;
  detail: string | null;
  ok: boolean;
};
