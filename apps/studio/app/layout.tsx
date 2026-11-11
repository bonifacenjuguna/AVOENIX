import type { Metadata, Viewport } from "next";
import "./globals.css";
import { NO_FLASH_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = { title: "AVOENIX Studio", description: "Admin console for the AVOENIX algorithmic intelligence system (v0.0.1)", robots: { index: false, follow: false } };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: NO_FLASH_SCRIPT }} /></head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
