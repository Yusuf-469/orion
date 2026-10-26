# Stage 2 manual checklist (about 10 minutes)

Run `C:\ORION\.venv\Scripts\python.exe -m orion` from `C:\ORION`. **Untick "Dry run"** for T1 to T7. Files go to `C:\ORION\workspace\`.

| # | Do | Expected |
|---|---|---|
| T1 | Tool `files.write_new`, args as pre-filled → Run tool | task **succeeded**; log says "re-read sha256 … matches"; `workspace\hello.txt` exists |
| T2 | Run `files.write_new` again with the same args | task **failed** with `invalid_input: … never overwrites`; file unchanged |
| T3 | `files.read` `{"path": "hello.txt"}` | succeeded, "read 16 bytes" |
| T4 | `files.write_new` `{"path": "..\\escape.txt", "content": "x"}` | task **blocked**, `permission_denied`; no `C:\ORION\escape.txt` |
| T5 | `files.copy` (pre-filled), then `files.delete` (pre-filled) | copy succeeds; delete **blocked**: `files.delete` not granted |
| T6 | Close ORION. Create `C:\ORION\orion.toml` with `[orion]` and `granted_permissions = ["files.read", "files.write", "app.launch", "files.delete"]`. Restart; banner lists files.delete. Run `files.delete` | dialog names the file and says it goes to trash; default button is **No**. Click **No** → blocked. Run again, click **Yes** → succeeded; file now in `workspace\.orion_trash\` |
| T7 | Run `files.delete` on a new copy; while the dialog is open press **Ctrl+Alt+End** | dialog closes; task **cancelled**; file still there |
| T8 | `app.launch` `{"app": "calculator"}` (reset kill switch first) | Calculator opens; task succeeded with "new window 'Calculator'" |
| T9 | Tick "Dry run", run `files.write_new` with a new path | task skipped; log says "would allow"; no file created |
