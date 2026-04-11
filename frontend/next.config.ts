import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 关闭开发模式左下角的 Next.js 浮动指示器
  devIndicators: false,

  // 允许加载外部图片
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**.hdslb.com",
      },
      {
        protocol: "https",
        hostname: "**.bilivideo.com",
      },
      {
        protocol: "http",
        hostname: "localhost",
      },
    ],
  },
};

export default nextConfig;
