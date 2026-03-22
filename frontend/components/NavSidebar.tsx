"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function NavSidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/tree", label: "知识树", icon: "tree", primary: true },
    { href: "/learning-path", label: "学习路径", icon: "path", primary: true },
    { href: "/search", label: "搜索", icon: "search", primary: false },
    { href: "/chat", label: "知识问答", icon: "chat", primary: false },
    { href: "/game", label: "知识挑战", icon: "game", primary: false },
    { href: "/review", label: "间隔复习", icon: "review", primary: false },
  ];

  const icons: Record<string, React.ReactNode> = {
    tree: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="5" r="2" />
        <circle cx="7" cy="14" r="1.5" />
        <circle cx="17" cy="14" r="1.5" />
        <path d="M12 7v3M9.5 12.5l-1.5 1M14.5 12.5l1.5 1" />
        <circle cx="5" cy="20" r="1.2" />
        <circle cx="9.5" cy="20" r="1.2" />
        <circle cx="17" cy="20" r="1.2" />
        <path d="M6.2 15.5l-0.5 3.3M8.2 15.5l0.5 3.3M17 15.5v3.3" />
      </svg>
    ),
    path: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="5" cy="6" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="18" r="2" />
        <path d="M7 7l3 3M14 13l3 3" />
      </svg>
    ),
    search: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
      </svg>
    ),
    chat: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
    ),
    game: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="2" y="6" width="20" height="12" rx="3" />
        <circle cx="9" cy="12" r="2" />
        <path d="M15 10v4M13 12h4" />
      </svg>
    ),
    review: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 3" />
        <path d="M16.5 3.5l1 2M7.5 3.5l-1 2" />
      </svg>
    ),
  };

  return (
    <nav className="nav-sidebar">
      <div className="nav-primary-group">
        {links.filter(l => l.primary).map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`nav-item ${pathname === link.href ? "active" : ""}`}
          >
            {icons[link.icon]}
            <span>{link.label}</span>
          </Link>
        ))}
      </div>
      <div className="nav-divider" />
      <div className="nav-secondary-group">
        {links.filter(l => !l.primary).map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`nav-item nav-item-secondary ${pathname === link.href ? "active" : ""}`}
          >
            {icons[link.icon]}
            <span>{link.label}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}
