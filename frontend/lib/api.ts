export type Extraction = Record<string, unknown> & {
  summary?: string;
  title?: string;
  dish_name?: string;
  destination?: string;
  topic?: string;
  subject?: string;
};

export type Item = {
  id: string;
  media_pk: string;
  media_type: string;
  source: "SAVED" | "DM";
  instagram_url?: string | null;
  author_username?: string | null;
  author_full_name?: string | null;
  caption?: string | null;
  category?: string | null;
  category_confidence?: number | null;
  status: string;
  archived: boolean;
  saved_at?: string | null;
  ingested_at: string;
  thumbnail_url?: string | null;
  extraction?: Extraction | null;
  match_reason?: string | null;
};

export type TranscriptSegment = { start: number; end: number; text: string };

export type ItemDetail = Item & {
  hashtags?: string[] | null;
  post_created_at?: string | null;
  transcript?: string | null;
  transcript_segments?: TranscriptSegment[] | null;
  transcript_lang?: string | null;
  error_log?: { stage: string; error: string } | null;
  media: { kind: string; url: string; bytes?: number | null }[];
};

export type ItemList = { items: Item[]; total: number; limit: number; offset: number };

export type Stats = {
  total_items: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  failed_count: number;
  llm_cost_total_usd: number;
  llm_cost_month_usd: number;
  items_last_7_days: number;
};

export type PollerStatus = {
  status: string;
  last_run_at?: string | null;
  last_new_items?: number | null;
  last_error?: string | null;
  queue_depth?: number | null;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api/backend/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body.slice(0, 300)}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const CATEGORIES = [
  "EDUCATIONAL",
  "EVENT",
  "RECIPE",
  "TRAVEL",
  "TECH_REFERENCE",
  "OTHER",
] as const;

export const CATEGORY_META: Record<
  string,
  { label: string; slug: string; color: string; ring: string }
> = {
  EDUCATIONAL: { label: "Educational", slug: "educational", color: "bg-sky-500/15 text-sky-300", ring: "ring-sky-500/30" },
  EVENT: { label: "Event", slug: "events", color: "bg-violet-500/15 text-violet-300", ring: "ring-violet-500/30" },
  RECIPE: { label: "Recipe", slug: "recipes", color: "bg-amber-500/15 text-amber-300", ring: "ring-amber-500/30" },
  TRAVEL: { label: "Travel", slug: "travel", color: "bg-emerald-500/15 text-emerald-300", ring: "ring-emerald-500/30" },
  TECH_REFERENCE: { label: "Tech", slug: "tech", color: "bg-rose-500/15 text-rose-300", ring: "ring-rose-500/30" },
  OTHER: { label: "Other", slug: "other", color: "bg-zinc-500/15 text-zinc-300", ring: "ring-zinc-500/30" },
};

export const SLUG_TO_CATEGORY: Record<string, string> = Object.fromEntries(
  Object.entries(CATEGORY_META).map(([cat, meta]) => [meta.slug, cat])
);

export function extractionHeadline(item: Item): string | null {
  const e = item.extraction;
  if (!e) return null;
  return (e.title || e.dish_name || e.destination || e.topic || e.subject || null) as string | null;
}
