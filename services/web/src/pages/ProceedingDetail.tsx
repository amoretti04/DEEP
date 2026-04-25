import { useEffect, useState } from "react";
import {
  api,
  type DocumentRow,
  type ProceedingDetail as ProceedingDetailT,
  type ProceedingEventWithContext,
  type SourceReferenceRow,
  type UserSettingsPayload,
} from "../api/client";

/**
 * Proceeding viewer. Shows events timeline, documents, and source
 * references. Every event can be toggled between original language and
 * the cached English translation; clicking translate on a document
 * calls the translate endpoint and shows the result inline.
 *
 * Translation toggle is hidden unless the user has opted in at Settings.
 * This mirrors ADR-0005: on-demand, per-user opt-in.
 */
export function ProceedingDetail({
  proceedingPid,
  settings,
  onBack,
}: {
  proceedingPid: string;
  settings: UserSettingsPayload | null;
  onBack: () => void;
}) {
  const [data, setData] = useState<ProceedingDetailT | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getProceeding(proceedingPid)
      .then((d) => !cancelled && setData(d))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [proceedingPid]);

  if (loading) return <Message>Loading proceeding…</Message>;
  if (error) return <Message tone="error">API error: {error}</Message>;
  if (!data) return <Message tone="muted">No proceeding.</Message>;

  const translationEnabled = settings?.translation.enabled ?? false;

  return (
    <div className="space-y-6 overflow-y-auto p-6 font-mono text-sm">
      <button
        type="button"
        onClick={onBack}
        className="text-xs text-neutral-500 hover:text-neutral-300"
      >
        ← Inbox
      </button>

      <Header data={data} />

      <Section title="Events">
        {data.events.length === 0 ? (
          <p className="text-neutral-500">No linked events.</p>
        ) : (
          <ol className="space-y-3">
            {data.events.map((e) => (
              <EventRow key={e.event_pid} event={e} canTranslate={translationEnabled} />
            ))}
          </ol>
        )}
      </Section>

      <Section title="Documents">
        {data.documents.length === 0 ? (
          <p className="text-neutral-500">No documents.</p>
        ) : (
          <ul className="space-y-3">
            {data.documents.map((d) => (
              <DocumentBlock
                key={d.document_pid}
                doc={d}
                canTranslate={translationEnabled}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Provenance">
        {data.source_references.length === 0 ? (
          <p className="text-neutral-500">No source references.</p>
        ) : (
          <ul className="space-y-2">
            {data.source_references.map((r) => (
              <ProvenanceRow key={r.record_uid} ref_={r} />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function Header({ data }: { data: ProceedingDetailT }) {
  return (
    <header className="space-y-2">
      <div className="text-xs uppercase tracking-widest text-neutral-500">
        Proceeding · {data.jurisdiction}
      </div>
      <h1 className="text-xl text-neutral-100">
        {data.court_name ?? "Unknown court"}
        {data.court_case_number && (
          <span className="ml-3 text-neutral-500">{data.court_case_number}</span>
        )}
      </h1>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone="blue">{data.proceeding_type}</Badge>
        <span className="text-neutral-500">{data.proceeding_type_original}</span>
        <StatusBadge status={data.status} />
      </div>
      {data.administrator_name && (
        <div className="text-xs text-neutral-400">
          {data.administrator_role ?? "Administrator"}:{" "}
          <span className="text-neutral-200">{data.administrator_name}</span>
        </div>
      )}
      {data.opened_at && (
        <div className="text-xs text-neutral-500">
          Opened {data.opened_at}
          {data.closed_at && ` · Closed ${data.closed_at}`}
        </div>
      )}
    </header>
  );
}

function EventRow({
  event,
  canTranslate,
}: {
  event: ProceedingEventWithContext;
  canTranslate: boolean;
}) {
  const [showEn, setShowEn] = useState(false);
  const hasEn = !!event.description_english;
  const displayed = showEn && hasEn ? event.description_english! : event.description_original;
  return (
    <li className="rounded border border-neutral-800 bg-neutral-900/50 p-3">
      <div className="flex items-center justify-between">
        <span className="text-neutral-300">{event.event_type.replace(/_/g, " ")}</span>
        <span className="text-xs text-neutral-500">{fmtDate(event.occurred_at_utc)}</span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-neutral-200">{displayed}</p>
      {canTranslate && hasEn && (
        <button
          type="button"
          onClick={() => setShowEn((v) => !v)}
          className="mt-2 text-xs text-blue-300 hover:text-blue-200"
        >
          {showEn
            ? `Show original (${event.language_original ?? "orig"})`
            : "Show EN translation"}
        </button>
      )}
    </li>
  );
}

function DocumentBlock({ doc, canTranslate }: { doc: DocumentRow; canTranslate: boolean }) {
  const [translated, setTranslated] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">(
    doc.has_translation ? "done" : "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState<boolean | null>(null);
  const [showEn, setShowEn] = useState(false);

  async function doTranslate() {
    setState("loading");
    setError(null);
    try {
      const r = await api.translateDocument(doc.document_pid);
      setTranslated(r.translated_text);
      setFromCache(r.from_cache);
      setShowEn(true);
      setState("done");
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  }

  return (
    <li className="rounded border border-neutral-800 bg-neutral-900/50 p-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-neutral-200">{doc.title}</div>
          <div className="text-[11px] text-neutral-500">
            {doc.document_type}
            {doc.filed_at && ` · ${doc.filed_at}`}
            {doc.language_original && ` · ${doc.language_original}`}
            {doc.page_count && ` · ${doc.page_count}p`}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {doc.url && (
            <a
              href={doc.url}
              className="text-xs text-neutral-400 hover:text-neutral-200"
              target="_blank"
              rel="noreferrer noopener"
            >
              open ↗
            </a>
          )}
          {canTranslate && state === "idle" && (
            <button
              type="button"
              onClick={doTranslate}
              className="rounded bg-blue-500/20 px-2 py-1 text-xs text-blue-200 hover:bg-blue-500/30"
            >
              Translate EN
            </button>
          )}
          {state === "loading" && (
            <span className="text-xs text-neutral-400">Translating…</span>
          )}
          {state === "done" && translated && (
            <button
              type="button"
              onClick={() => setShowEn((v) => !v)}
              className="text-xs text-blue-300 hover:text-blue-200"
            >
              {showEn ? "Original" : "EN"}
            </button>
          )}
        </div>
      </div>
      {state === "done" && translated && showEn && (
        <div className="mt-3 rounded bg-neutral-950 p-3">
          <div className="mb-1 text-[10px] uppercase tracking-widest text-neutral-500">
            English
            {fromCache !== null && (
              <span className="ml-2 text-neutral-600">
                {fromCache ? "(cached)" : "(just translated)"}
              </span>
            )}
          </div>
          <p className="whitespace-pre-wrap text-neutral-200">{translated}</p>
        </div>
      )}
      {state === "error" && error && (
        <p className="mt-2 text-xs text-red-400">Translation failed: {error}</p>
      )}
      {!canTranslate && (
        <p className="mt-1 text-[11px] text-neutral-600">
          Enable translation in Settings to view English.
        </p>
      )}
    </li>
  );
}

function ProvenanceRow({ ref_ }: { ref_: SourceReferenceRow }) {
  return (
    <li className="rounded border border-neutral-900 bg-neutral-950 p-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-neutral-300">{ref_.source_id}</span>
        <span className="text-neutral-600">{ref_.parser_version}</span>
      </div>
      <div className="mt-1 text-[11px] text-neutral-500">
        Fetched {fmtDate(ref_.fetched_at_utc)}
      </div>
      {ref_.source_url && (
        <a
          href={ref_.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1 block truncate text-[11px] text-blue-400 hover:text-blue-300"
        >
          {ref_.source_url}
        </a>
      )}
      {ref_.raw_object_key && (
        <div className="mt-1 truncate text-[11px] text-neutral-600">
          raw: {ref_.raw_object_key}
        </div>
      )}
    </li>
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

function Badge({ tone, children }: { tone: "blue"; children: React.ReactNode }) {
  const color = tone === "blue" ? "bg-blue-500/20 text-blue-300" : "";
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${color}`}>{children}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "open"
      ? "bg-emerald-500/10 text-emerald-300"
      : status === "closed"
        ? "bg-neutral-700/30 text-neutral-400"
        : "bg-amber-500/10 text-amber-300";
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${color}`}>{status}</span>;
}

function Message({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "muted" | "error";
}) {
  const c =
    tone === "error"
      ? "text-red-400"
      : tone === "muted"
        ? "text-neutral-400"
        : "text-neutral-300";
  return (
    <div className={`flex h-full items-center justify-center p-10 font-mono text-sm ${c}`}>
      {children}
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}
