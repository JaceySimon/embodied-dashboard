import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "具身智能看板 - Embodied AI Dashboard",
  description: "跟踪具身智能 / VLA 方向的最新进展",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-gray-950 text-gray-200">
        <header className="border-b border-gray-800">
          <div className="max-w-6xl mx-auto px-4 py-4">
            <a href="/" className="text-xl font-bold text-white">
              具身智能看板
            </a>
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
