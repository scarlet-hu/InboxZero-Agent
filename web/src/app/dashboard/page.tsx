"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, BACKEND_URL, api } from "@/lib/api";
import { useUser } from "@/lib/useUser";

export default function DashboardPage() {
  const router = useRouter();
  const { user, isLoading, unauthenticated } = useUser();

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

  if (isLoading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

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
            <CardTitle>Dashboard</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Backend: <code>{BACKEND_URL}</code>
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Run controls and results table land in the next commit.
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
