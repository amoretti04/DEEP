# Canary fixtures for it-tribunale-milano

Capture 2–3 known-good raw payloads for **Tribunale di Milano — Sezione Fallimentare** and commit them here
alongside expected canonical outputs. CI replays the parser against
these fixtures on every change; any divergence fails the build.

Layout:
```
tests/canary/it/tribunale-milano/
  001_raw.html
  001_expected.json
  002_raw.html
  002_expected.json
```

How to capture:
1. From the live source, save one detail page as-is (no JS rendering).
2. Redact any personal data that isn't required for regression (CLAUDE.md §3.2).
3. Hand-produce the expected canonical JSON.
4. Commit, push, open PR.
