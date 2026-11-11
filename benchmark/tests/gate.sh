#!/usr/bin/env bash
# The harness gate: the whole unit suite, each module that failed in it once more alone, then the mutation
# checker (check_mutations.py), on a host nothing else is loading.
#
# usage: benchmark/tests/gate.sh [--list] [--modules a,b] [--under-load] [--jobs <n>]
#   --list          print what the gate would run (modules, mutation cases) and exit; no load check
#   --modules a,b   only these test modules (test_x or x), and only the mutation cases whose test is in one of them
#   --under-load    run although the host is loaded (the result line then says load=loaded)
#   --jobs <n>      mutation cases at a time (default GATE_MUTATION_JOBS, else 1)
#
# Bench 5 (D41) ran the gate beside cargo jobs: timing-sensitive tests failed and the exit code did not say
# which. So the gate refuses to start while a process named cargo, rustc, cargo-nextest or nextest runs, or
# a bench driver (benchmark-{deploy,blast,teardown,probe}.sh, launch/launch.sh, launch/run-arms.sh,
# tools/params-apply.sh, check_mutations.py or another gate.sh) runs under bash, sh or python. The match is
# on a process's program (argv[0]) or on the script a shell or python runs (argv[1]), read from `ps`, never
# on a whole command line, so the gate's own ps and awk cannot match (and its own pid and its subshells are
# skipped); a shell whose -c text names cargo does not match either, the cargo it starts does. The
# check runs again after the suite and after the mutations: a job that started meanwhile also makes the
# run load=loaded.
#
# The suite runs with BENCH_TEST_TIMEOUT_SCALE=3 (unless the caller set it), the scale the tests with a
# timing budget multiply their timeouts by. A module that failed runs once more alone; the suite passes
# when every failed module passes alone. The last line is always
#   GATE unittest=<rc> isolated=<module:rc,...|none> mutations=<rc> load=<quiet|loaded> secs=<n>
# (rc "-" for a step that did not run). Exit 0 only when the suite passed (after the isolated re-runs) and
# every mutation was killed; 1 when not; 2 when the gate refused to start or was called wrongly.
# Logs go to GATE_LOG_DIR (default: a new directory under ${TMPDIR:-/tmp}).
set -euo pipefail

TESTS="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "${TESTS}/../.." && pwd -P)"
CHECKER="${TESTS}/check_mutations.py"
T0="$(date +%s)"

LIST=0; UNDER_LOAD=0; MODULES=""; JOBS="${GATE_MUTATION_JOBS:-1}"
usage() { sed -n '/^# usage:/,/^#   --jobs/p' "$0" | sed 's/^# \{0,1\}//' >&2; }
result() {   # unittest isolated mutations load
    echo "GATE unittest=$1 isolated=$2 mutations=$3 load=$4 secs=$(( $(date +%s) - T0 ))"
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --list) LIST=1 ;;
        --under-load) UNDER_LOAD=1 ;;
        --modules) [ "$#" -ge 2 ] || { echo "gate: --modules needs a list" >&2; usage; exit 2; }; MODULES="$2"; shift ;;
        --modules=*) MODULES="${1#--modules=}" ;;
        --jobs) [ "$#" -ge 2 ] || { echo "gate: --jobs needs a number" >&2; usage; exit 2; }; JOBS="$2"; shift ;;
        --jobs=*) JOBS="${1#--jobs=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "gate: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
    shift
done
case "${JOBS}" in ''|*[!0-9]*|0) echo "gate: --jobs must be a positive integer, not '${JOBS}'" >&2; exit 2 ;; esac

# The modules: every test_*.py beside this script, or the --modules list (each must exist).
MODS=()
if [ -n "${MODULES}" ]; then
    for m in $(printf '%s' "${MODULES}" | tr ',' ' '); do
        m="${m%.py}"
        case "${m}" in test_*) ;; *) m="test_${m}" ;; esac
        [ -f "${TESTS}/${m}.py" ] || { echo "gate: no module ${m} in ${TESTS}" >&2; exit 2; }
        MODS+=("${m}")
    done
    [ "${#MODS[@]}" -gt 0 ] || { echo "gate: --modules names no module" >&2; exit 2; }
else
    for f in "${TESTS}"/test_*.py; do
        [ -f "${f}" ] || continue
        m="${f##*/}"; MODS+=("${m%.py}")
    done
    [ "${#MODS[@]}" -gt 0 ] || { echo "gate: no test_*.py in ${TESTS}" >&2; exit 2; }
fi
MOD_CSV="$(IFS=,; printf '%s' "${MODS[*]}")"
CHECK_ARGS=(--jobs "${JOBS}")
[ -z "${MODULES}" ] || CHECK_ARGS+=(--modules "${MOD_CSV}")

