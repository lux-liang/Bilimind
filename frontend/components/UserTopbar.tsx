"use client";

import { useState, useEffect } from "react";
import { authApi } from "@/lib/api";

/**
 * 用户状态栏 — 显示当前登录用户 + 切换账户 / 退出按钮
 * 放在各页面的 topbar-actions 区域中
 */
export default function UserTopbar() {
  const [user, setUser] = useState<string | null>(null);
  const [session, setSession] = useState<string | null>(null);

  useEffect(() => {
    setUser(localStorage.getItem("bili_user"));
    setSession(localStorage.getItem("bili_session"));
  }, []);

  const handleLogout = () => {
    if (session) authApi.logout(session).catch(() => {});
    localStorage.removeItem("bili_session");
    localStorage.removeItem("bili_user");
    window.location.href = "/";
  };

  if (!user) return null;

  return (
    <>
      <span className="user-chip">
        <span>已登录</span>
        <strong>{user}</strong>
      </span>
      <button onClick={handleLogout} className="btn-icon" title="退出登录 / 切换账户">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" style={{ width: 18, height: 18 }}>
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
      </button>
    </>
  );
}
