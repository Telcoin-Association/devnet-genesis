# do_fund as benchmark-blast.sh had it at 4356229 (bench 6 run 1), before the still_short check.
do_fund() {
    preflight
    local zone="${ZONES[0]}" urls senders start rc line
    case "${BENCH_RUN_INDEX}" in ''|*[!0-9]*|0?*) bench_die "BENCH_RUN_INDEX='${BENCH_RUN_INDEX}' must be a non-negative integer" ;; esac
    urls="$(node_url 0)"
    senders=$(( VAL_COUNT * BENCH_SENDERS ))
    start=$(( BENCH_RUN_INDEX * 100000 ))
    echo ">>> fund: ${FUNDER} (${zone}) --prepare senders=${senders} sender-start=${start} against ${urls}"
    echo "    bucket prefix: $(bucket_prefix funder)/"
    if [ -n "$(bench_instance_json "${FUNDER}" "${zone}")" ]; then
        bench_die "${FUNDER} already exists — inspect/delete it first (benchmark-blast.sh delete --yes)"
    fi
    set_aside_prev_funder
    gcloud auth print-access-token >/dev/null
    bench_manifest_ts fund_start
    create_vm "${FUNDER}" "${zone}" fund "${urls}" "${senders}" "${start}" ""
    assert_load_vm "${FUNDER}" "${zone}"
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN — re-run with --yes."; return 0; }
    bench_serial_wait "${FUNDER}" "${zone}" "BENCH_FUND_DONE rc=" "${BENCH_FUND_TIMEOUT_SECS:-3600}" "${BENCH_FUND_POLL_SECS:-60}" \
        || bench_die "funder did not finish; serial: gcloud compute instances get-serial-port-output ${FUNDER} --zone=${zone}"
    line="$(bench_serial_last "${FUNDER}" "${zone}" "BENCH_FUND_DONE rc=")"
    rc="$(printf '%s\n' "${line}" | marker_rc BENCH_FUND_DONE)"
    echo "    funder: ${line}"
    # .fund says funder/ holds this index's output: only a copy that succeeded may claim that.
    if copy_prefix "$(bucket_prefix funder)" funder; then
        bench_manifest_jq --arg i "${BENCH_RUN_INDEX}" --arg p "$(bucket_prefix funder)" '.fund = {run_index: ($i|tonumber), bucket_prefix: $p}'
    else
        bench_warn "funder/ does not hold index ${BENCH_RUN_INDEX}'s output and .fund is unchanged; copy it by hand: gcloud storage cp -r '$(bucket_prefix funder)/*' ${BENCH_RESULTS_DIR}/funder/"
        bench_manifest_note "fund: copy of $(bucket_prefix funder) into funder/ failed at $(bench_now_iso); .fund not updated" || true
    fi
    bench_manifest_ts fund_end
    bench_manifest_note "fund: ${line}"
    settle_load_vm "${FUNDER}" "${zone}" funder "${line}" BENCH_FUND_DONE
    [ "${rc:-1}" = "0" ] && [ "$(printf '%s\n' "${line}" | marker_reason BENCH_FUND_DONE)" = "ok" ] || bench_die "funding failed (${line})"
    echo "    ✓ funded"
}
