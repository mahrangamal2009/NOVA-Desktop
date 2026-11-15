# Plan: Startup Manager (مدير البرامج الابتدائية)

## Context
NOVA Desktop 3.0 already contains: Overview, System Monitor, Cleaner, RAM Manager, DNS Manager, Network Monitor, Notes, Programs. The natural next feature is **Startup Manager** — managing programs that launch automatically at boot. It complements the Programs page (shortcuts) and RAM Manager (running processes) and requires no new Python packages (psutil already installed).

## Decision: Startup Manager
- **Page name:** "Startup" (Arabic: "برامج الابتداء")
- **Nav item:** added after "programs" in the left sidebar.
- **Data source:** scan two startup directories plus optional registry fallback:
  - `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`
  - `%LOCALAPPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`
  - Registry `HKCU:\Software\Microsoft\Windows\Startup` (keys = program name, value = path or exe)
- **Display columns:** اسم البرنامج (Name), مسار الاختصار/المسار (Path/Location), مفعول (Enabled).
- **Per-row controls:** Checkbutton "تفعيل" (Enable) + Button "تشغيل المحدد" (Launch selected) + Button "إعدادات التطبيقات" (App Settings).
- **Refresh:** automatic every 5 s; manual refresh button.
- **Safety:** never auto-enables; user confirms each toggle; does NOT delete entries; no destructive actions.

## Dependencies
None new — uses existing `psutil`.

## Implementation Steps
1. Add nav item `"startup", "برامج الابتداء"` in `_layout()`.
2. Add `page_startup()` method: clear content, fetch entries, populate `ttk.Treeview` (`columns=("name","path","enabled")`), pack, show heading card, add buttons.
3. Add `self.startup_tree = ttk.Treeview(...)` and helper `fetch_startup_entries()` returning `[{name, path, enabled}, ...]`.
4. Add `_toggle_startup(idx, val)`, `_schedule_startup_refresh()`, `_refresh_startup()`.
5. Bind `<<TreeviewSelect>>` to open selected (like `page_programs`).
6. Wire into `show_page("startup")`.

## Helper: fetch_startup_entries()
- Local paths:
  - `local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))`
  - `temp = Path(tempfile.gettempdir())`
  - `targets = cache_targets()` (user temp, DirectX shader cache, thumbnail cache, Windows Temp)
- Startup dirs:
  - `local / "Microsoft/Windows/Start Menu/Programs/Startup"`
  - `local / "Microsoft/Windows/Start Menu/Programs"`
  - `PROGRAMDATA / "Microsoft/Windows/Start Menu/Programs/Startup"`
  - `os.environ["APPDATA"] / "Microsoft/Windows/Start Menu/Programs/Startup"`
- Registry fallback (if above empty):
  - Iterate `HKCU["Software"]["Microsoft"]["Windows"]["Startup"]` keys; value = path or exe; name = value.split("=")[0].strip().split("/")[0].
- Deduplicate by name; mark enabled = True if file exists or registry value non-empty else False.

## Risks
- Registry entries vary across OS versions; file scan is primary.
- Some entries are services (no .lnk); try `sc start` or `msstart` instead of opening.
- Admin rights needed for some entries; show warning if command fails.
- Registry keys may contain spaces; split carefully.

## Validation
- Launch app → startup page loads.
- Sidebar shows startup entries.
- Toggle enable → confirmation dialog; state updates.
- Refresh refreshes values.
- No frozen interface during background operations (threaded).

## Open Questions
- Include registry-only entries beyond file scan?
- How to handle entries without .lnk (services)?
