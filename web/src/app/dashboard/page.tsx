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
import { ApiError, api } from "@/lib/api";
import { useUser } from "@/lib/useUser";

interface EmailResult {
  subject: string;
  sender: string;
  category: "action" | "fyi" | "spam" | string;
  summary: string;
  draft_id: string | null;
  calendar_status: string | null;
}

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

export default function DashboardPage() {
  const router = useRouter();
  const { user, isLoading, unauthenticated } = useUser();

  const [maxEmails, setMaxEmails] = useState(5);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<EmailResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
                        <TableHead className="w-[20%]">Subject</TableHead>
                        <TableHead className="w-[16%]">From</TableHead>
                        <TableHead className="w-[8%]">Category</TableHead>
                        <TableHead className="w-[34%]">Summary</TableHead>
                        <TableHead className="w-[16%]">Calendar</TableHead>
                        <TableHead className="w-[6%]">Draft</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((r, i) => (
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
                            {r.draft_id ? "✓" : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TooltipProvider>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </main>
  );
}
