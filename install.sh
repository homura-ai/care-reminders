#!/bin/bash
# Install into ~/.local/lib/care-reminders and enable the two user timers
# (care-reminders-run.timer, care-reminders-send.timer).
#   --no-enable  copy files only, no systemctl
#   --force      replace a unit or the `care` link that another package owns
# Without --force it refuses to replace anything it did not install, so an older
# care setup (for example care-run.timer and ~/.local/bin/care-run) is left alone.
set -eu
cd -- "$(dirname -- "$0")"
enable=1 force=0
for arg in "$@"; do
    case "$arg" in
        --no-enable) enable=0 ;;
        --force) force=1 ;;
        *) echo "usage: install.sh [--no-enable] [--force]" >&2; exit 2 ;;
    esac
done
lib="$HOME/.local/lib/care-reminders"
units="$HOME/.config/systemd/user"
marker='# Part of care-reminders'
ours() {  # absent, or installed by this package
    if [ -L "$1" ]; then case "$(readlink -- "$1")" in */lib/care-reminders/*) return 0 ;; esac; return 1; fi
    [ ! -e "$1" ] || grep -qF -- "$marker" "$1"
}
foreign=0
for target in "$HOME/.local/bin/care" "$units"/care-reminders-{run,send}.{service,timer}; do
    if ! ours "$target"; then echo "install.sh: $target exists and is not from care-reminders" >&2; foreign=1; fi
done
if [ "$foreign" = 1 ] && [ "$force" = 0 ]; then
    echo "install.sh: nothing changed; rerun with --force to replace it" >&2; exit 1
fi
install -d -m 755 "$lib" "$HOME/.local/bin" "$units" "$HOME/.config/care-reminders"
install -m 755 care_config.py care_send.py care_run.py care_state.py care_wake.py care_activity.py "$lib/"
ln -sfn ../lib/care-reminders/care_state.py "$HOME/.local/bin/care"
[ -e "$HOME/.config/care-reminders/config.json" ] || install -m 600 config.example.json "$HOME/.config/care-reminders/config.json"
install -m 644 care-reminders-run.service care-reminders-run.timer \
    care-reminders-send.service care-reminders-send.timer "$units/"
[ "$enable" = 1 ] || exit 0
systemctl --user daemon-reload
systemctl --user enable --now care-reminders-run.timer care-reminders-send.timer
