import type { Metadata } from "next";
import { DM_Sans, Syne } from "next/font/google";
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
        {children}
      </body>
    </html>
  );
}
