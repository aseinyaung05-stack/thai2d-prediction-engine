"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLang } from "@/lib/i18n";

const LINKS = [
  { href: "/", key: "dashboard" as const },
  { href: "/history", key: "history" as const },
  { href: "/backtest", key: "backtest" as const },
  { href: "/status", key: "status" as const },
];

export default function Header() {
  const { lang, setLang, t } = useLang();
  const pathname = usePathname();

  return (
    <header className="border-b border-ink-700 bg-ink-900/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <div className="mr-auto">
          <h1 className="text-sm font-bold tracking-wide text-slate-100 sm:text-base">
            {t("title")}
          </h1>
          <p className="text-[11px] text-slate-500">{t("subtitle")}</p>
        </div>

        <button
          onClick={() => setLang(lang === "mm" ? "en" : "mm")}
          className="badge border border-ink-700 bg-ink-800 text-slate-300 hover:bg-ink-700"
          aria-label="toggle language"
        >
          {lang === "mm" ? "EN" : "မြန်မာ"}
        </button>

        <nav className="flex w-full gap-1 overflow-x-auto text-xs sm:w-auto">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 font-medium transition-colors ${
                pathname === l.href
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "text-slate-400 hover:bg-ink-800 hover:text-slate-200"
              }`}
            >
              {t(l.key)}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
