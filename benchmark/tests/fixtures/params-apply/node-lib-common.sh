# lib/common.sh of the v2 scripts on a fake node (tests/test_params_apply.py): the two functions
# params-apply.sh calls through tnlib, driven by files in the node ($STUB_NODE_DIR):
#   guard   one verdict per call, separated by spaces: 0 passes, 1 refuses, 2 cannot count, w passes
#           with a warning (the real guard's blind pass); the last one repeats; absent: 0
#   epoch   one "<secs left> <epoch duration>" per call, one per line; the last one repeats;
#           absent: "600 1200"
# Each call is appended to calls.log.
set -euo pipefail

# _stub_item <file> <counter> <default> <sep> — the item of <file> for this call (the last repeats).
_stub_item() {
    local f="${STUB_NODE_DIR}/$1" c="${STUB_NODE_DIR}/state/$2" n=0 items
    [ ! -f "$c" ] || n="$(cat "$c")"
    echo $((n + 1)) > "$c"
    if [ ! -f "$f" ]; then printf '%s\n' "$3"; return 0; fi
    if [ "$4" = word ]; then items="$(tr -s ' \t' '\n\n' < "$f" | grep -v '^$')"; else items="$(grep -v '^$' "$f")"; fi
    # awk reads every line (no early exit: under pipefail a SIGPIPE to printf would fail the call)
    printf '%s\n' "$items" | awk -v n="$((n + 1))" '{ last = $0 } NR == n { pick = $0; found = 1 } END { print (found ? pick : last) }'
}

tn_committee_down_guard() {
    local fn="${2:-}" v
    printf 'tnlib tn_committee_down_guard\n' >> "${STUB_NODE_DIR}/calls.log"
    v="$(_stub_item guard guard-calls 0 word)"
    case "$v" in
        0) "$fn" log "committee of 4: 0 member(s) down; stopping this node leaves 1, below the 2 that halt consensus."; return 0 ;;
        w) "$fn" warn "could not count the committee members that are down (the committee could not be read); going ahead."; return 0 ;;
        1) "$fn" warn "committee of 4: 1 member(s) down; stopping this node makes 2 of the 2 that halt consensus. Refused."; return 1 ;;
        *) "$fn" warn "could not count the committee members that are down (the latest consensus commit is 300 s old)."; return 2 ;;
    esac
}

tn_epoch_secs_left() {
    local v
    printf 'tnlib tn_epoch_secs_left\n' >> "${STUB_NODE_DIR}/calls.log"
    v="$(_stub_item epoch epoch-calls "600 1200" line)"
    # shellcheck disable=SC2086  # two numbers
    set -- $v
    printf '%s 7 1700001200 %s\n' "$1" "$2"
}
