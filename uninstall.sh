#!/bin/bash
# Stop the timers and remove the installed files. Keeps config and state.
# Only removes units and the `care` link that this package installed.
set -eu
systemctl="${SYSTEMCTL:-systemctl}"   # tests set SYSTEMCTL=true
units="$HOME/.config/systemd/user"
marker='# Part of care-reminders'
"$systemctl" --user disable --now care-reminders-send.timer care-reminders-run.timer 2>/dev/null || true
for unit in "$units"/care-reminders-{send,run}.{service,timer}; do
    if [ -f "$unit" ] && grep -qF -- "$marker" "$unit"; then rm -f -- "$unit"
    elif [ -e "$unit" ]; then echo "kept $unit (not from care-reminders)" >&2; fi
done
link="$HOME/.local/bin/care"
if [ -L "$link" ]; then
    case "$(readlink -- "$link")" in */lib/care-reminders/*) rm -f -- "$link" ;; *) echo "kept $link (not from care-reminders)" >&2 ;; esac
fi
rm -rf -- "$HOME/.local/lib/care-reminders"
"$systemctl" --user daemon-reload
echo "Kept ~/.config/care-reminders and ~/.local/state/care-reminders"
