import type { Metadata } from "next";
import "./globals.css";
import { LangProvider } from "@/lib/i18n";
import Header from "@/components/Header";
import DisclaimerBanner from "@/components/DisclaimerBanner";

export const metadata: Metadata = {
  title: "Thai 2D Prediction Engine",
  description:
    "Statistical analysis of historical Thai 2D data. Model scores are estimates, not guarantees.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="my">
      <body className="min-h-screen bg-ink-950">
        <LangProvider>
          <Header />
          <main className="mx-auto max-w-6xl px-4 pb-16">{children}</main>
          <DisclaimerBanner />
        </LangProvider>
      </body>
    </html>
  );
}
