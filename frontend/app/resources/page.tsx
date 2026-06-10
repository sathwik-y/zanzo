"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, ExternalLink, Gift, Link as LinkIcon, Loader2, MousePointerClick } from "lucide-react";
import { api, ENGAGEMENT_STATUS_LABEL, ResourceRow } from "@/lib/api";

export default function ResourcesPage() {
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api<ResourceRow[]>("resources"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const withResources = rows.filter((r) => r.resources.length > 0);
  const inProgress = rows.filter((r) => r.resources.length === 0);

  return (
    <div>
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Gift className="size-6 text-violet-400" /> Resources
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Links Zanzo fetched for you by following creators and commenting the keyword
          (&quot;comment GUIDE to get the link&quot;), then harvesting their reply.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>
      )}

      {loading && (
        <div className="flex justify-center py-10 text-zinc-500"><Loader2 className="size-6 animate-spin" /></div>
      )}

      {!loading && rows.length === 0 && !error && (
        <div className="flex flex-col items-center gap-2 py-16 text-zinc-500">
          <Gift className="size-8" />
          <p className="max-w-md text-center text-sm">
            No auto-engagements yet. When you save a reel that says &quot;comment X / follow me for
            the link&quot;, Zanzo follows the creator, comments the keyword, and the resource shows up here.
          </p>
        </div>
      )}

      {withResources.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">Harvested</h2>
          <div className="space-y-3">
            {withResources.map((r) => (
              <div key={r.item_id} className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4">
                <div className="flex items-start justify-between gap-3">
                  <Link href={`/items/${r.item_id}`} className="font-medium text-zinc-100 hover:underline">
                    {r.headline}
                  </Link>
                  <span className="shrink-0 text-xs text-zinc-500">@{r.creator_username} · {r.keyword}</span>
                </div>
                <ul className="mt-2 space-y-1.5">
                  {r.resources.map((res, i) => (
                    <li key={i}>
                      <a href={res.url} target="_blank" className="flex items-start gap-2 text-sm text-violet-300 underline break-all">
                        {res.source === "interaction_required" ? (
                          <MousePointerClick className="mt-0.5 size-3.5 shrink-0" />
                        ) : (
                          <LinkIcon className="mt-0.5 size-3.5 shrink-0" />
                        )}
                        {res.source === "interaction_required" ? "Claim in Instagram (tap required)" : res.url}
                      </a>
                      {res.text && <p className="mt-0.5 pl-5 text-xs text-zinc-500">{res.text}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      {inProgress.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">In progress</h2>
          <div className="space-y-2">
            {inProgress.map((r) => (
              <div key={r.item_id} className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-2.5">
                <Link href={`/items/${r.item_id}`} className="min-w-0 truncate text-sm text-zinc-200 hover:underline">
                  {r.headline}
                </Link>
                <span className="ml-3 flex shrink-0 items-center gap-1.5 text-xs text-zinc-400">
                  <CheckCircle2 className="size-3.5 text-zinc-600" />
                  @{r.creator_username} · {r.keyword} · {ENGAGEMENT_STATUS_LABEL[r.status] ?? r.status}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
