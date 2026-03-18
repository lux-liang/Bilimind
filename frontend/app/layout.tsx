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
  title: "BiliMind - 知识树学习导航",
  description: "基于B站收藏视频自动构建的个人知识树与学习导航系统",
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
