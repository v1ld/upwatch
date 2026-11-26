# upwatch

Checks watched software for new versions and pops up a desktop notification when one appears.
Standard-library Python 3.11+, no root.

Install or update: `bash install.sh` (from this folder). Remove: `bash install.sh --uninstall`.

## Files
- `~/.local/bin/upwatch`: the app
- `~/.config/upwatch/config.toml`: the sources (`upwatch init` writes a commented example)
- `~/.config/systemd/user/upwatch.{service,timer}`: runs `upwatch check --notify --quiet --wait-network 300` 2 min after login and every 6 hours (waits up to 5 min for the network, retrying every 30 s)
- `~/.local/state/upwatch/state.json`: acknowledged versions, what was already notified
- `~/.cache/upwatch/`: Nexus metadata cache

## Source types
- `github-release`: `repo = "owner/name"`; optional `include_prereleases`, `tag_pattern` (regex)
- `github-commit`: `repo`, optional `branch`
- `nexus`: `game`, `mod_id`, optional `installed`, `file_name` (glob on the file's name)
- `list`: `format = "nexus-check"`, `file = ".../nexus-check.json"`: every mod in the Witcher 3 layer's list
  (Nexus pages + GitHub repos), with provenance checks and changelogs; also refreshes `nexus-status.json` beside it

Installed version, any single source: `installed = "1.2"`, `installed_glob = "~/path/Name*"` (current when a matching
folder or file name contains the latest tag), or `installed_cmd = "pacman -Q pkg"` (+ `installed_regex`).
With none of these, the first check records the latest version as yours; later ones show as updates
until `upwatch ack NAME`.

Common keys: `name`, `type`, `tags = [...]`, `enabled = false`.

## Commands
```
upwatch                    check everything (prints only updates and errors)
upwatch -v                 also the up-to-date ones, API allowance left, time taken
upwatch --top              standalone sources only (skip what lists point to)
upwatch --games            sources tagged "game" (same as --tag game)
upwatch --tag proton       sources with that tag
upwatch tw3                one source; tw3/modSmartCamera or "Smart Camera" for one list member
upwatch list [...]         what would be checked, no network
upwatch ack ge-proton      accept the latest version (sources without an installed version)
upwatch --json             results as JSON (name: as shown; a list member's Nexus page title: nexus_name)
upwatch --fetch            check, then fetch the Nexus file updates with your clicks (see below)
upwatch tw3 --fetch --dry-run   what fetching that list's updates would do; opens and moves nothing
upwatch fetch WANTS.json   fetch the files a want-list names (see below)
upwatch --wait-network 300 wait up to 300 s (retry every 30 s) for the API hosts
systemctl --user start upwatch.service   run the notifying check now
journalctl --user -u upwatch            its output
```

## Fetching updates (`--fetch`)
`upwatch --fetch` runs the normal check, then helps you download the Nexus file updates it found: it opens each
file's page in your browser, waits for you to click the download, recognises the finished file in your Downloads
folder and moves it to the folder its source names. **Every download is your own click on the page.** upwatch
never downloads a file itself, sends no request to the Nexus site for it, and presses nothing on a page; it hands the
page address to your desktop browser (`xdg-open`, or Python's `webbrowser`).

Config (`~/.config/upwatch/config.toml`):
```
[settings]
downloads_dir = "~/Downloads"        # where your browser saves (this is the default)
# fetch_dir = "~/mods/inbox"         # optional default for Nexus sources that name none

[[source]]
name = "tw3"
type = "list"
# ...
fetch_dir = "~/path/to/inbox"        # where this list's new files go (an existing folder)
```
`fetch_dir` works on a `list` and on a `nexus` source. A Nexus update whose source has no `fetch_dir` (and no default in
`[settings]`) is not fetched: the output says so in one line. GitHub updates, held versions, failed lookups and
archives flagged "!" are not fetched either. NAME, `--tag`, `--games` and `--top` narrow what is checked and so what
is fetched.

While it runs: a batch whose files have all arrived opens the next batch by itself; Enter opens the next batch now
(after the last one, Enter finishes); Ctrl-C stops at once and prints the summary. Files that match and are already
in Downloads are offered first with one question (`--yes` takes them without asking).

The output is one line per mod, then a count:
```
Friendly Stash 0.9.2R: fetched
Other Mod 1.4: skipped (no fetch_dir for othergame)
Third Mod 2.0: FAILED (not downloaded)
fetch: 1 fetched, 1 skipped, 1 failed
```
`-v` adds each file's path, how it was recognised and its md5; `--report FILE` always writes all of that as JSON.

Options: `--dry-run` (shows what would happen; opens and moves nothing), `--yes`, `--batch N`, `--gap MIN MAX`,
`--downloads DIR`, `--settle SECS`, `--poll SECS`, `--report FILE`, `--opener CMD` (open pages with `CMD URL`).
Exit status: 0 everything in place, 1 something missing or not moved, 2 bad options or list, 130 Ctrl-C.

### Safety limits (fixed, not settings)
- Pages open in batches of `--batch` (default 10, at most 20), with a random gap of `--gap` seconds between any two
  openings (default 1 to 2; it can never be under 1 second).
- A file is touched only once it has kept the same size and time across two looks `--settle` seconds apart (default 2),
  and never while it looks partial: `*.part`, `*.crdownload`, `*.tmp`, `*.download`, `*.partial`, hidden or empty
  files, or a file with a partial twin beside it.
- Recognition: by md5 when known; otherwise Nexus's exact file name plus the exact size (`size_in_bytes`), or the
  name alone when Nexus gives no size. A browser's `name (1).7z` and `%20` for spaces count as the name. Never
  "the newest file". Anything else in Downloads is left exactly as it is.
- It never overwrites: if the destination already holds a different file of that name, both stay where they are. It
  never creates a destination folder.
- A move is a hard link under the new name, then the old name is dropped; across filesystems, a copy that is read back
  and md5-compared before the source is removed. Ctrl-C during a copy removes the unfinished copy and keeps the source.
- `--fetch` and `fetch` work only in a terminal, never with `--notify`, `--quiet` or `--json`, so the timer can
  never open pages.

### Want-lists (`upwatch fetch WANTS.json`)
Another tool can name the files to fetch in a JSON file, format `upwatch-wants` version 1:
```json
{
 "format": "upwatch-wants",
 "version": 1,
 "written_by": "my rollback tool",
 "files": [
  {"mod": "Some Mod", "id": "modSomeMod", "version": "1.2", "game": "witcher3",
   "nexus_mod_id": 1234, "file_id": 56789,
   "file_name": "Some Mod 1234 1.2 2026-11-01T10-00Z abcdefghi.7z",
   "size": 1234567, "md5": "0123456789abcdef0123456789abcdef", "dest": "archive", "note": "rollback"}
 ]
}
```
| field | | |
|---|---|---|
| `mod` | required | name shown on screen |
| `nexus_mod_id`, `file_id` | required | whole numbers |
| `file_name` | required | Nexus's exact file name (files.json `file_name`); also the name at the destination |
| `dest` | required | `inbox` or `archive`: the folders `inbox_dir` and `archive_dir` in `[settings]` (or `--inbox-dir`, `--archive-dir`) |
| `size` | optional | exact bytes, or null |
| `md5` | optional | 32 hex digits, or null; when given, the md5 decides and the name does not matter |
| `url` | optional | default `https://www.nexusmods.com/GAME/mods/ID?tab=files&file_id=FILE_ID`; https only; on nexusmods.com its ids must agree with the entry |
| `game` | optional | default `witcher3` |
| `id`, `version`, `note`, `written_by`, `written` | optional | shown / carried |

The same `file_id` twice is allowed only with identical name, size, md5 and destination (used once); two different
files may not want the same name at the same destination; a newer `version` of the format is refused. A list with any
problem is refused whole, with every problem listed.

## Tests
`python3 -I tests/test_upwatch.py` and `python3 -I tests/test_fetch.py` (no network: GitHub, Nexus and the browser
are stubbed; scratch folders come from `tempfile`; the cross-filesystem cases use `/dev/shm` when it is a separate
filesystem). Two environment variables exist for the tests only: `UPWATCH_TEST_FORCE_COPY=1` (take the copy path)
and `UPWATCH_TEST_COPY_DELAY=SECS` (slow the copy so Ctrl-C can land in it).
