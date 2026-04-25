import { useEffect, useMemo, useState } from "react";
import { api, type CountsByDimension, type SourceSummary } from "../api/client";

export function SourceRegistry() {
  const [items, setItems] = useState<SourceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<CountsByDimension | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [country, setCountry] = useState<string>("");
  const [tier, setTier] = useState<number | "">("");
  const [category, setCategory] = useState<string>("");
  const [priorityOnly, setPriorityOnly] = useState<boolean>(true);
  const [search, setSearch] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const query = {
      country: country || undefined,
      tier: typeof tier === "number" ? tier : undefined,
      category: category || undefined,
      in_priority_scope: priorityOnly ? true : undefined,
      q: search || undefined,
      limit: 200,
    };
    Promise.all([api.listSources(query), api.sourceCounts()])
      .then(([list, c]) => {
        if (cancelled) return;
        setItems(list.items);
        setTotal(list.total);
        setCounts(c);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [country, tier, category, priorityOnly, search]);

  return (
    <div className="grid h-full grid-cols-[280px_1fr] divide-x divide-neutral-800">
      <aside className="space-y-6 overflow-y-auto p-4 font-mono text-sm">
        <CountsPanel counts={counts} />
        <FiltersPanel
          country={country}
          setCountry={setCountry}
          tier={tier}
          setTier={setTier}
          category={category}
          setCategory={setCategory}
          priorityOnly={priorityOnly}
          setPriorityOnly={setPriorityOnly}
          search={search}
          setSearch={setSearch}
        />
      </aside>
      <div className="flex h-full flex-col">
        <div className="border-b border-neutral-800 px-4 py-2 font-mono text-xs text-neutral-500">
          {loading ? "Loading…" : error ? <span className="text-red-400">{error}</span> : `${items.length} of ${total} matching`}
        </div>
        <div className="flex-1 overflow-y-auto">
          <SourcesTable items={items} />
        </div>
      </div>
    </div>
  );
}

function CountsPanel({ counts }: { counts: CountsByDimension | null }) {
  if (!counts) return null;
  const topCountries = Object.entries(counts.by_country).slice(0, 8);
  const byTier = Object.entries(counts.by_tier).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="space-y-3">
      <h3 className="text-xs uppercase tracking-widest text-neutral-500">Registry</h3>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Total" value={counts.total} />
        <Stat label="Priority" value={counts.in_priority_scope} tone="blue" />
        <Stat label="Enabled" value={counts.enabled} tone="green" />
      </div>
      <div className="space-y-1 pt-2">
        <div className="text-[11px] text-neutral-500">By tier</div>
        {byTier.map(([t, n]) => (
          <Row key={t} label={`T${t}`} value={n} />
        ))}
      </div>
      <div className="space-y-1 pt-2">
        <div className="text-[11px] text-neutral-500">Top countries</div>
        {topCountries.map(([c, n]) => (
          <Row key={c} label={c} value={n} />
        ))}
      </div>
    </div>
  );
}

function FiltersPanel(props: {
  country: string;
  setCountry: (s: string) => void;
  tier: number | "";
  setTier: (t: number | "") => void;
  category: string;
  setCategory: (s: string) => void;
  priorityOnly: boolean;
  setPriorityOnly: (b: boolean) => void;
  search: string;
  setSearch: (s: string) => void;
}) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs uppercase tracking-widest text-neutral-500">Filters</h3>
      <label className="block">
        <span className="text-[11px] text-neutral-500">Search</span>
        <input
          type="text"
          value={props.search}
          onChange={(e) => props.setSearch(e.target.value)}
          placeholder="tribunale / bolsa / gazette…"
          className="mt-1 w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-blue-500"
        />
      </label>
      <FilterSelect
        label="Country"
        value={props.country}
        onChange={props.setCountry}
        options={["", "IT", "DE", "FR", "UK", "ES", "NL", "CH", "EU", "AE", "SA", "XX"]}
      />
      <FilterSelect
        label="Tier"
        value={props.tier === "" ? "" : String(props.tier)}
        onChange={(v) => props.setTier(v === "" ? "" : Number(v))}
        options={["", "1", "2", "3"]}
      />
      <FilterSelect
        label="Category"
        value={props.category}
        onChange={props.setCategory}
        options={["", "GAZ", "COURT", "INS-REG", "AUCT", "REG", "CRED", "NEWS", "REGU", "MKT"]}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={props.priorityOnly}
          onChange={(e) => props.setPriorityOnly(e.target.checked)}
          className="accent-blue-500"
        />
        <span className="text-neutral-300">Priority scope only (EU-7 + EU)</span>
      </label>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-neutral-500">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 focus:border-blue-500"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o === "" ? "— all —" : o}
          </option>
        ))}
      </select>
    </label>
  );
}

