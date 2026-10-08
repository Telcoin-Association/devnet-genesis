#!/usr/bin/env bash
# Stand-in for sleep: records the requested seconds in $FAKE_ROOT/sleeps and returns at once.
printf '%s\n' "$*" >> "${FAKE_ROOT:?}/sleeps"
