import { Extraction } from "@/lib/api";

function Row({ label, value }: { label: string; value?: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-32 shrink-0 text-zinc-500">{label}</span>
      <span className="text-zinc-200">{String(value)}</span>
    </div>
  );
}

function Pills({ label, values }: { label: string; values?: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <div className="text-sm">
      <span className="text-zinc-500">{label}</span>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {values.map((v, i) => (
          <span key={i} className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs text-zinc-300">
            {String(v)}
          </span>
        ))}
      </div>
    </div>
  );
}

function Bullets({ label, values }: { label: string; values?: unknown }) {
  if (!Array.isArray(values) || values.length === 0) return null;
  return (
    <div className="text-sm">
      <span className="text-zinc-500">{label}</span>
      <ul className="mt-1.5 space-y-1.5">
        {values.map((v, i) => (
          <li key={i} className="flex gap-2 text-zinc-200">
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-violet-400" />
            {String(v)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ExtractionView({ category, payload }: { category?: string | null; payload: Extraction }) {
  const p = payload as Record<string, unknown>;

  if (category === "EVENT") {
    return (
      <div className="space-y-3">
        <Row label="Title" value={p.title} />
        <Row label="Type" value={p.event_type} />
        <Row label="Starts" value={p.starts_at} />
        <Row label="Ends" value={p.ends_at} />
        <Row label="Venue" value={p.venue_name} />
        <Row label="Address" value={p.venue_address} />
        <Row label="City" value={[p.city, p.country].filter(Boolean).join(", ")} />
        <Row label="Price" value={p.price_info} />
        {Boolean(p.rsvp_url) && (
          <a href={String(p.rsvp_url)} target="_blank" className="block text-sm text-violet-300 underline">RSVP link</a>
        )}
        {Boolean(p.ticket_url) && (
          <a href={String(p.ticket_url)} target="_blank" className="block text-sm text-violet-300 underline">Tickets</a>
        )}
        <p className="text-sm text-zinc-300">{String(p.summary ?? "")}</p>
      </div>
    );
  }

  if (category === "RECIPE") {
    const ingredients = (p.ingredients ?? []) as { item: string; quantity?: string; notes?: string }[];
    return (
      <div className="space-y-4">
        <Row label="Dish" value={p.dish_name} />
        <Row label="Cuisine" value={p.cuisine} />
        <Row label="Servings" value={p.servings} />
        <Row label="Prep / cook" value={[p.prep_time_minutes && `${p.prep_time_minutes}m prep`, p.cook_time_minutes && `${p.cook_time_minutes}m cook`].filter(Boolean).join(" · ") || undefined} />
        {ingredients.length > 0 && (
          <div className="text-sm">
            <span className="text-zinc-500">Ingredients</span>
            <ul className="mt-1.5 space-y-1">
              {ingredients.map((ing, i) => (
                <li key={i} className="text-zinc-200">
                  {ing.quantity ? `${ing.quantity} ` : ""}{ing.item}
                  {ing.notes ? <span className="text-zinc-500"> — {ing.notes}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        )}
        <Bullets label="Steps" values={p.steps} />
        <Bullets label="Tips" values={p.tips} />
        <Pills label="Dietary" values={p.dietary_tags} />
      </div>
    );
  }

  if (category === "TRAVEL") {
    const places = (p.places_mentioned ?? []) as { name: string; type?: string; notes?: string }[];
    return (
      <div className="space-y-4">
        <Row label="Destination" value={p.destination} />
        <Row label="Where" value={[p.city, p.country].filter(Boolean).join(", ")} />
        <Row label="Best time" value={p.best_time_to_visit} />
        <Row label="Budget" value={p.budget_info} />
        {places.length > 0 && (
          <div className="text-sm">
            <span className="text-zinc-500">Places mentioned</span>
            <div className="mt-1.5 space-y-2">
              {places.map((pl, i) => (
                <div key={i} className="rounded-lg bg-zinc-800/60 px-3 py-2">
                  <span className="font-medium text-zinc-100">{pl.name}</span>
                  {pl.type && <span className="ml-2 text-xs text-zinc-500">{pl.type}</span>}
                  {pl.notes && <p className="mt-0.5 text-zinc-400">{pl.notes}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
        <Bullets label="Tips" values={p.tips} />
        <p className="text-sm text-zinc-300">{String(p.summary ?? "")}</p>
      </div>
    );
  }

  if (category === "TECH_REFERENCE") {
    const tools = (p.tools_mentioned ?? []) as { name: string; url?: string; category?: string }[];
    const snippets = (p.code_or_command_snippets ?? []) as { language: string; snippet: string; purpose: string }[];
    const comparisons = (p.comparisons_made ?? []) as { between: string[]; verdict: string }[];
    return (
      <div className="space-y-4">
        <Row label="Subject" value={p.subject} />
        {tools.length > 0 && (
          <div className="text-sm">
            <span className="text-zinc-500">Tools mentioned</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {tools.map((t, i) =>
                t.url ? (
                  <a key={i} href={t.url} target="_blank" className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs text-violet-300 underline">
                    {t.name}
                  </a>
                ) : (
                  <span key={i} className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs text-zinc-300">{t.name}</span>
                )
              )}
            </div>
          </div>
        )}
        {snippets.map((s, i) => (
          <div key={i} className="text-sm">
            <span className="text-zinc-500">{s.purpose} ({s.language})</span>
            <pre className="mt-1.5 overflow-x-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs text-emerald-300">{s.snippet}</pre>
          </div>
        ))}
        <Bullets label="Key insights" values={p.key_insights} />
        {comparisons.map((c, i) => (
          <div key={i} className="rounded-lg bg-zinc-800/60 px-3 py-2 text-sm">
            <span className="text-zinc-400">{(c.between ?? []).join(" vs ")}:</span>{" "}
            <span className="text-zinc-100">{c.verdict}</span>
          </div>
        ))}
        <p className="text-sm text-zinc-300">{String(p.summary ?? "")}</p>
      </div>
    );
  }

  if (category === "EDUCATIONAL") {
    const tools = (p.tools_or_resources_mentioned ?? []) as { name: string; url_or_handle?: string }[];
    return (
      <div className="space-y-4">
        <Row label="Topic" value={p.topic} />
        <Row label="Difficulty" value={p.difficulty} />
        <Bullets label="Key takeaways" values={p.key_takeaways} />
        <Pills label="Concepts" values={p.concepts_introduced} />
        {tools.length > 0 && (
          <Pills label="Resources" values={tools.map((t) => t.url_or_handle ? `${t.name} (${t.url_or_handle})` : t.name)} />
        )}
        <p className="text-sm text-zinc-300">{String(p.summary ?? "")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-zinc-300">{String(p.summary ?? "")}</p>
      {Boolean(p.notable_text) && (
        <blockquote className="border-l-2 border-zinc-700 pl-3 text-sm italic text-zinc-400">
          {String(p.notable_text)}
        </blockquote>
      )}
      <Pills label="Tags" values={p.tags} />
    </div>
  );
}
