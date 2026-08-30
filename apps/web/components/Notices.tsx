"use client";

import { useLang, type DictKey } from "@/lib/i18n";

export function Notice({
  kind,
  children,
}: {
  kind: "warn" | "error" | "info";
  children: React.ReactNode;
}) {
  const styles = {
    warn: "border-accent-amber/40 bg-accent-amber/10 text-amber-200",
    error: "border-accent-red/40 bg-accent-red/10 text-red-200",
    info: "border-accent-blue/40 bg-accent-blue/10 text-blue-200",
  }[kind];
  return (
    <div className={`mb-4 rounded-lg border px-4 py-2.5 text-xs font-medium ${styles}`}>
      {children}
    </div>
  );
}

export function StaleNotice({ stale }: { stale?: boolean }) {
  const { t } = useLang();
  if (!stale) return null;
  return <Notice kind="warn">⚠ {t("stale")}</Notice>;
}
