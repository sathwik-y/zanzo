import Link from "next/link";
import { ImageOff } from "lucide-react";
import { extractionHeadline, Item } from "@/lib/api";
import { CategoryBadge, SourceChip, StatusChip } from "./badges";

function cardSubtitle(item: Item): string | null {
  const e = item.extraction;
  if (!e) return null;
  if (item.category === "EVENT") {
    const bits = [e["starts_at"], e["venue_name"], e["city"]].filter(Boolean) as string[];
    if (bits.length) return bits.join(" · ");
  }
  if (item.category === "RECIPE") {
    const n = Array.isArray(e["ingredients"]) ? e["ingredients"].length : 0;
    if (n) return `${n} ingredients`;
  }
  if (item.category === "TRAVEL") {
    const n = Array.isArray(e["places_mentioned"]) ? e["places_mentioned"].length : 0;
    if (n) return `${n} places mentioned`;
  }
  return (e.summary as string) ?? null;
}

export function ItemCard({ item }: { item: Item }) {
  const headline = extractionHeadline(item) ?? item.caption?.slice(0, 80) ?? item.media_pk;
  const subtitle = cardSubtitle(item);
  return (
    <Link
      href={`/items/${item.id}`}
      className="group flex gap-4 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-3 transition-colors hover:border-zinc-700 hover:bg-zinc-900"
    >
      <div className="relative h-28 w-20 shrink-0 overflow-hidden rounded-lg bg-zinc-800">
        {item.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.thumbnail_url}
            alt=""
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-zinc-600">
            <ImageOff className="size-5" />
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1 py-1">
        <div className="flex flex-wrap items-center gap-2">
          <CategoryBadge category={item.category} />
          <StatusChip status={item.status} />
          <SourceChip source={item.source} />
          {item.match_reason && (
            <span className="text-[10px] text-zinc-500">matched: {item.match_reason}</span>
          )}
        </div>
        <h3 className="mt-1.5 line-clamp-1 font-medium text-zinc-100">{headline}</h3>
        {subtitle && <p className="mt-0.5 line-clamp-2 text-sm text-zinc-400">{subtitle}</p>}
        <p className="mt-1 text-xs text-zinc-500">
          {item.author_username ? `@${item.author_username}` : ""}
          {item.saved_at ? ` · ${new Date(item.saved_at).toLocaleDateString()}` : ""}
        </p>
      </div>
    </Link>
  );
}
