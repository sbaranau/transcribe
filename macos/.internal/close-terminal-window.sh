#!/usr/bin/env bash
# Schedule closing the Terminal window created for a .command launcher. The close must happen
# only after this script and its parent shells have exited; otherwise Terminal shows an alarming
# warning that closing the window will terminate bash and osascript.
[ "${TERM_PROGRAM:-}" = "Apple_Terminal" ] || exit 0

window_id="$(osascript -e 'tell application "Terminal" to get the id of the front window' 2>/dev/null)" || exit 0
case "$window_id" in
    ''|*[!0-9]*) exit 0 ;;
esac

# launchctl starts a detached job with no connection to this Terminal tab. By the time it asks
# Terminal to close the captured window, the launcher and Terminal's wrapper shell are gone.
label="local.transcribe.close-terminal.$$.${window_id}"
command="sleep 2; /usr/bin/osascript -e 'tell application \"Terminal\" to close (first window whose id is $window_id)'"
/bin/launchctl submit -l "$label" -- /bin/sh -c "$command" >/dev/null 2>&1 || true
