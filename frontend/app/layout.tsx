import type { Metadata } from "next";
import { ZCOOL_XiaoWei, Noto_Sans_SC } from "next/font/google";
import "./globals.css";

const display = ZCOOL_XiaoWei({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
});

const body = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "BiliMind — 个人视频知识导航系统",
  description: "基于 B 站收藏视频自动构建知识树、规划学习路径、追溯视频片段证据的个人知识导航系统",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className={`${display.variable} ${body.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
