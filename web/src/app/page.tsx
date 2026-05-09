"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { demoLoginUrl, loginUrl } from "@/lib/api";

function LoginCard() {
  const params = useSearchParams();
  const authError = params.get("auth_error");

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-2xl">⚡ Inbox Zero Agent</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Sign in with Google to let the agent triage your inbox, draft replies
          for action items, and check your calendar for proposed meetings.
        </p>
        {authError ? (
          <p className="text-sm text-red-600">
            Login failed: <code>{authError}</code>. Please try again.
          </p>
        ) : null}
        <Button asChild size="lg">
          <a href={loginUrl()}>Sign in with Google</a>
        </Button>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          <span>or</span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <Button asChild size="lg" variant="outline">
          <a href={demoLoginUrl()}>Try Demo (no Google login)</a>
        </Button>
        <p className="text-xs text-muted-foreground">
          Demo mode loads sample emails and a calendar conflict so you can
          explore the agent without granting access to a real inbox.
        </p>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 p-6 dark:bg-black">
      <Suspense fallback={null}>
        <LoginCard />
      </Suspense>
    </main>
  );
}
