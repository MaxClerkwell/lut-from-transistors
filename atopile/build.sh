#!/bin/sh
# Build the atopile project without touching the user's KiCad configuration.
#
# atopile writes to the home directory on every start: it installs a plugin
# loader into KiCad's scripting directory and enables the KiCad API server in
# kicad_common.json. This script gives it a home directory of its own and,
# where `unshare` is available, runs it without network access.
#
# Usage: ATO=/path/to/ato ./build.sh        (default: `ato` from the PATH)
set -e
cd "$(dirname "$0")"
ATO="${ATO:-ato}"
H="$PWD/.home"
mkdir -p "$H"
export HOME="$H" XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" \
       XDG_STATE_HOME="$H/.local/state" XDG_CACHE_HOME="$H/.cache"
if unshare -rn true 2>/dev/null; then
    exec unshare -rn "$ATO" build "$@"
fi
exec "$ATO" build "$@"
