import type { Metadata } from "next";
import { DM_Sans, Syne } from "next/font/google";

import { QueryProvider } from "@/providers/QueryProvider";
import "./globals.css";

const display = Syne({
  subsets: ["latin"],
  variable: "--font-display-loaded",
  weight: ["600", "700", "800"],
});

const body = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body-loaded",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "FAE",
  description: "Fully Autonomous Echo — voice agent",
  manifest: "/manifest.webmanifest",
  themeColor: "#0f6e56",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "FAE",
  },
  icons: {
    apple: "/icons/icon-192.png",
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${display.variable} ${body.variable} antialiased`}
        style={
          {
            ["--font-display" as string]: "var(--font-display-loaded), Syne, sans-serif",
            ["--font-body" as string]: "var(--font-body-loaded), 'DM Sans', sans-serif",
          } as React.CSSProperties
        }
      >
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
