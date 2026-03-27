"use client";

import { authApi } from "@/lib/api";
import { useTheme } from "@/components/ThemeProvider";
import { clearAuthSession, useAuthSession } from "@/lib/session";

/**
 * 用户状态栏 — 显示当前登录用户 + 主题切换 + 退出按钮
 * 放在各页面的 topbar-actions 区域中
 */
export default function UserTopbar() {
  const { userName: user, sessionId: session } = useAuthSession();
  const { theme, toggleTheme } = useTheme();

  const handleLogout = () => {
    if (session) authApi.logout(session).catch(() => {});
    clearAuthSession();
    window.location.href = "/";
  };

  return (
    <>
      <button
        onClick={toggleTheme}
        className="btn-icon"
        title={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
        style={{ marginRight: 4 }}
      >
        {theme === "dark" ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="12" cy="12" r="5" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
          </svg>
        )}
      </button>
      {user && (
        <>
          <span className="user-chip">
            <span>已登录</span>
            <strong>{user}</strong>
          </span>
          <button onClick={handleLogout} className="btn-icon" title="退出登录 / 切换账户">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" style={{ width: 18, height: 18 }}>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </>
      )}
    </>
  );
}
