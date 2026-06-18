import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polis · 虚拟智能企业平台",
  description: "Polis 虚拟智能企业平台：一个目标，开出一家 AI 虚拟公司，角色化智能体替你规划、协作、交付。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
