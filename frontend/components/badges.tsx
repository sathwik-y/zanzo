import { CATEGORY_META } from "@/lib/api";

export function CategoryBadge({ category }: { category?: string | null }) {
  if (!category) return null;
  const meta = CATEGORY_META[category] ?? CATEGORY_META.OTHER;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${meta.color} ${meta.ring}`}>
      {meta.label}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  if (status === "COMPLETED") return null;
  const failed = status.startsWith("FAILED");
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${
        failed
          ? "bg-red-500/15 text-red-300 ring-red-500/30"
          : "bg-yellow-500/10 text-yellow-300 ring-yellow-500/25 animate-pulse"
      }`}
    >
      {failed ? status.replace("FAILED_", "failed: ").toLowerCase() : status.toLowerCase()}
    </span>
  );
}

export function SourceChip({ source }: { source: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-zinc-800/80 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
      {source === "DM" ? "via DM" : "saved"}
    </span>
  );
}
