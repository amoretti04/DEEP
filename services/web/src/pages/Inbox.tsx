import { useEffect, useState } from "react";
import { api, type EventRow } from "../api/client";

export function Inbox({ onOpenProceeding }: { onOpenProceeding?: (pid: string) => void } = {}) {
  const [events, setEvents] = useState<EventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listEvents({ limit: 100 })
      .then((resp) => {
        if (cancelled) return;
        setEvents(resp.items);
        setTotal(resp.total);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // j/k navigation across the list. Analysts want keyboard-first.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (document.activeElement?.tagName === "INPUT") return;
      if (e.key === "j") setSelected((s) => Math.min(s + 1, events.length - 1));
      if (e.key === "k") setSelected((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [events.length]);

  if (loading) return <CenterMessage>Loading events…</CenterMessage>;
  if (error) return <CenterMessage tone="error">API error: {error}</CenterMessage>;
  if (events.length === 0)
    return (
      <CenterMessage tone="muted">
        No events yet. The inbox populates once connectors start running — enable a
        source with <code className="text-blue-300">legal_review.verdict=approved</code>{" "}
        and let the scheduler pick it up.
      </CenterMessage>
    );

  return (
    <div className="grid h-full grid-cols-[1fr_2fr] divide-x divide-neutral-800">
      <ol className="overflow-y-auto font-mono text-sm">
        {events.map((ev, i) => (
          <li key={ev.event_pid}>
            <button
              type="button"
              onClick={() => setSelected(i)}
              className={`block w-full border-b border-neutral-900 px-4 py-3 text-left ${
                i === selected
                  ? "bg-blue-500/10 ring-1 ring-blue-500/30"
                  : "hover:bg-neutral-900/60"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="truncate text-neutral-200">
                  {eventIcon(ev.event_type)} {shortType(ev.event_type)}
                </span>
                <span className="text-[11px] text-neutral-500">
                  {fmtDate(ev.occurred_at_utc)}
                </span>
              </div>
              <div className="mt-1 truncate text-neutral-500">
                {ev.description_original}
              </div>
            </button>
          </li>
        ))}
      </ol>
      <EventDetail event={events[selected]} total={total} onOpenProceeding={onOpenProceeding} />
    </div>
  );
}

function EventDetail({
  event,
  total,
  onOpenProceeding,
}: {
  event: EventRow | undefined;
  total: number;
  onOpenProceeding?: (pid: string) => void;
}) {
  if (!event) return <CenterMessage>Select an event</CenterMessage>;
  return (
    <div className="space-y-6 overflow-y-auto p-6 font-mono text-sm">
      <header className="space-y-1">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs uppercase tracking-widest text-neutral-500">
              Event {total > 0 && `of ${total}`}
            </div>
            <h1 className="text-xl text-neutral-100">{shortType(event.event_type)}</h1>
            <div className="text-neutral-500">{fmtDate(event.occurred_at_utc)}</div>
          </div>
          {onOpenProceeding && (
            <button
              type="button"
              onClick={() => onOpenProceeding(event.proceeding_pid)}
              className="rounded bg-blue-500/20 px-3 py-1 text-xs text-blue-200 hover:bg-blue-500/30"
            >
              Open proceeding →
            </button>
          )}
        </div>
      </header>

      <Section title="Original">
        <p className="whitespace-pre-wrap leading-relaxed text-neutral-200">
          {event.description_original}
        </p>
        {event.language_original && (
          <div className="mt-2 text-xs text-neutral-500">
            Language: <span className="text-neutral-300">{event.language_original}</span>
          </div>
        )}
      </Section>

      {event.description_english && (
        <Section title="English">
          <p className="whitespace-pre-wrap leading-relaxed text-neutral-300">
            {event.description_english}
          </p>
        </Section>
      )}

      <Section title="IDs">
        <dl className="grid grid-cols-[120px_1fr] gap-y-1 text-xs">
          <dt className="text-neutral-500">event_pid</dt>
          <dd className="text-neutral-300">{event.event_pid}</dd>
          <dt className="text-neutral-500">proceeding_pid</dt>
          <dd className="text-neutral-300">{event.proceeding_pid}</dd>
        </dl>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-xs uppercase tracking-widest text-neutral-500">{title}</h2>
      {children}
    </section>
  );
}

function CenterMessage({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "muted" | "error";
}) {
  const color =
    tone === "error" ? "text-red-400" : tone === "muted" ? "text-neutral-400" : "text-neutral-300";
  return (
    <div className={`flex h-full items-center justify-center p-10 text-center ${color}`}>
      <div className="max-w-xl font-mono text-sm">{children}</div>
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function shortType(t: string): string {
  return t.replace(/_/g, " ");
}

function eventIcon(t: string): string {
  if (t.includes("filing")) return "▸";
  if (t.includes("auction")) return "⧫";
  if (t.includes("plan")) return "◆";
  if (t.includes("meeting")) return "○";
  return "·";
}
