"use client";

import { useLang } from "@/lib/i18n";

export default function DisclaimerBanner() {
  const { t } = useLang();
  return (
    <footer className="mt-10 border-t border-ink-700 bg-ink-900/60">
      <p className="mx-auto max-w-6xl px-4 py-4 text-[11px] leading-relaxed text-slate-500">
        ⚠️ {t("disclaimer")}
      </p>
    </footer>
  );
}
