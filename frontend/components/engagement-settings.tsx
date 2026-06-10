"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, Loader2, Save } from "lucide-react";
import { api, EngagementConfig, EngagementRow, ENGAGEMENT_STATUS_LABEL } from "@/lib/api";

const NUMERIC_FIELDS: { key: keyof EngagementConfig; label: string; hint?: string }[] = [
  { key: "daily_follow_cap", label: "Follows / day" },
  { key: "daily_comment_cap", label: "Comments / day" },
  { key: "daily_dm_cap", label: "DMs / day" },
  { key: "min_delay_s", label: "Min delay (s)", hint: "between actions" },
  { key: "max_delay_s", label: "Max delay (s)" },
  { key: "dm_fallback_after_s", label: "DM fallback (s)", hint: "DM keyword if no reply" },
];

export function EngagementSettings() {
  const [config, setConfig] = useState<EngagementConfig | null>(null);
  const [rows, setRows] = useState<EngagementRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const [c, r] = await Promise.all([
      api<EngagementConfig>("engagement/config"),
      api<EngagementRow[]>("engagement"),
    ]);
    setConfig(c);
    setRows(r);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => api<EngagementRow[]>("engagement").then(setRows).catch(() => {}), 15000);
    return () => clearInterval(t);
  }, [load]);

  async function save() {
    if (!config) return;
    setSaving(true);
    try {
      setConfig(await api<EngagementConfig>("engagement/config", { method: "PUT", body: JSON.stringify(config) }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  if (!config) return null;

  const deferred = rows.filter((r) => ["PENDING", "FOLLOWING"].includes(r.status)).length;

  return (
    <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-medium">
          <Bot className="size-4 text-violet-400" /> Auto-engagement
        </h2>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
            className="size-4 accent-violet-500"
          />
          Enabled
        </label>
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        When a saved reel says &quot;comment X / follow me for the link&quot;, the bot account follows and
        comments automatically, then harvests the creator&apos;s reply into Resources. Caps keep it ban-safe.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {NUMERIC_FIELDS.map((f) => (
          <label key={f.key} className="text-sm">
            <span className="text-zinc-400">{f.label}</span>
            {f.hint && <span className="ml-1 text-[10px] text-zinc-600">{f.hint}</span>}
            <input
              type="number"
              value={config[f.key] as number}
              onChange={(e) => setConfig({ ...config, [f.key]: Number(e.target.value) })}
              className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-zinc-200 outline-none focus:border-violet-500/60"
            />
          </label>
        ))}
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="mt-4 flex items-center gap-2 rounded-lg bg-violet-500/20 px-3 py-1.5 text-sm text-violet-100 hover:bg-violet-500/30 disabled:opacity-50"
      >
        {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
        {saved ? "Saved" : "Save caps"}
      </button>

      {rows.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
            <span>Recent engagements</span>
            {deferred > 0 && <span>{deferred} waiting on cap, will retry</span>}
          </div>
          <div className="space-y-1.5">
            {rows.slice(0, 8).map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg bg-zinc-800/50 px-3 py-1.5 text-sm">
                <span className="text-zinc-300">
                  @{r.creator_username} · <span className="font-mono text-violet-300">{r.keyword}</span>
                </span>
                <span className="text-xs text-zinc-400">
                  {ENGAGEMENT_STATUS_LABEL[r.status] ?? r.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
