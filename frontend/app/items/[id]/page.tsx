"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Archive,
  ArchiveRestore,
  CalendarPlus,
  ClipboardCopy,
  ExternalLink,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api, CATEGORIES, CATEGORY_META, ItemDetail } from "@/lib/api";
import { CategoryBadge, SourceChip, StatusChip } from "@/components/badges";
import { ExtractionView } from "@/components/extraction-view";

export default function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    try {
      setItem(await api<ItemDetail>(`items/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    try {
      await fn();
    } catch (e) {
      alert(e instanceof Error ? e.message : "action failed");
    } finally {
      setBusy(null);
    }
  }

  if (error) {
    return <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>;
  }
  if (!item) {
    return (
      <div className="flex justify-center py-20 text-zinc-500">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  const video = item.media.find((m) => m.kind === "VIDEO");
  const image = item.media.find((m) => m.kind === "IMAGE");
  const isVideo = Boolean(video);
  const failed = item.status.startsWith("FAILED");

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <CategoryBadge category={item.category} />
          <StatusChip status={item.status} />
          <SourceChip source={item.source} />
          {item.category_confidence != null && item.category_confidence < 1 && (
            <span className="text-xs text-zinc-500">
              confidence {(item.category_confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>

        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-black">
          {isVideo ? (
            <video ref={videoRef} src={video!.url} controls className="mx-auto max-h-[70vh]" />
          ) : image || item.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={(image ?? { url: item.thumbnail_url! }).url} alt="" className="mx-auto max-h-[70vh]" />
          ) : (
            <div className="p-12 text-center text-sm text-zinc-600">media not available</div>
          )}
        </div>

        {failed && item.error_log && (
          <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
            <p className="font-medium">Processing failed at {item.error_log.stage}</p>
            <p className="mt-1 text-red-300/80">{item.error_log.error}</p>
          </div>
        )}

        {item.caption && (
          <section className="mt-6">
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">Caption</h2>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{item.caption}</p>
          </section>
        )}

        {item.transcript_segments && item.transcript_segments.length > 0 && (
          <section className="mt-6">
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
              Transcript {item.transcript_lang ? `(${item.transcript_lang})` : ""}
            </h2>
            <div className="max-h-72 space-y-1 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              {item.transcript_segments.map((seg, i) => (
                <button
                  key={i}
                  onClick={() => {
                    if (videoRef.current) {
                      videoRef.current.currentTime = seg.start;
                      videoRef.current.play();
                    }
                  }}
                  className="block w-full rounded px-2 py-1 text-left text-sm text-zinc-300 hover:bg-zinc-800"
                >
                  <span className="mr-2 font-mono text-xs text-violet-400">
                    {Math.floor(seg.start / 60)}:{String(Math.floor(seg.start % 60)).padStart(2, "0")}
                  </span>
                  {seg.text}
                </button>
              ))}
            </div>
          </section>
        )}
      </div>

      <aside className="space-y-6">
        {item.extraction && (
          <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">Extracted</h2>
            <ExtractionView category={item.category} payload={item.extraction} />
          </section>
        )}

        <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">Actions</h2>
          <div className="space-y-2">
            {item.category === "EVENT" && item.extraction?.["starts_at"] != null && (
              <ActionButton
                icon={CalendarPlus}
                label="Add to calendar (.ics)"
                busy={busy === "ics"}
                onClick={() =>
                  run("ics", async () => {
                    const resp = await fetch(`/api/backend/actions/event/${item.id}/add-to-calendar`, { method: "POST" });
                    if (!resp.ok) throw new Error(await resp.text());
                    const blob = await resp.blob();
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = "event.ics";
                    a.click();
                  })
                }
              />
            )}
            {item.category === "RECIPE" && item.extraction && (
              <ActionButton
                icon={ClipboardCopy}
                label="Copy recipe"
                busy={busy === "copy"}
                onClick={() =>
                  run("copy", async () => {
                    const e = item.extraction! as Record<string, unknown>;
                    const ingredients = ((e.ingredients ?? []) as { item: string; quantity?: string }[])
                      .map((i) => `- ${i.quantity ? i.quantity + " " : ""}${i.item}`)
                      .join("\n");
                    const steps = ((e.steps ?? []) as string[]).map((s, i) => `${i + 1}. ${s}`).join("\n");
                    await navigator.clipboard.writeText(
                      `${e.dish_name}\n\nIngredients:\n${ingredients}\n\nSteps:\n${steps}`
                    );
                  })
                }
              />
            )}
            {item.instagram_url && (
              <a
                href={item.instagram_url}
                target="_blank"
                className="flex w-full items-center gap-2.5 rounded-lg border border-zinc-700/80 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
              >
                <ExternalLink className="size-4" /> Open on Instagram
              </a>
            )}
            {failed && (
              <ActionButton
                icon={RefreshCw}
                label="Retry processing"
                busy={busy === "retry"}
                onClick={() =>
                  run("retry", async () => {
                    await api(`items/${item.id}/retry`, { method: "POST" });
                    await load();
                  })
                }
              />
            )}
            <ActionButton
              icon={item.archived ? ArchiveRestore : Archive}
              label={item.archived ? "Unarchive" : "Archive"}
              busy={busy === "archive"}
              onClick={() =>
                run("archive", async () => {
                  await api(`items/${item.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ archived: !item.archived }),
                  });
                  await load();
                })
              }
            />
            <ActionButton
              icon={Trash2}
              label="Delete from Recall"
              danger
              busy={busy === "delete"}
              onClick={() =>
                run("delete", async () => {
                  if (!confirm("Remove this item from Recall? (It stays saved on Instagram.)")) return;
                  await api(`items/${item.id}`, { method: "DELETE" });
                  router.push("/");
                })
              }
            />
          </div>
        </section>

        <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">Category</h2>
          <select
            value={item.category ?? "OTHER"}
            disabled={busy === "recat"}
            onChange={(e) =>
              run("recat", async () => {
                await api(`items/${item.id}/recategorize`, {
                  method: "POST",
                  body: JSON.stringify({ category: e.target.value }),
                });
                await load();
              })
            }
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-violet-500/60"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_META[c].label}
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs text-zinc-500">
            Changing the category re-runs extraction with the right schema.
          </p>
        </section>

        <section className="space-y-1.5 px-1 text-xs text-zinc-500">
          {item.author_username && <p>By @{item.author_username} {item.author_full_name ? `(${item.author_full_name})` : ""}</p>}
          {item.post_created_at && <p>Posted {new Date(item.post_created_at).toLocaleString()}</p>}
          {item.saved_at && <p>Saved {new Date(item.saved_at).toLocaleString()}</p>}
          <p>Ingested {new Date(item.ingested_at).toLocaleString()}</p>
          {item.hashtags && item.hashtags.length > 0 && <p>{item.hashtags.map((h) => `#${h}`).join(" ")}</p>}
        </section>
      </aside>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  busy,
  danger,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  busy?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
        danger
          ? "border-red-500/30 text-red-300 hover:bg-red-500/10"
          : "border-zinc-700/80 text-zinc-300 hover:bg-zinc-800"
      }`}
    >
      {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4" />}
      {label}
    </button>
  );
}
