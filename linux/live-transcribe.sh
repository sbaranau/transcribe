#!/usr/bin/env bash
# Transcribes a meeting while it happens, in its own window: the computer's sound (the other
# participants in Teams, Zoom, ...) and your microphone, through PulseAudio or PipeWire. No video
# is recorded. The text goes to ~/Documents/Transcripts/<date time>/meeting.live.txt; after Stop,
# the window offers the full processing (speakers, check, summary).
exec "$(dirname "$(readlink -f "$0")")/transcribe.sh" --live "$@"
