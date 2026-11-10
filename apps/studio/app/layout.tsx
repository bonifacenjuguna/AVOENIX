import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "AVOENIX Studio", description: "Admin console for the AVOENIX algorithmic intelligence system (v0.0.0)", robots: { index: false, follow: false } };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
