#!/usr/bin/env bash
set -Eeuo pipefail

if ((EUID == 0)); then
  echo "Run this as the desktop user, without sudo." >&2
  exit 1
fi

entry=""
for candidate in "${XDG_DATA_HOME:-$HOME/.local/share}/applications/smv-cap-ui.desktop" \
                 /usr/share/applications/smv-cap-ui.desktop; do
  if [[ -f "$candidate" ]]; then
    entry="$candidate"
    break
  fi
done
[[ -n "$entry" ]] || { echo "Capture UI application entry is not installed." >&2; exit 1; }

desktop_dir=""
if command -v xdg-user-dir >/dev/null 2>&1; then
  desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
if [[ -z "$desktop_dir" || "$desktop_dir" == "$HOME" ]]; then
  desktop_dir="$HOME/Desktop"
fi
mkdir -p -- "$desktop_dir"
shortcut="$desktop_dir/Ashton Capture Slices.desktop"
if [[ -e "$shortcut" ]] && ! grep -q '^X-Ashton-Smokeview=true$' "$shortcut"; then
  echo "Refusing to replace an unrelated desktop shortcut: $shortcut" >&2
  exit 1
fi
install -m 0755 "$entry" "$shortcut"
if command -v gio >/dev/null 2>&1; then
  gio set "$shortcut" metadata::trusted true >/dev/null 2>&1 || true
fi
echo "Capture UI desktop shortcut: $shortcut"
