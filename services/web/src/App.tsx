import { useEffect, useState } from "react";
import { api, type UserSettingsPayload } from "./api/client";
import { Inbox } from "./pages/Inbox";
import { ProceedingDetail } from "./pages/ProceedingDetail";
import { SettingsPage } from "./pages/Settings";
import { SourceRegistry } from "./pages/SourceRegistry";

type Tab = "inbox" | "sources" | "settings";

const TABS: Array<{ id: Tab; label: string; hotkey: string }> = [
  { id: "inbox", label: "Inbox", hotkey: "1" },
  { id: "sources", label: "Sources", hotkey: "2" },
  { id: "settings", label: "Settings", hotkey: "3" },
];

/**
 * Root app shell.
 *
 * Holds:
 *  - active tab,
 *  - optional "viewing proceeding PID" overlay (set from Inbox → cleared on back),
 *  - user settings (fetched once on mount, mutated by Settings page, read by
 *    the viewer to decide whether the translation toggle is visible).
 */
export function App() {
  const [tab, setTab] = useState<Tab>("inbox");
  const [viewingProceeding, setViewingProceeding] = useState<string | null>(null);
  const [settings, setSettings] = useState<UserSettingsPayload | null>(null);

  // One-shot settings fetch on mount.
  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((r) => !cancelled && setSettings(r.settings))
      .catch(() => {
        // Settings failure is not fatal — fall back to defaults. The
        // pages render fine with null settings.
        if (!cancelled) setSettings(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Keyboard nav: 1 / 2 / 3 across tabs. Viewer overlay captures Esc to close.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.activeElement?.tagName === "INPUT") return;
      if (document.activeElement?.tagName === "SELECT") return;
      if (e.key === "Escape" && viewingProceeding) {
        setViewingProceeding(null);
        return;
      }
      if (e.key === "1") setTab("inbox");
      if (e.key === "2") setTab("sources");
      if (e.key === "3") setTab("settings");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewingProceeding]);

  return (
    <div className="flex h-full flex-col">
      <Header tab={tab} onTab={setTab} />
      <main className="flex-1 overflow-auto">
        {viewingProceeding ? (
          <ProceedingDetail
            proceedingPid={viewingProceeding}
            settings={settings}
            onBack={() => setViewingProceeding(null)}
          />
        ) : tab === "inbox" ? (
          <Inbox onOpenProceeding={setViewingProceeding} />
        ) : tab === "sources" ? (
          <SourceRegistry />
        ) : (
          <SettingsPage onSaved={setSettings} />
        )}
      </main>
      <Footer />
    </div>
  );
}

function Header({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <header className="border-b border-neutral-800 bg-neutral-900 px-6 py-3">
      <div className="flex items-center gap-8">
        <div className="font-mono text-sm tracking-tight">
          <span className="text-blue-400">DIP</span>
          <span className="text-neutral-500"> · Distressed Investment Intelligence</span>
        </div>
        <nav className="flex gap-1" aria-label="Primary">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTab(t.id)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                tab === t.id
                  ? "bg-blue-500/20 text-blue-300"
                  : "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
              }`}
            >
              {t.label}
              <kbd className="ml-2 rounded border border-neutral-700 bg-neutral-950 px-1 text-[10px] text-neutral-500">
                {t.hotkey}
              </kbd>
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t border-neutral-800 bg-neutral-900 px-6 py-2 font-mono text-xs text-neutral-500">
      R3 · 905 sources · 5 reference parsers + 12 scaffolded · Normalizer wired · Provenance on every record
    </footer>
  );
}
