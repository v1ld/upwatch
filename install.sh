#!/usr/bin/env bash
# install.sh: install upwatch for this user (no root).
#   ~/.local/bin/upwatch                      the app
#   ~/.config/upwatch/config.toml             your sources (written only if missing; never overwritten)
#   ~/.config/systemd/user/upwatch.{service,timer}   checks every 6 hours, desktop notification on new updates
# usage: bash install.sh            install or update (safe to rerun)
#        bash install.sh --uninstall   remove the app and the units (keeps config and state)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
bin=$HOME/.local/bin/upwatch
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
cfg=${XDG_CONFIG_HOME:-$HOME/.config}/upwatch/config.toml

if [[ ${1:-} == --uninstall ]]; then
  systemctl --user disable --now upwatch.timer 2>/dev/null || true
  rm -f "$bin" "$units/upwatch.service" "$units/upwatch.timer"
  systemctl --user daemon-reload
  echo "removed upwatch (kept $cfg and ~/.local/state/upwatch)"
  exit 0
fi

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "upwatch needs Python 3.11 or newer"; exit 1; }
install -Dm755 "$here/upwatch" "$bin"
install -Dm644 "$here/systemd/upwatch.service" "$units/upwatch.service"
install -Dm644 "$here/systemd/upwatch.timer" "$units/upwatch.timer"
echo "installed $bin and $units/upwatch.{service,timer}"

if [[ ! -e $cfg ]]; then
  "$bin" init
  # the Witcher 3 project (its work/ folder holds updates/ and state/; override with W3WORK=...): point tw3 and the key there
  w3work=${W3WORK:-}
  if [[ -e $w3work/updates/nexus-check.json ]]; then
    sed -i "s#^file = .*nexus-check.json\"#file = \"$w3work/updates/nexus-check.json\"#" "$cfg"
  fi
  if [[ ! -e $HOME/.config/nexus-apikey && -e $w3work/state/nexus-apikey ]]; then
    sed -i "s#^nexus_key_file = .*#nexus_key_file = \"$w3work/state/nexus-apikey\"#" "$cfg"
  fi
else
  echo "kept your config $cfg"
fi

command -v notify-send >/dev/null || echo "NOTE: notify-send not found; notifications fall back to gdbus. For notify-send: sudo pacman -S libnotify"

systemctl --user daemon-reload
systemctl --user enable --now upwatch.timer
echo
echo "== timer"; systemctl --user list-timers upwatch.timer --no-pager | head -3
echo
echo "== what is installed (for the Proton sources)"
ls -1d "$HOME"/.local/share/Steam/compatibilitytools.d/*/ 2>/dev/null | xargs -rn1 basename || true
pacman -Q 2>/dev/null | grep -i proton || true
echo
echo "== first check (upwatch -v)"
"$bin" -v || true
