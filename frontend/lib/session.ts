"use client";

import { useEffect, useState } from "react";

const SESSION_ID_KEY = "bilimind.session_id";
const USER_NAME_KEY = "bilimind.user_name";
const BUILD_TASK_PREFIX = "bilimind.build_task.";

export interface AuthSession {
  sessionId: string | null;
  userName: string | null;
}

export interface KnowledgeBuildTaskSnapshot {
  taskId: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string | null;
  progress?: number;
  currentStep?: string | null;
  updatedAt: number;
}

function safeLocalStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

export function readAuthSession(): AuthSession {
  const storage = safeLocalStorage();
  if (!storage) return { sessionId: null, userName: null };
  return {
    sessionId: storage.getItem(SESSION_ID_KEY),
    userName: storage.getItem(USER_NAME_KEY),
  };
}

export function setAuthSession(sessionId: string, userName?: string | null) {
  const storage = safeLocalStorage();
  if (!storage) return;
  storage.setItem(SESSION_ID_KEY, sessionId);
  if (userName) storage.setItem(USER_NAME_KEY, userName);
  window.dispatchEvent(new Event("bilimind:auth-session-change"));
}

export function clearAuthSession() {
  const storage = safeLocalStorage();
  if (!storage) return;
  const { sessionId } = readAuthSession();
  storage.removeItem(SESSION_ID_KEY);
  storage.removeItem(USER_NAME_KEY);
  if (sessionId) storage.removeItem(BUILD_TASK_PREFIX + sessionId);
  window.dispatchEvent(new Event("bilimind:auth-session-change"));
}

export function isActiveSession(sessionId?: string | null): boolean {
  if (!sessionId) return false;
  return readAuthSession().sessionId === sessionId;
}

export function useAuthSession() {
  const [session, setSession] = useState<AuthSession>(() => readAuthSession());

  useEffect(() => {
    const sync = () => setSession(readAuthSession());
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener("bilimind:auth-session-change", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("bilimind:auth-session-change", sync);
    };
  }, []);

  return {
    sessionId: session.sessionId,
    userName: session.userName,
    scopeKey: session.sessionId || "anonymous",
  };
}

export function readKnowledgeBuildTask(sessionId?: string | null): KnowledgeBuildTaskSnapshot | null {
  if (!sessionId) return null;
  const storage = safeLocalStorage();
  if (!storage) return null;
  const raw = storage.getItem(BUILD_TASK_PREFIX + sessionId);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as KnowledgeBuildTaskSnapshot;
  } catch {
    storage.removeItem(BUILD_TASK_PREFIX + sessionId);
    return null;
  }
}

export function writeKnowledgeBuildTask(
  sessionId: string,
  snapshot: KnowledgeBuildTaskSnapshot
) {
  const storage = safeLocalStorage();
  if (!storage) return;
  storage.setItem(BUILD_TASK_PREFIX + sessionId, JSON.stringify(snapshot));
  window.dispatchEvent(new Event("bilimind:build-task-change"));
}
