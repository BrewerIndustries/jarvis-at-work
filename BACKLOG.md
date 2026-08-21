# Backlog

## Next
- [ ] **Run `spike_uia.py` on the VM.** Everything on the agent side is blocked
      on knowing whether the accessibility tree is usable. One evening.
- [ ] Live-test the brain against the API (never yet run with a real key).
- [ ] Run the Windows observer on Windows — `_session_locked()` and the psutil
      process-name lookup are written but unexercised.
- [ ] Capture UI: global hotkey + a small box. Capture must cost nothing at the
      moment of capture; routing happens after.

## Soon
- [ ] Toast notifications with action buttons (`windows-toasts`) as the push channel.
- [ ] Tray icon: pause/resume, open items, last routing decision.
- [ ] Screen OCR via Windows.Media.Ocr for content, not just titles.
- [ ] Snapshot pruning job — `prune_snapshots` exists, nothing calls it.
- [ ] Embeddings for `recall`; LIKE is a placeholder to measure against.

## Tier 1/2 integrations (headless — build before any more GUI work)
- [ ] Outlook COM (`win32com.client`) — mail and calendar with no tenant consent.
      Classic Outlook only; New Outlook dropped COM.
- [ ] OneDrive folder watcher for Teams recordings and transcripts.
- [ ] Microsoft Graph, if the tenant permits an app registration.
- [ ] Google Workspace — port `google_auth.py` / `google_calendar.py` from `jarvis`.

## Open questions
- [ ] Is the Claude account a personal Pro/Max seat or an enterprise SSO seat?
      Changes whether the VM can sign in cleanly.
- [ ] Does the tenant allow app registration + admin consent for Graph transcript
      scopes? Decides whether tier 1 exists at all.
- [ ] Commitment extraction: worth it only once transcripts are reachable.
