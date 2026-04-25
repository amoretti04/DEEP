import { useEffect, useState } from "react";
import { api, type UserSettingsPayload } from "../api/client";

/**
 * Settings page. Currently surfaces two groups per R2:
 *   - Translation (opt-in NLLB-200 use per ADR-0005)
 *   - Display (low-confidence badge + priority-scope default)
 *
 * Save writes PUT /settings and returns the canonical echo, which the
 * parent App uses to refresh its in-memory settings copy so the
 * translation toggle in the viewer updates immediately.
 */
export function SettingsPage({
  onSaved,
}: {
  onSaved: (settings: UserSettingsPayload) => void;
}) {
  const [settings, setSettings] = useState<UserSettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getSettings()
      .then((r) => !cancelled && setSettings(r.settings))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.updateSettings(settings);
      setSavedAt(r.updated_at);
      onSaved(r.settings);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (loading || !settings) {
    return <CenterMessage>Loading settings…</CenterMessage>;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 p-6 font-mono text-sm">
      <header>
        <h1 className="text-lg text-neutral-100">Settings</h1>
        <p className="mt-1 text-xs text-neutral-500">
          Per-user preferences. Changes take effect immediately on save.
        </p>
      </header>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-300">
          {error}
        </div>
      )}
      {savedAt && !error && (
        <div className="rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300">
          Saved at {savedAt}
        </div>
      )}

      <Group title="Translation">
        <p className="text-xs text-neutral-500">
          When enabled, document detail pages show a “Translate EN” button that
          calls the on-demand translation service. First translation is slow
          (~1–3 s); subsequent views are instant from the shared cache.
          See ADR-0005 for the full design.
        </p>
        <Toggle
          label="Enable translation"
          value={settings.translation.enabled}
          onChange={(v) =>
            setSettings({
              ...settings,
              translation: { ...settings.translation, enabled: v },
            })
          }
        />
        <Select
          label="Default target language"
          value={settings.translation.default_target_language}
          onChange={(v) =>
            setSettings({
              ...settings,
              translation: { ...settings.translation, default_target_language: v },
            })
          }
          options={[
            ["en", "English"],
            ["it", "Italian"],
            ["de", "German"],
            ["fr", "French"],
            ["es", "Spanish"],
            ["nl", "Dutch"],
          ]}
          disabled={!settings.translation.enabled}
        />
      </Group>

      <Group title="Display">
        <Toggle
          label="Show low-confidence badge on extracted fields"
          value={settings.display.show_low_confidence_badge}
          onChange={(v) =>
            setSettings({
              ...settings,
              display: { ...settings.display, show_low_confidence_badge: v },
            })
          }
        />
        <Toggle
          label="Filter to priority scope (EU-7 + EU) by default"
          value={settings.display.priority_scope_only_by_default}
          onChange={(v) =>
            setSettings({
              ...settings,
              display: { ...settings.display, priority_scope_only_by_default: v },
            })
          }
        />
      </Group>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded bg-blue-500/30 px-4 py-2 text-sm text-blue-100 hover:bg-blue-500/40 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded border border-neutral-800 bg-neutral-900/40 p-4">
      <h2 className="text-xs uppercase tracking-widest text-neutral-500">{title}</h2>
      {children}
    </section>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3 text-sm text-neutral-300">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-blue-500"
      />
      <span>{label}</span>
    </label>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ReadonlyArray<[string, string]>;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-neutral-500">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-56 rounded border border-neutral-800 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 disabled:opacity-50"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

function CenterMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-10 font-mono text-sm text-neutral-300">
      {children}
    </div>
  );
}
