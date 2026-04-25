"use client";

import useSWR from "swr";

import { ApiError, api } from "./api";

export interface User {
  email: string;
  scopes: string[];
}

export function useUser() {
  const { data, error, isLoading, mutate } = useSWR<User>(
    "/auth/me",
    (path: string) => api<User>(path),
    { shouldRetryOnError: false },
  );

  const unauthenticated = error instanceof ApiError && error.status === 401;

  return {
    user: data ?? null,
    isLoading,
    unauthenticated,
    error: unauthenticated ? null : (error ?? null),
    refresh: mutate,
  };
}
