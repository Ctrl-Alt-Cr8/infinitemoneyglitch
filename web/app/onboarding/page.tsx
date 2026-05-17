"use client";

import { useEffect, useRef, useState, KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { parseResume, submitOnboarding } from "@/lib/agent";
import type { ParsedProfile } from "@/lib/agent";

type Step = "choose" | "interview" | "form";
type OrgType = "individual" | "collective" | "nonprofit" | "";
type DeadlineWindow = "30" | "60" | "90" | "180" | "rolling" | "";
type Priority = "high" | "medium" | "low";

const ALL_DISCIPLINES = [
  "Visual Art", "Music", "Writing", "Film", "Performance",
  "Craft", "Community Organizing", "Curatorial", "Dance", "Poetry",
  "Photography", "Theater", "Other",
];

interface Interview {
  disciplines: string[];
  org_type: OrgType;
  geographic_focus: string[];
  budget_min: string;
  deadline_window: DeadlineWindow;
  mission_weight: Priority;
  award_weight: Priority;
  deadline_weight: Priority;
  project_description: string;
  past_grants: string;
}

interface FormState {
  name: string;
  disciplines: string[];
  org_type: OrgType;
  location_pref: string;
  geographic_focus: string[];
  summary: string;
  project_description: string;
  past_grants: string;
  constraints: string;
  keywords: string[];
  recipient_email: string;
}

const BLANK_INTERVIEW: Interview = {
  disciplines: [],
  org_type: "",
  geographic_focus: [],
  budget_min: "",
  deadline_window: "90",
  mission_weight: "high",
  award_weight: "medium",
  deadline_weight: "medium",
  project_description: "",
  past_grants: "",
};

const BLANK_FORM: FormState = {
  name: "",
  disciplines: [],
  org_type: "individual",
  location_pref: "",
  geographic_focus: [],
  summary: "",
  project_description: "",
  past_grants: "",
  constraints: "",
  keywords: [],
  recipient_email: "",
};

function interviewToText(iv: Interview): string {
  const parts: string[] = [];
  if (iv.disciplines.length) parts.push(`Disciplines: ${iv.disciplines.join(", ")}`);
  if (iv.org_type) parts.push(`Org type: ${iv.org_type}`);
  if (iv.geographic_focus.length) parts.push(`Geographic focus: ${iv.geographic_focus.join(", ")}`);
  if (iv.budget_min) parts.push(`Minimum award: $${iv.budget_min}`);
  if (iv.deadline_window) parts.push(`Deadline window: ${iv.deadline_window} days`);
  if (iv.project_description) parts.push(`Current project: ${iv.project_description}`);
  if (iv.past_grants) parts.push(`Past grants: ${iv.past_grants}`);
  return parts.join("\n");
}

function fromParsed(parsed: ParsedProfile, iv: Interview, fallbackEmail: string): FormState {
  return {
    name: parsed.name ?? "",
    disciplines: parsed.disciplines?.length ? parsed.disciplines : iv.disciplines.map((d) => d.toLowerCase()),
    org_type: (iv.org_type || parsed.org_type || "individual") as OrgType,
    location_pref: parsed.location_pref ?? "",
    geographic_focus: iv.geographic_focus,
    summary: parsed.summary ?? "",
    project_description: parsed.project_description ?? iv.project_description,
    past_grants: iv.past_grants,
    constraints: parsed.constraints ?? "",
    keywords: parsed.keywords ?? [],
    recipient_email: fallbackEmail,
  };
}

export default function OnboardingPage() {
  const { user, loading, getIdToken } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<Step>("choose");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [interview, setInterview] = useState<Interview>(BLANK_INTERVIEW);
  const [form, setForm] = useState<FormState>(BLANK_FORM);
  const [parsing, setParsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geoInput, setGeoInput] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/");
  }, [user, loading, router]);

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setResumeFile(file);
    setStep("interview");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleManual() {
    setResumeFile(null);
    setStep("interview");
  }

  function toggleDiscipline(d: string) {
    const lower = d.toLowerCase();
    setInterview((prev) => ({
      ...prev,
      disciplines: prev.disciplines.includes(lower)
        ? prev.disciplines.filter((x) => x !== lower)
        : [...prev.disciplines, lower],
    }));
  }

  function addGeoFocus(raw: string) {
    const val = raw.trim();
    if (!val || interview.geographic_focus.includes(val)) { setGeoInput(""); return; }
    setInterview((prev) => ({ ...prev, geographic_focus: [...prev.geographic_focus, val] }));
    setGeoInput("");
  }

  function removeGeoFocus(val: string) {
    setInterview((prev) => ({ ...prev, geographic_focus: prev.geographic_focus.filter((x) => x !== val) }));
  }

  async function handleInterviewContinue() {
    setError(null);
    if (resumeFile) {
      setParsing(true);
      try {
        const token = await getIdToken();
        if (!token) throw new Error("Not authenticated");
        const parsed = await parseResume(token, resumeFile, interviewToText(interview));
        setForm(fromParsed(parsed, interview, user?.email ?? ""));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to parse document");
        setParsing(false);
        return;
      } finally {
        setParsing(false);
      }
    } else {
      setForm({
        ...BLANK_FORM,
        disciplines: interview.disciplines,
        org_type: interview.org_type || "individual",
        geographic_focus: interview.geographic_focus,
        project_description: interview.project_description,
        past_grants: interview.past_grants,
        recipient_email: user?.email ?? "",
      });
    }
    setStep("form");
  }

  function setF(field: keyof Omit<FormState, "keywords" | "disciplines" | "geographic_focus">) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { setError("Name is required"); return; }
    if (!form.recipient_email.trim()) { setError("Report email is required"); return; }
    setSubmitting(true);
    setError(null);
    try {
      const token = await getIdToken();
      if (!token) throw new Error("Not authenticated");
      await submitOnboarding(token, {
        name: form.name.trim(),
        disciplines: form.disciplines,
        org_type: form.org_type || "individual",
        location_pref: form.location_pref.trim(),
        geographic_focus: form.geographic_focus,
        keywords: form.keywords,
        summary: form.summary.trim(),
        constraints: form.constraints.trim(),
        recipient_email: form.recipient_email.trim(),
        project_description: form.project_description.trim(),
        past_grants: form.past_grants.trim(),
        budget_min: interview.budget_min ? parseInt(interview.budget_min) : 0,
        deadline_window_days: interview.deadline_window && interview.deadline_window !== "rolling"
          ? parseInt(interview.deadline_window)
          : 365,
        scoring_weights: {
          mission: interview.mission_weight,
          award: interview.award_weight,
          deadline: interview.deadline_weight,
        },
        interview_answers: interviewToText(interview),
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
      setSubmitting(false);
    }
  }

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-950">
        <div className="text-gray-400 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4">
        <h1 className="text-lg font-semibold tracking-tight">Infinite Money Glitch</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-12">
        <div className="mb-8">
          <h2 className="text-2xl font-bold">Set up your grant agent</h2>
          <p className="mt-1 text-sm text-gray-400">
            Tell us about your practice so we can find and score grants for you.
          </p>
        </div>

        {/* Step 1 — Choose path */}
        {step === "choose" && (
          <div className="space-y-4">
            <input ref={fileInputRef} type="file" accept=".pdf" className="hidden" onChange={handleFileSelect} />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full text-left p-6 bg-gray-900 border border-gray-700 rounded-xl hover:border-gray-500 transition-colors"
            >
              <div className="font-semibold">Upload a document</div>
              <div className="mt-1 text-sm text-gray-400">Artist CV, artist statement, or past grant application (PDF) — Claude extracts your profile</div>
            </button>
            <button
              onClick={handleManual}
              className="w-full text-left p-6 bg-gray-900 border border-gray-700 rounded-xl hover:border-gray-500 transition-colors"
            >
              <div className="font-semibold">Fill in manually</div>
              <div className="mt-1 text-sm text-gray-400">Enter your practice details yourself</div>
            </button>
          </div>
        )}

        {/* Step 2 — Interview */}
        {step === "interview" && (
          <div className="space-y-6">
            {resumeFile && (
              <div className="text-xs text-gray-500 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
                Document: <span className="text-gray-300">{resumeFile.name}</span>
              </div>
            )}

            <Field label="Your disciplines" hint="Select all that apply">
              <div className="flex flex-wrap gap-2 mt-1">
                {ALL_DISCIPLINES.map((d) => {
                  const lower = d.toLowerCase();
                  const active = interview.disciplines.includes(lower);
                  return (
                    <button key={d} type="button"
                      onClick={() => toggleDiscipline(d)}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${active ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </Field>

            <Field label="You are applying as...">
              <div className="flex gap-2">
                {(["individual", "collective", "nonprofit"] as OrgType[]).map((opt) => (
                  <button key={opt} type="button"
                    onClick={() => setInterview((prev) => ({ ...prev, org_type: prev.org_type === opt ? "" : opt }))}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border capitalize transition-colors ${interview.org_type === opt ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                    {opt === "nonprofit" ? "Nonprofit 501(c)(3)" : opt.charAt(0).toUpperCase() + opt.slice(1)}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="Geographic focus" hint="Where you want grants from — press Enter to add">
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  {interview.geographic_focus.map((g) => (
                    <span key={g} className="flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-full px-3 py-1 text-sm">
                      {g}
                      <button type="button" onClick={() => removeGeoFocus(g)} className="text-gray-500 hover:text-red-400 ml-1">×</button>
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  value={geoInput}
                  onChange={(e) => setGeoInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addGeoFocus(geoInput); } }}
                  onBlur={() => addGeoFocus(geoInput)}
                  className={inputCls}
                  placeholder="NYC, New York State, national, international..."
                />
              </div>
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Minimum award size" hint="In dollars, e.g. 1000">
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                  <input type="number" min={0} step={500}
                    value={interview.budget_min}
                    onChange={(e) => setInterview((prev) => ({ ...prev, budget_min: e.target.value }))}
                    className={inputCls + " pl-7"}
                    placeholder="1000" />
                </div>
              </Field>
              <Field label="Deadline window">
                <div className="flex flex-wrap gap-1.5">
                  {(["30", "60", "90", "180", "rolling"] as DeadlineWindow[]).map((opt) => (
                    <button key={opt} type="button"
                      onClick={() => setInterview((prev) => ({ ...prev, deadline_window: prev.deadline_window === opt ? "" : opt }))}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${interview.deadline_window === opt ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                      {opt === "rolling" ? "Rolling only" : `${opt} days`}
                    </button>
                  ))}
                </div>
              </Field>
            </div>

            <Field label="Scoring priorities" hint="How much should each factor influence your grant score?">
              <div className="space-y-3">
                {(["mission", "award", "deadline"] as const).map((criterion) => {
                  const field = `${criterion}_weight` as keyof Interview;
                  const value = interview[field] as Priority;
                  return (
                    <div key={criterion} className="flex items-center gap-3">
                      <span className="text-sm text-gray-300 w-28 capitalize">{criterion === "mission" ? "Mission alignment" : criterion === "award" ? "Award size" : "Deadline proximity"}</span>
                      <div className="flex gap-1.5">
                        {(["high", "medium", "low"] as Priority[]).map((p) => (
                          <button key={p} type="button"
                            onClick={() => setInterview((prev) => ({ ...prev, [field]: p }))}
                            className={`px-3 py-1 rounded text-xs font-medium border capitalize transition-colors ${value === p ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                            {p}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Field>

            <Field label="What are you currently working on?" hint="A project, a body of work, a community initiative">
              <textarea
                value={interview.project_description}
                onChange={(e) => setInterview((prev) => ({ ...prev, project_description: e.target.value }))}
                rows={3}
                className={inputCls}
                placeholder="e.g. A series of large-scale murals exploring the history of my neighborhood..."
              />
            </Field>

            <Field label="Past grants received" hint="Optional — helps calibrate grant fit. List names or funders.">
              <textarea
                value={interview.past_grants}
                onChange={(e) => setInterview((prev) => ({ ...prev, past_grants: e.target.value }))}
                rows={2}
                className={inputCls}
                placeholder="e.g. NYFA Artists' Fellowship 2022, Creative Capital 2023..."
              />
            </Field>

            {error && <p className="text-sm text-red-400">{error}</p>}

            <div className="flex gap-3 pt-2">
              <button type="button" onClick={() => { setStep("choose"); setError(null); }} className="px-4 py-2.5 text-sm text-gray-400 hover:text-white transition-colors">
                Back
              </button>
              <button
                onClick={handleInterviewContinue}
                disabled={parsing}
                className="flex-1 py-2.5 bg-white text-gray-900 font-medium rounded-lg hover:bg-gray-100 transition-colors text-sm disabled:opacity-50"
              >
                {parsing ? "Parsing with Claude..." : "Continue"}
              </button>
            </div>
          </div>
        )}

        {/* Step 3 — Profile form */}
        {step === "form" && (
          <form onSubmit={handleSubmit} className="space-y-6">
            <Field label="Full name" required>
              <input type="text" value={form.name} onChange={setF("name")} required className={inputCls} placeholder="Jane Smith" />
            </Field>

            <Field label="Disciplines" hint="Your practice areas">
              <div className="flex flex-wrap gap-2 mt-1">
                {ALL_DISCIPLINES.map((d) => {
                  const lower = d.toLowerCase();
                  const active = form.disciplines.includes(lower);
                  return (
                    <button key={d} type="button"
                      onClick={() => setForm((prev) => ({
                        ...prev,
                        disciplines: active
                          ? prev.disciplines.filter((x) => x !== lower)
                          : [...prev.disciplines, lower],
                      }))}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${active ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </Field>

            <Field label="You are applying as">
              <div className="flex gap-2">
                {(["individual", "collective", "nonprofit"] as OrgType[]).map((opt) => (
                  <button key={opt} type="button"
                    onClick={() => setForm((prev) => ({ ...prev, org_type: opt }))}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${form.org_type === opt ? "bg-white text-gray-900 border-white" : "bg-gray-900 text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                    {opt === "nonprofit" ? "Nonprofit 501(c)(3)" : opt.charAt(0).toUpperCase() + opt.slice(1)}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="City / location" hint="Your city, state, or country">
              <input type="text" value={form.location_pref} onChange={setF("location_pref")} className={inputCls} placeholder="New York, NY" />
            </Field>

            <Field label="Practice summary">
              <textarea value={form.summary} onChange={setF("summary")} rows={4} className={inputCls} placeholder="2–3 sentences describing your practice and current work." />
            </Field>

            <Field label="Current project">
              <textarea value={form.project_description} onChange={setF("project_description")} rows={3} className={inputCls} placeholder="What are you working on?" />
            </Field>

            <Field label="Search keywords" hint="Used to search for grants — add, remove, or reorder">
              <KeywordTagEditor
                keywords={form.keywords}
                onChange={(kw) => setForm((prev) => ({ ...prev, keywords: kw }))}
              />
            </Field>

            <Field label="Constraints" hint="Optional — e.g. US citizens only, no 501c3 required">
              <input type="text" value={form.constraints} onChange={setF("constraints")} className={inputCls} placeholder="No 501c3 required" />
            </Field>

            <Field label="Digest email" hint="Grant digest reports will be sent here" required>
              <input type="email" value={form.recipient_email} onChange={setF("recipient_email")} required className={inputCls} placeholder="you@example.com" />
            </Field>

            {error && <p className="text-sm text-red-400">{error}</p>}

            <div className="flex gap-3 pt-2">
              <button type="button" onClick={() => { setStep("interview"); setError(null); }} className="px-4 py-2.5 text-sm text-gray-400 hover:text-white transition-colors">
                Back
              </button>
              <button type="submit" disabled={submitting} className="flex-1 py-2.5 bg-white text-gray-900 font-medium rounded-lg hover:bg-gray-100 transition-colors text-sm disabled:opacity-50">
                {submitting ? "Saving..." : "Start my grant agent"}
              </button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
}

function KeywordTagEditor({ keywords, onChange }: { keywords: string[]; onChange: (kw: string[]) => void }) {
  const [input, setInput] = useState("");

  function addKeyword(raw: string) {
    const kw = raw.trim();
    if (!kw || keywords.includes(kw)) { setInput(""); return; }
    onChange([...keywords, kw]);
    setInput("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addKeyword(input);
    } else if (e.key === "Backspace" && !input && keywords.length > 0) {
      onChange(keywords.slice(0, -1));
    }
  }

  function remove(i: number) {
    onChange(keywords.filter((_, idx) => idx !== i));
  }

  function move(i: number, dir: -1 | 1) {
    const next = [...keywords];
    const j = i + dir;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {keywords.map((kw, i) => (
          <span key={i} className="flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-full px-3 py-1 text-sm text-white">
            <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className="text-gray-500 hover:text-white disabled:opacity-20 text-xs leading-none">↑</button>
            <button type="button" onClick={() => move(i, 1)} disabled={i === keywords.length - 1} className="text-gray-500 hover:text-white disabled:opacity-20 text-xs leading-none">↓</button>
            {kw}
            <button type="button" onClick={() => remove(i)} className="text-gray-500 hover:text-red-400 ml-1 leading-none">×</button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => addKeyword(input)}
        className={inputCls}
        placeholder="Type a keyword and press Enter or comma to add..."
      />
    </div>
  );
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-200 mb-1">
        {label}{required && <span className="text-red-400 ml-1">*</span>}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

const inputCls = "w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-gray-500 transition-colors";