# Processes that load the host, one "<pid> <command line>" per line (none: empty).
busy() {
    ps -eo pid=,ppid=,args= 2>/dev/null | awk -v self="$$" '
        function base(p) { sub(/.*\//, "", p); return p }
        $1 == self || $2 == self { next }
        {
            a1 = base($3); a2 = base($4)
            s = (a1 ~ /^(bash|sh|dash|zsh|env|python|python3|python3\.[0-9]+)$/) ? a2 : a1
            if (a1 ~ /^(cargo|rustc|cargo-nextest|nextest)$/ \
                || s ~ /^(benchmark-(deploy|blast|teardown|probe)\.sh|launch\.sh|run-arms\.sh|params-apply\.sh|check_mutations\.py|gate\.sh)$/) {
                line = $0; sub(/^[ \t]*[0-9]+[ \t]+[0-9]+[ \t]+/, "", line)
                printf "%s %s\n", $1, substr(line, 1, 160)
            }
        }'
}
LOAD=quiet
check_load() {   # <when>: prints what it found; sets LOAD=loaded when anything was
    local found
    found="$(busy)" || found=""
    [ -n "${found}" ] || return 0
    LOAD=loaded
    echo "gate: the host is loaded ($1):"
    printf '%s\n' "${found}" | sed 's/^/  /'
}

if [ "${LIST}" = "1" ]; then
    echo "gate: tests in ${TESTS}"
    echo "gate: load check: no process named cargo, rustc, cargo-nextest or nextest, and no bench driver"
    echo "gate: unit suite with BENCH_TEST_TIMEOUT_SCALE=${BENCH_TEST_TIMEOUT_SCALE:-3}: ${#MODS[@]} module(s)"
    printf '  %s\n' "${MODS[@]}"
    echo "gate: then each failed module once more alone"
    echo "gate: mutation checker: python3 ${CHECKER#"${ROOT}"/} ${CHECK_ARGS[*]}"
    python3 "${CHECKER}" --list "${CHECK_ARGS[@]}"
    exit 0
fi

check_load "start"
if [ "${LOAD}" = loaded ] && [ "${UNDER_LOAD}" != "1" ]; then
    echo "gate: refused: wait for these to end, or pass --under-load to run anyway (the result line says so)" >&2
    result - none - loaded
    exit 2
fi

LOGS="${GATE_LOG_DIR:-}"
if [ -z "${LOGS}" ]; then
    LOGS="$(mktemp -d "${TMPDIR:-/tmp}/bench-gate.XXXXXX")"
else
    mkdir -p "${LOGS}"
fi
export BENCH_TEST_TIMEOUT_SCALE="${BENCH_TEST_TIMEOUT_SCALE:-3}"
export PYTHONDONTWRITEBYTECODE=1

# Runs the named modules (none: discover every test_*.py), writes the modules with a failure or an error,
# one per line, to <failed-file> and exits 0 only when every test passed. A module that does not import
# counts under its own name; a setUpClass/setUpModule error under its module.
RUNNER="$(cat <<'PY'
import re
import sys
import unittest

tests_dir, failed_file, names = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, tests_dir)
loader = unittest.TestLoader()
if names:
    suite = loader.loadTestsFromNames(names)
else:
    suite = loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir)
result = unittest.TextTestRunner(verbosity=2).run(suite)


def module_of(test):
    mod = type(test).__module__
    if not mod.startswith("unittest"):
        return mod
    if type(test).__name__ == "_FailedTest":
        return test._testMethodName.split(".")[0]
    m = re.search(r"\(([^)]+)\)", getattr(test, "description", "") or str(test))
    return m.group(1).split(".")[0] if m else str(test)


failed = sorted(set(module_of(t) for t, _ in result.failures + result.errors))
with open(failed_file, "w") as fh:
    fh.write("".join(m + "\n" for m in failed))
sys.exit(0 if result.wasSuccessful() else 1)
PY
)"

N_ARGS=()
[ -z "${MODULES}" ] || N_ARGS=("${MODS[@]}")
echo "gate: unit suite, ${#MODS[@]} module(s), BENCH_TEST_TIMEOUT_SCALE=${BENCH_TEST_TIMEOUT_SCALE}, log ${LOGS}/unittest.log"
UT=0
( cd "${ROOT}" && python3 -c "${RUNNER}" "${TESTS}" "${LOGS}/failed.txt" ${N_ARGS[@]+"${N_ARGS[@]}"} ) \
    > "${LOGS}/unittest.log" 2>&1 || UT=$?
tail -n 3 "${LOGS}/unittest.log" | sed 's/^/  /'

ISO=""; ISO_OK=1
if [ "${UT}" != "0" ]; then
    FAILED="$(cat "${LOGS}/failed.txt" 2>/dev/null)" || FAILED=""
    [ -n "${FAILED}" ] || ISO_OK=0     # the run broke before it could name a module
    for m in ${FAILED}; do
        rc=0
        echo "gate: ${m} failed in the suite; once more alone, log ${LOGS}/isolated-${m}.log"
        ( cd "${ROOT}" && python3 -c "${RUNNER}" "${TESTS}" "${LOGS}/failed-${m}.txt" "${m}" ) \
            > "${LOGS}/isolated-${m}.log" 2>&1 || rc=$?
        tail -n 1 "${LOGS}/isolated-${m}.log" | sed 's/^/  /'
        ISO="${ISO:+${ISO},}${m}:${rc}"
        [ "${rc}" = "0" ] || ISO_OK=0
    done
fi
check_load "after the suite"

echo "gate: mutation checker, log ${LOGS}/mutations.log"
MUT=0
python3 "${CHECKER}" "${CHECK_ARGS[@]}" > "${LOGS}/mutations.log" 2>&1 || MUT=$?
grep -E '^[0-9]+ of [0-9]+ mutations killed' "${LOGS}/mutations.log" | sed 's/^/  /' || true
grep -E '^  (survived|broken|anchor|syntax) ' "${LOGS}/mutations.log" | sed 's/^/  /' || true
check_load "after the mutations"

result "${UT}" "${ISO:-none}" "${MUT}" "${LOAD}"
[ "${ISO_OK}" = "1" ] && [ "${MUT}" = "0" ] || exit 1
exit 0