function Stat({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "blue" | "green" }) {
  const color =
    tone === "blue" ? "text-blue-300" : tone === "green" ? "text-emerald-300" : "text-neutral-100";
  return (
    <div className="rounded border border-neutral-800 bg-neutral-950 p-2">
      <div className={`font-mono text-lg ${color}`}>{value.toLocaleString()}</div>
      <div className="text-[10px] uppercase tracking-widest text-neutral-500">{label}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-neutral-400">{label}</span>
      <span className="font-mono text-neutral-200">{value}</span>
    </div>
  );
}

function SourcesTable({ items }: { items: SourceSummary[] }) {
  const grouped = useMemo(() => {
    const byCountry: Record<string, SourceSummary[]> = {};
    for (const s of items) {
      byCountry[s.country] = byCountry[s.country] || [];
      byCountry[s.country].push(s);
    }
    return byCountry;
  }, [items]);

  return (
    <table className="w-full border-collapse font-mono text-xs">
      <thead className="sticky top-0 bg-neutral-950 text-left text-[10px] uppercase tracking-widest text-neutral-500">
        <tr>
          <th className="border-b border-neutral-800 px-3 py-2">Source</th>
          <th className="border-b border-neutral-800 px-3 py-2">Country</th>
          <th className="border-b border-neutral-800 px-3 py-2">Tier</th>
          <th className="border-b border-neutral-800 px-3 py-2">Category</th>
          <th className="border-b border-neutral-800 px-3 py-2">Connector</th>
          <th className="border-b border-neutral-800 px-3 py-2">Legal</th>
          <th className="border-b border-neutral-800 px-3 py-2">Status</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(grouped).map(([country, rows]) =>
          rows.map((s) => (
            <tr key={s.source_id} className="hover:bg-neutral-900/40">
              <td className="border-b border-neutral-900 px-3 py-2">
                <div className="text-neutral-100">{s.name}</div>
                <div className="text-[10px] text-neutral-500">{s.source_id}</div>
              </td>
              <td className="border-b border-neutral-900 px-3 py-2 text-neutral-300">{country}</td>
              <td className="border-b border-neutral-900 px-3 py-2">
                <TierBadge tier={s.tier} />
              </td>
              <td className="border-b border-neutral-900 px-3 py-2 text-neutral-300">{s.category}</td>
              <td className="border-b border-neutral-900 px-3 py-2 text-neutral-500">{s.connector.replace("Connector", "")}</td>
              <td className="border-b border-neutral-900 px-3 py-2">
                <LegalBadge verdict={s.legal_review_verdict} />
              </td>
              <td className="border-b border-neutral-900 px-3 py-2">
                {s.enabled ? (
                  <span className="text-emerald-400">enabled</span>
                ) : (
                  <span className="text-neutral-600">off</span>
                )}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function TierBadge({ tier }: { tier: number }) {
  const color = tier === 1 ? "bg-red-500/10 text-red-300" : tier === 2 ? "bg-amber-500/10 text-amber-300" : "bg-neutral-700/30 text-neutral-400";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] ${color}`}>T{tier}</span>;
}

function LegalBadge({ verdict }: { verdict: string }) {
  const color =
    verdict === "approved"
      ? "text-emerald-400"
      : verdict === "rejected"
        ? "text-red-400"
        : "text-amber-400";
  return <span className={`text-[11px] ${color}`}>{verdict}</span>;
}
