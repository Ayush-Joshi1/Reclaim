import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reclaim | Recovery Dashboard",
  description: "Autonomous payment recovery dashboard for failed payments, risk evaluation, and recovery execution.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-900">{children}</body>
    </html>
  );
}
