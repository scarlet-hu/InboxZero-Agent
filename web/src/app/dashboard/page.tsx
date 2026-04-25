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
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Subject</TableHead>
                      <TableHead>From</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Summary</TableHead>
                      <TableHead>Calendar</TableHead>
                      <TableHead>Draft</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="max-w-xs truncate">
                          {r.subject}
                        </TableCell>
                        <TableCell className="max-w-xs truncate">
                          {r.sender}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={CATEGORY_VARIANT[r.category] ?? "secondary"}
                          >
                            {r.category}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-md text-sm">
                          {r.summary}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {r.calendar_status ?? "—"}
                        </TableCell>
                        <TableCell className="text-xs">
                          {r.draft_id ? "✓" : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </main>
  );
}
