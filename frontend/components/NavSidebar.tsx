"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function NavSidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/tree", label: "知识树", icon: "tree" },
    { href: "/learning-path", label: "学习路径", icon: "path" },
    { href: "/search", label: "搜索", icon: "search" },
    { href: "/chat", label: "问答", icon: "chat" },
  ];

  const icons: Record<string, React.ReactNode> = {
    tree: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 3v18M12 7l-4 4M12 7l4 4M12 13l-6 5M12 13l6 5" />
      </svg>
    ),
    path: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M9 20l-5.5-5.5L9 9M15 4l5.5 5.5L15 15" />
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
  };

  return (
    <nav className="nav-sidebar">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={`nav-item ${pathname === link.href ? "active" : ""}`}
        >
          {icons[link.icon]}
          <span>{link.label}</span>
        </Link>
      ))}
    </nav>
  );
}
