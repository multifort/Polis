import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polis",
  description: "多 Agent 协同平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
