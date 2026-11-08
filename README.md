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
upwatch --json             results as JSON
upwatch --wait-network 300 wait up to 300 s (retry every 30 s) for the API hosts
systemctl --user start upwatch.service   run the notifying check now
journalctl --user -u upwatch            its output
```
