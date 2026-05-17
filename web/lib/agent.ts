const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:8080";

export interface UserConfig {
  name: string;
  disciplines: string[];
  org_type: string;
  location_pref: string;
  geographic_focus: string[];
  keywords: string[];
  summary: string;
  constraints: string;
  project_description: string;
  past_grants: string;
  budget_min: number;
  deadline_window_days: number;
  scoring_weights: Record<string, string>;
  recipient_email: string;
}

export interface ParsedProfile {
  name: string;
  disciplines: string[];
  org_type: string;
  location_pref: string;
  summary: string;
  constraints: string;
  project_description: string;
  keywords: string[];
}

export interface OnboardingData {
  name: string;
  disciplines: string[];
  org_type: string;
  location_pref: string;
  geographic_focus: string[];
  keywords: string[];
  summary: string;
  constraints: string;
  recipient_email: string;
  project_description?: string;
  past_grants?: string;
  budget_min?: number;
  deadline_window_days?: number;
  scoring_weights?: Record<string, string>;
  interview_answers?: string;
}

export interface Grant {
  id: number;
  title: string;
  funder: string;
  award_amount?: string;
  deadline?: string;
  decision: "PRIORITY" | "REVIEW" | "SKIP";
  score: number;
  url?: string;
  disciplines?: string[];
  eligibility?: string;
}

export interface RunWithGrants {
  id: number;
  run_at: string;
  grants_fetched: number;
  grants_priority: number;
  grants_review: number;
  grants_skip: number;
  estimated_cost: number;
  grants: Grant[];
}

export interface Draft {
  id: number;
  grant_id?: number;
  doc_type: "loi" | "artist_statement";
  content: string;
  grant_title?: string;
  funder?: string;
  created_at: string;
}

export interface DraftResult {
  id: number;
  doc_type: "loi" | "artist_statement";
  content: string;
  valid: boolean;
  issues: string[];
  grant_title?: string;
  funder?: string;
}

export async function getRuns(token: string): Promise<RunWithGrants[]> {
  const res = await fetch(`${AGENT_URL}/runs`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Agent error: ${res.status}`);
  return res.json();
}

export async function getConfig(token: string): Promise<UserConfig | null> {
  const res = await fetch(`${AGENT_URL}/config`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Agent error: ${res.status}`);
  return res.json();
}

export async function parseResume(token: string, file: File, interviewAnswers = ""): Promise<ParsedProfile> {
  const form = new FormData();
  form.append("file", file);
  if (interviewAnswers) form.append("interview_answers", interviewAnswers);
  const res = await fetch(`${AGENT_URL}/parse-resume`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Agent error: ${res.status}`);
  }
  return res.json();
}

export async function submitOnboarding(token: string, data: OnboardingData): Promise<void> {
  const res = await fetch(`${AGENT_URL}/onboard`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Agent error: ${res.status}`);
  }
}

export async function triggerRun(token: string): Promise<void> {
  const res = await fetch(`${AGENT_URL}/run-agent`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Agent error: ${res.status}`);
  }
}

export async function draftDocument(
  token: string,
  docType: "loi" | "artist_statement",
  grantId?: number,
): Promise<DraftResult> {
  const res = await fetch(`${AGENT_URL}/draft-document`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ doc_type: docType, grant_id: grantId ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Agent error: ${res.status}`);
  }
  return res.json();
}

export async function getDrafts(token: string): Promise<Draft[]> {
  const res = await fetch(`${AGENT_URL}/drafts`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Agent error: ${res.status}`);
  return res.json();
}
