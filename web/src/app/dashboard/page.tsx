"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ApiError,
  DraftContent,
  api,
  discardDraft,
  getDraft,
  sendDraft,
  updateDraft,
} from "@/lib/api";
import { useUser } from "@/lib/useUser";

interface EmailResult {
  subject: string;
  sender: string;
  category: "action" | "fyi" | "spam" | string;
  summary: string;
  draft_id: string | null;
  calendar_status: string | null;
}

type DraftState = "pending" | "sent" | "discarded";

const CATEGORY_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  action: "default",
  fyi: "secondary",
  spam: "destructive",
};

function HoverText({ text, clamp }: { text: string; clamp: 1 | 2 }) {
  const clampClass = clamp === 1 ? "truncate" : "line-clamp-2";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={`block cursor-default ${clampClass}`}>{text}</span>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// Draft editor modal — review-approve HITL UI
// ---------------------------------------------------------------------------

function DraftEditor({
  draftId,
  onClose,
  onSent,
  onDiscarded,
}: {
  draftId: string;
  onClose: () => void;
  onSent: () => void;
  onDiscarded: () => void;
}) {
  // Modal is keyed by draftId at the mount site, so draftId is stable for
  // this component's lifetime. Initial state covers the "loading" render;
  // the effect runs once on mount to fetch.
  const [draft, setDraft] = useState<DraftContent | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<null | "load" | "save" | "send" | "discard">(
    "load",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDraft(draftId)
      .then((d) => {
        if (cancelled) return;
        setDraft(d);
        setSubject(d.subject);
        setBody(d.body);
        setBusy(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setBusy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [draftId]);

  async function handleSave() {
    setBusy("save");
    setError(null);
    try {
      const updated = await updateDraft(draftId, { subject, body });
      setDraft(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function handleSaveAndSend() {
    setBusy("send");
    setError(null);
    try {
      await updateDraft(draftId, { subject, body });
      await sendDraft(draftId);
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  }

  async function handleDiscard() {
    if (!confirm("Discard this draft? This cannot be undone.")) return;
    setBusy("discard");
    setError(null);
    try {
      await discardDraft(draftId);
      onDiscarded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg border bg-white p-6 shadow-lg dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Review Draft</h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            ✕
          </Button>
        </div>

        {busy === "load" ? (
          <p className="text-sm text-muted-foreground">Loading draft…</p>
        ) : error && !draft ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : draft ? (
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                To
              </label>
              <div className="rounded border bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-800">
                {draft.to || "(no recipient)"}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Subject
              </label>
              <input
                className="w-full rounded border bg-white px-3 py-2 text-sm dark:bg-zinc-800"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                disabled={busy !== null}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Body
              </label>
              <textarea
                className="h-48 w-full resize-y rounded border bg-white px-3 py-2 font-mono text-sm dark:bg-zinc-800"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                disabled={busy !== null}
              />
            </div>

            {error ? (
              <p className="text-sm text-red-600">{error}</p>
            ) : null}

            <div className="mt-2 flex flex-wrap justify-end gap-2">
              <Button
                variant="ghost"
                onClick={handleDiscard}
                disabled={busy !== null}
              >
                {busy === "discard" ? "Discarding…" : "Discard"}
              </Button>
              <Button
                variant="outline"
                onClick={handleSave}
                disabled={busy !== null}
              >
                {busy === "save" ? "Saving…" : "Save"}
              </Button>
              <Button onClick={handleSaveAndSend} disabled={busy !== null}>
                {busy === "send" ? "Sending…" : "Save & Send"}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const router = useRouter();
  const { user, isLoading, unauthenticated } = useUser();

  const [maxEmails, setMaxEmails] = useState(5);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<EmailResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  // Per-draft action state: which drafts have been sent / discarded in this session.
  const [draftStates, setDraftStates] = useState<Record<string, DraftState>>({});
  const [sendingDraftId, setSendingDraftId] = useState<string | null>(null);

  useEffect(() => {
    if (unauthenticated) router.replace("/");
  }, [unauthenticated, router]);

  async function logout() {
    try {
      await api(`/auth/logout`, { method: "POST" });
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
    }
    router.replace("/");
  }

  async function runAgent() {
    setRunning(true);
    setError(null);
    setResults(null);
    setDraftStates({});
    try {
      const data = await api<EmailResult[]>("/agent/process", {
        method: "POST",
        body: JSON.stringify({ max_results: maxEmails }),
      });
      setResults(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  async function quickSend(draftId: string) {
    if (!confirm("Send this draft as-is?")) return;
    setSendingDraftId(draftId);
    try {
      await sendDraft(draftId);
      setDraftStates((s) => ({ ...s, [draftId]: "sent" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSendingDraftId(null);
    }
  }

  async function quickDiscard(draftId: string) {
    if (!confirm("Discard this draft? This cannot be undone.")) return;
    setSendingDraftId(draftId);
    try {
      await discardDraft(draftId);
      setDraftStates((s) => ({ ...s, [draftId]: "discarded" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSendingDraftId(null);
    }
  }

  if (isLoading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  const actionsCount = results?.filter((r) => r.category === "action").length ?? 0;
  const draftsCount = results?.filter((r) => r.draft_id).length ?? 0;

  return (
    <main className="min-h-screen bg-zinc-50 p-6 dark:bg-black">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">⚡ Inbox Zero Agent</h1>
          <div className="flex items-center gap-4">
            {user.is_demo ? (
              <Badge variant="secondary">Demo mode</Badge>
            ) : null}
            <span className="text-sm text-muted-foreground">{user.email}</span>
            <Button variant="outline" onClick={logout}>
              Logout
            </Button>
          </div>
        </header>

        <Card>
          <CardHeader>
            <CardTitle>Run Agent</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="mb-2 block text-sm font-medium">
                Emails to fetch: {maxEmails}
              </label>
              <Slider
                value={[maxEmails]}
                min={1}
                max={20}
                step={1}
                onValueChange={(v) => setMaxEmails(v[0])}
                disabled={running}
              />
            </div>
            <Button onClick={runAgent} disabled={running} size="lg">
              {running ? "Running…" : "🚀 Run Agent"}
            </Button>
          </CardContent>
        </Card>

        {error ? (
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-red-600">Error: {error}</p>
            </CardContent>
          </Card>
        ) : null}

        {results !== null ? (
          <Card>
            <CardHeader>
              <CardTitle>Results</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-4 flex gap-6 text-sm">
                <span>
                  <strong>{results.length}</strong> processed
                </span>
                <span>
                  <strong>{actionsCount}</strong> actions
                </span>
                <span>
                  <strong>{draftsCount}</strong> drafts created
                </span>
              </div>
              {results.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Inbox is already Zero! 🎉
                </p>
              ) : (
                <TooltipProvider delayDuration={150}>
                  <Table className="table-fixed">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[18%]">Subject</TableHead>
                        <TableHead className="w-[14%]">From</TableHead>
                        <TableHead className="w-[8%]">Category</TableHead>
                        <TableHead className="w-[28%]">Summary</TableHead>
                        <TableHead className="w-[14%]">Calendar</TableHead>
                        <TableHead className="w-[18%]">Draft</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((r, i) => {
                        const draftState = r.draft_id ? draftStates[r.draft_id] : undefined;
                        const acting = r.draft_id ? sendingDraftId === r.draft_id : false;
                        return (
                          <TableRow key={i}>
                            <TableCell>
                              <HoverText text={r.subject} clamp={1} />
                            </TableCell>
                            <TableCell>
                              <HoverText text={r.sender} clamp={1} />
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={CATEGORY_VARIANT[r.category] ?? "secondary"}
                              >
                                {r.category}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-sm">
                              <HoverText text={r.summary} clamp={2} />
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              <HoverText text={r.calendar_status ?? "—"} clamp={2} />
                            </TableCell>
                            <TableCell className="text-xs">
                              {!r.draft_id ? (
                                "—"
                              ) : draftState === "sent" ? (
                                <span className="text-green-600">✓ sent</span>
                              ) : draftState === "discarded" ? (
                                <span className="text-zinc-500">discarded</span>
                              ) : (
                                <div className="flex gap-1">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setEditingDraftId(r.draft_id!)}
                                    disabled={acting}
                                  >
                                    Edit
                                  </Button>
                                  <Button
                                    size="sm"
                                    onClick={() => quickSend(r.draft_id!)}
                                    disabled={acting}
                                  >
                                    {acting ? "…" : "Send"}
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => quickDiscard(r.draft_id!)}
                                    disabled={acting}
                                    aria-label="Discard"
                                  >
                                    ✕
                                  </Button>
                                </div>
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TooltipProvider>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>

      {editingDraftId ? (
        <DraftEditor
          key={editingDraftId}
          draftId={editingDraftId}
          onClose={() => setEditingDraftId(null)}
          onSent={() => {
            setDraftStates((s) => ({ ...s, [editingDraftId]: "sent" }));
            setEditingDraftId(null);
          }}
          onDiscarded={() => {
            setDraftStates((s) => ({ ...s, [editingDraftId]: "discarded" }));
            setEditingDraftId(null);
          }}
        />
      ) : null}
    </main>
  );
}
