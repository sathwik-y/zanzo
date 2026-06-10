"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, SearchX } from "lucide-react";
import { api, CATEGORIES, CATEGORY_META, Item, ItemList } from "@/lib/api";
import { ItemCard } from "./item-card";

const PAGE = 20;

export function Feed({
  fixedCategory,
  fixedStatus,
  header,
}: {
  fixedCategory?: string;
  fixedStatus?: string;
  header?: React.ReactNode;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState(fixedCategory ?? "");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(
    async (offset: number, query: string, cat: string) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        params.set("limit", String(PAGE));
        params.set("offset", String(offset));
        if (query.trim()) params.set("search", query.trim());
        if (cat) params.set("category", cat);
        if (fixedStatus) params.set("status", fixedStatus);
        const data = await api<ItemList>(`items?${params}`);
        setItems((prev) => (offset === 0 ? data.items : [...prev, ...data.items]));
        setTotal(data.total);
      } catch (e) {
        setError(e instanceof Error ? e.message : "failed to load");
      } finally {
        setLoading(false);
      }
    },
    [fixedStatus]
  );

  useEffect(() => {
    load(0, "", fixedCategory ?? "");
  }, [load, fixedCategory]);

  function onSearch(value: string) {
    setSearch(value);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => load(0, value, category), 350);
  }

  function onCategory(value: string) {
    setCategory(value);
    load(0, search, value);
  }

  return (
    <div>
      {header}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder='Search your saves... try "that tokyo ramen place"'
          className="w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-900/70 px-3.5 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none focus:border-violet-500/60"
        />
        {!fixedCategory && (
          <select
            value={category}
            onChange={(e) => onCategory(e.target.value)}
            className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-300 outline-none focus:border-violet-500/60"
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_META[c].label}
              </option>
            ))}
          </select>
        )}
        {!loading && (
          <span className="text-xs text-zinc-500">
            {total} item{total === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex flex-col gap-3">
        {items.map((item) => (
          <ItemCard key={item.id} item={item} />
        ))}
      </div>

      {loading && (
        <div className="flex justify-center py-10 text-zinc-500">
          <Loader2 className="size-6 animate-spin" />
        </div>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="flex flex-col items-center gap-2 py-16 text-zinc-500">
          <SearchX className="size-8" />
          <p className="text-sm">
            {search ? "Nothing matched that search." : "Nothing here yet. Save a reel on Instagram and it will show up within minutes."}
          </p>
        </div>
      )}

      {!loading && !search && items.length < total && (
        <div className="flex justify-center pt-6">
          <button
            onClick={() => load(items.length, search, category)}
            className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
