"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function NavSidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/workspace", label: "工作台", icon: "workspace", primary: true },
    { href: "/organizer", label: "整理中心", icon: "organizer", primary: true },
    { href: "/tree", label: "知识树", icon: "tree", primary: false },
  ];

  const icons: Record<string, React.ReactNode> = {
    workspace: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
    organizer: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 6h16" />
        <path d="M4 12h10" />
        <path d="M4 18h7" />
        <circle cx="18" cy="12" r="3" />
        <circle cx="14" cy="18" r="2" />
      </svg>
    ),
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
