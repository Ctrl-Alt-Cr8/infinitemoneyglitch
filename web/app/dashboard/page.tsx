"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getConfig, getRuns, triggerRun, draftDocument, getDrafts } from "@/lib/agent";
import type { RunWithGrants, Grant, Draft, DraftResult } from "@/lib/agent";

type DraftDocType = "loi" | "artist_statement";

export default function DashboardPage() {
  const { user, loading, signOut, getIdToken } = useAuth();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [runs, setRuns] = useState<RunWithGrants[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [triggered, setTriggered] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"runs" | "drafts">("runs");

  // Draft modal state
  const [draftModalGrant, setDraftModalGrant] = useState<Grant | null>(null);
  const [draftTypes, setDraftTypes] = useState<Set<DraftDocType>>(new Set());
  const [drafting, setDrafting] = useState(false);
  const [draftResults, setDraftResults] = useState<DraftResult[]>([]);
  const [draftError, setDraftError] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!user) { router.replace("/"); return; }
    getIdToken().then((token) => {
      if (!token) { router.replace("/"); return; }
      return getConfig(token);
    }).then((config) => {
      if (config === null) router.replace("/onboarding");
      else setReady(true);
    }).catch(() => setReady(true));
  }, [user, loading, router, getIdToken]);

  useEffect(() => {
    if (!ready) return;
    async function loadData() {
      const token = await getIdToken();
      if (!token) return;
      const [runData, draftData] = await Promise.all([getRuns(token), getDrafts(token)]);
      const list = runData ?? [];
      setRuns(list);
      setDrafts(draftData ?? []);
      if (list.length > 0) setExpanded(list[0].id);
    }
    loadData()
      .catch((err) => setFetchError(err instanceof Error ? err.message : "Failed to load data"))
      .finally(() => setRunsLoading(false));
  }, [ready, getIdToken]);

  async function handleRunAgent() {
    setTriggering(true);
    setTriggerError(null);
    try {
      const token = await getIdToken();
      if (!token) return;
      await triggerRun(token);
      setTriggered(true);
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : "Failed to start agent");
    } finally {
      setTriggering(false);
    }
  }

  function openDraftModal(grant: Grant) {
    setDraftModalGrant(grant);
    setDraftTypes(new Set());
    setDraftResults([]);
    setDraftError(null);
  }

  function closeDraftModal() {
    setDraftModalGrant(null);
    setDrafting(false);
    setDraftResults([]);
    setDraftError(null);
  }

  async function handleDraft() {
    if (!draftModalGrant || draftTypes.size === 0) return;
    setDrafting(true);
    setDraftError(null);
    setDraftResults([]);
    try {
      const token = await getIdToken();
      if (!token) throw new Error("Not authenticated");
      const results = await Promise.all(
        [...draftTypes].map((dt) => draftDocument(token, dt, draftModalGrant.id))
      );
      setDraftResults(results);
      // Refresh drafts list
      const freshDrafts = await getDrafts(token);
      setDrafts(freshDrafts);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "Drafting failed");
    } finally {
      setDrafting(false);
    }
  }

  if (loading || !user || !ready) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-950">
        <div className="text-gray-400 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold tracking-tight">Infinite Money Glitch</h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">{user.email}</span>
          <button onClick={signOut} className="text-sm text-gray-400 hover:text-white transition-colors">
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        {/* Run Agent */}
        <div className="flex flex-col gap-2">
          {triggered ? (
            <div className="rounded-xl bg-gray-900 border border-gray-700 px-5 py-4 text-sm text-gray-300">
              Agent is running — this takes a few minutes. Refresh when done to see results.
            </div>
          ) : (
            <button
              onClick={handleRunAgent}
              disabled={triggering}
              className="self-start px-5 py-2.5 bg-white text-gray-900 font-medium rounded-lg hover:bg-gray-100 transition-colors text-sm disabled:opacity-50"
            >
              {triggering ? "Starting..." : "Find Grants"}
            </button>
          )}
          {triggerError && <p className="text-sm text-red-400">{triggerError}</p>}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-gray-800">
          {(["runs", "drafts"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${activeTab === tab ? "border-white text-white" : "border-transparent text-gray-500 hover:text-gray-300"}`}
            >
              {tab === "drafts" ? `Drafts (${drafts.length})` : "Grant History"}
            </button>
          ))}
        </div>

        {/* Run history tab */}
        {activeTab === "runs" && (
          <div className="space-y-4">
            {runsLoading && <div className="text-sm text-gray-500">Loading...</div>}
            {!runsLoading && fetchError && <div className="text-sm text-red-400">{fetchError}</div>}
            {!runsLoading && !fetchError && runs.length === 0 && (
              <div className="rounded-xl bg-gray-900 border border-gray-800 px-5 py-8 text-center text-sm text-gray-500">
                No runs yet. Hit <span className="text-white font-medium">Find Grants</span> to start your first search.
              </div>
            )}
            {runs.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                expanded={expanded === run.id}
                onToggle={() => setExpanded(expanded === run.id ? null : run.id)}
                onDraft={openDraftModal}
              />
            ))}
          </div>
        )}

        {/* Drafts tab */}
        {activeTab === "drafts" && (
          <div className="space-y-4">
            {drafts.length === 0 ? (
              <div className="rounded-xl bg-gray-900 border border-gray-800 px-5 py-8 text-center text-sm text-gray-500">
                No drafts yet. Use the <span className="text-white font-medium">Draft Document</span> button on any Priority or Review grant.
              </div>
            ) : (
              drafts.map((draft) => <DraftCard key={draft.id} draft={draft} />)
            )}
          </div>
        )}
      </main>

      {/* Draft modal */}
      {draftModalGrant && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={closeDraftModal}>
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5 border-b border-gray-800">
              <h3 className="font-semibold text-white">Draft Document</h3>
              <p className="mt-1 text-sm text-gray-400">
                {draftModalGrant.funder} — {draftModalGrant.title}
              </p>
            </div>

            {draftResults.length === 0 ? (
              <div className="px-6 py-5 space-y-4">
                <p className="text-sm text-gray-400">What would you like Claude to draft?</p>
                <div className="space-y-2">
                  {(["loi", "artist_statement"] as DraftDocType[]).map((dt) => (
                    <label key={dt} className="flex items-center gap-3 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={draftTypes.has(dt)}
                        onChange={(e) => {
                          const next = new Set(draftTypes);
                          if (e.target.checked) next.add(dt);
                          else next.delete(dt);
                          setDraftTypes(next);
                        }}
                        className="w-4 h-4 accent-white"
                      />
                      <span className="text-sm text-gray-300 group-hover:text-white transition-colors">
                        {dt === "loi" ? "Letter of Intent (LOI)" : "Artist Statement"}
                      </span>
                    </label>
                  ))}
                </div>

                {draftError && <p className="text-sm text-red-400">{draftError}</p>}

                <div className="flex gap-3 pt-2">
                  <button onClick={closeDraftModal} className="px-4 py-2.5 text-sm text-gray-400 hover:text-white transition-colors">
                    Cancel
                  </button>
                  <button
                    onClick={handleDraft}
                    disabled={drafting || draftTypes.size === 0}
                    className="flex-1 py-2.5 bg-white text-gray-900 font-medium rounded-lg hover:bg-gray-100 transition-colors text-sm disabled:opacity-50"
                  >
                    {drafting ? "Drafting with Claude..." : "Draft"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-6 py-5 space-y-6">
                {draftResults.map((result, i) => (
                  <div key={i} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-medium text-white capitalize">
                        {result.doc_type === "loi" ? "Letter of Intent" : "Artist Statement"}
                      </h4>
                      <button
                        onClick={() => navigator.clipboard.writeText(result.content)}
                        className="text-xs text-gray-500 hover:text-white transition-colors"
                      >
                        Copy
                      </button>
                    </div>
                    {!result.valid && result.issues.length > 0 && (
                      <div className="text-xs text-amber-400 space-y-0.5">
                        {result.issues.map((issue, j) => <div key={j}>⚠ {issue}</div>)}
                      </div>
                    )}
                    <pre className="text-sm text-gray-300 whitespace-pre-wrap font-sans bg-gray-800/50 rounded-lg p-4 max-h-80 overflow-y-auto">
                      {result.content}
                    </pre>
                  </div>
                ))}
                <button
                  onClick={closeDraftModal}
                  className="w-full py-2.5 bg-gray-800 text-white font-medium rounded-lg hover:bg-gray-700 transition-colors text-sm"
                >
                  Done — saved to Drafts
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function RunCard({
  run, expanded, onToggle, onDraft,
}: {
  run: RunWithGrants;
  expanded: boolean;
  onToggle: () => void;
  onDraft: (grant: Grant) => void;
}) {
  const date = new Date(run.run_at);
  const dateStr = date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const timeStr = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 overflow-hidden">
      <button onClick={onToggle} className="w-full text-left px-5 py-4 hover:bg-gray-800/50 transition-colors">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-white">
              {dateStr} <span className="text-gray-500 font-normal">at {timeStr}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
              <span>{run.grants_fetched ?? "—"} fetched</span>
              <span className="text-green-400">{run.grants_priority} PRIORITY</span>
              <span className="text-amber-400">{run.grants_review} REVIEW</span>
              <span className="text-gray-500">{run.grants_skip} SKIP</span>
              <span className="text-gray-500">${run.estimated_cost.toFixed(4)}</span>
            </div>
          </div>
          <span className="text-gray-500 text-xs mt-0.5 shrink-0">
            {expanded ? "▲" : "▼"} {run.grants.length} grants
          </span>
        </div>
      </button>

      {expanded && run.grants.length > 0 && (
        <div className="border-t border-gray-800 divide-y divide-gray-800/60">
          {run.grants.map((grant) => (
            <GrantRow key={grant.id} grant={grant} onDraft={onDraft} />
          ))}
        </div>
      )}

      {expanded && run.grants.length === 0 && (
        <div className="border-t border-gray-800 px-5 py-4 text-sm text-gray-500">
          No grants recorded for this run.
        </div>
      )}
    </div>
  );
}

function GrantRow({ grant, onDraft }: { grant: Grant; onDraft: (grant: Grant) => void }) {
  const badge: Record<string, string> = {
    PRIORITY: "bg-green-500/15 text-green-400 border border-green-500/25",
    REVIEW: "bg-amber-500/15 text-amber-400 border border-amber-500/25",
    SKIP: "bg-gray-500/15 text-gray-500 border border-gray-500/25",
  };

  const deadlineDaysLeft = (() => {
    if (!grant.deadline) return null;
    try {
      const parts = grant.deadline.split("-");
      if (parts.length !== 3) return null;
      const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
      return Math.ceil((d.getTime() - Date.now()) / 86400000);
    } catch { return null; }
  })();

  const showDraftBtn = grant.decision === "PRIORITY" || grant.decision === "REVIEW";

  return (
    <div className="px-5 py-3 flex items-start gap-3">
      <span className={`shrink-0 mt-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${badge[grant.decision] ?? badge.SKIP}`}>
        {grant.decision}
      </span>
      <div className="flex-1 min-w-0 space-y-0.5">
        {grant.url ? (
          <a href={grant.url} target="_blank" rel="noopener noreferrer"
            className="text-sm text-white hover:text-gray-300 transition-colors truncate block">
            {grant.title}
          </a>
        ) : (
          <span className="text-sm text-white truncate block">{grant.title}</span>
        )}
        <div className="flex flex-wrap gap-x-3 text-xs text-gray-500">
          <span>{grant.funder}</span>
          {grant.award_amount && <span>{grant.award_amount}</span>}
          {deadlineDaysLeft !== null && (
            <span className={deadlineDaysLeft <= 30 ? "text-amber-400 font-medium" : ""}>
              {deadlineDaysLeft <= 0 ? "Closed" : deadlineDaysLeft <= 30 ? `${deadlineDaysLeft}d left` : grant.deadline}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 flex items-center gap-2">
        <span className="text-xs text-gray-500 tabular-nums">{grant.score}</span>
        {showDraftBtn && (
          <button
            onClick={() => onDraft(grant)}
            className="text-xs px-2 py-1 bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white rounded transition-colors"
          >
            Draft
          </button>
        )}
      </div>
    </div>
  );
}

function DraftCard({ draft }: { draft: Draft }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 overflow-hidden">
      <button onClick={() => setOpen((p) => !p)} className="w-full text-left px-5 py-4 hover:bg-gray-800/50 transition-colors">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-white capitalize">
              {draft.doc_type === "loi" ? "Letter of Intent" : "Artist Statement"}
            </div>
            {draft.grant_title && (
              <div className="text-xs text-gray-500 mt-0.5">{draft.funder} — {draft.grant_title}</div>
            )}
            <div className="text-xs text-gray-600 mt-0.5">
              {new Date(draft.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(draft.content); }}
              className="text-xs text-gray-500 hover:text-white transition-colors"
            >
              Copy
            </button>
            <span className="text-gray-500 text-xs">{open ? "▲" : "▼"}</span>
          </div>
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-800 px-5 py-4">
          <pre className="text-sm text-gray-300 whitespace-pre-wrap font-sans max-h-96 overflow-y-auto">
            {draft.content}
          </pre>
        </div>
      )}
    </div>
  );
}
