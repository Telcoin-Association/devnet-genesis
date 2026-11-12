"""L1a mutation anchors, check_mutations.py style: each case in a copied tree (never the working tree)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

R = Path("/home/drtnarg/coding/telcoin/devnet-genesis")
FILES = ["config.sh", "benchmark/config.sh", "benchmark/consensus-parameters.yaml", "common/create-instances.sh",
         "common/wgvpn/wg-config.sh", "benchmark/tests/test_node_shapes.py"]
CFG = "benchmark/config.sh"
T = "test_node_shapes."

MT_PAST = ('_bench_bad="not <index>:<machine-type>" ;; esac\n'
           '    case "${_bench_idx}" in \'\'|*[!0-9]*|0?*) _bench_bad="${_bench_bad:-index \'${_bench_idx}\' is not a number}" ;; esac\n'
           '    if [ -z "${_bench_bad}" ] && [ "${_bench_idx}" -ge "${#INSTANCE_NAMES[@]}" ]')
MT_DUP = ('    case "${_bench_seen}" in *" ${_bench_idx} "*) _bench_bad="${_bench_bad:-index ${_bench_idx} appears twice (give each node one item)}" ;; esac\n'
          '    _bench_seen="${_bench_seen}${_bench_idx} "\n'
          '    if [ -z "${_bench_bad}" ] && ! [[ "${_bench_v}" =~ ^[a-z][a-z0-9-]*[a-z0-9]$ ]]; then')
ZONES_ENV_END = '    export ZONES=("${_bench_zarr[@]}")\nfi\n'
NARROW = ('    export MACHINE_TYPE="${BENCH_CREATE_MACHINE_TYPE}"\n'
          '    for _bench_idx in "${!INSTANCE_NAMES[@]}"; do\n'
          '        [ "${NODE_MACHINE_TYPES[_bench_idx]}" = "${MACHINE_TYPE}" ]')

CASES = [
    ("M1 an index past the last node is accepted (BENCH_NODE_MACHINE_TYPES)",
     MT_PAST, MT_PAST.replace("-ge", "-gt"), T + "RefusalTests.test_machine_types"),
    ("M2 a duplicate index is accepted (BENCH_NODE_MACHINE_TYPES)",
     MT_DUP, MT_DUP.split("\n", 1)[1], T + "RefusalTests.test_machine_types"),
    ("M3 the unset of the other types' INSTANCE_NAMES entries is dropped",
     '[ "${NODE_MACHINE_TYPES[_bench_idx]}" = "${MACHINE_TYPE}" ] || unset "INSTANCE_NAMES[${_bench_idx}]"',
     '[ "${NODE_MACHINE_TYPES[_bench_idx]}" = "${MACHINE_TYPE}" ] || :',
     T + "CreateNarrowTests.test_sparse_instance_names"),
    ("M3b same, against the real create-instances.sh",
     '[ "${NODE_MACHINE_TYPES[_bench_idx]}" = "${MACHINE_TYPE}" ] || unset "INSTANCE_NAMES[${_bench_idx}]"',
     '[ "${NODE_MACHINE_TYPES[_bench_idx]}" = "${MACHINE_TYPE}" ] || :',
     T + "CreateNarrowTests.test_create_instances_per_type"),
    ("M4 BENCH_NODE_DATADIR_LSSD=1 is accepted without BENCH_FLEET",
     'if [ "${BENCH_NODE_DATADIR_LSSD:-0}" = "1" ] && [ -z "${BENCH_FLEET:-}" ]; then',
     'if [ "${BENCH_NODE_DATADIR_LSSD:-0}" = "1" ] && false; then',
     T + "RefusalTests.test_datadir_lssd"),
    ("M5 BENCH_NODE_ZONES is applied after the zones.env block",
     ZONES_ENV_END,
     ZONES_ENV_END + 'for _bench_item in ${BENCH_NODE_ZONES:-}; do ZONES[${_bench_item%%:*}]="${_bench_item#*:}"; done\n',
     T + "ZonesEnvTests.test_zones_env_wins"),
    ("M6 a scratch variable of the new blocks leaks into the caller",
     "_bench_zones _bench_zarr _bench_lssd", "_bench_zones _bench_zarr",
     T + "KnobUnsetTests.test_no_scratch_variable_survives"),
    ("M7 the e2/n1 x hyperdisk refusal checks MACHINE_TYPE only",
     'for _bench_t in "${NODE_MACHINE_TYPES[@]}"; do', 'for _bench_t in "${MACHINE_TYPE}"; do',
     T + "RefusalTests.test_e2_n1_hyperdisk_per_type"),
    ("M8 a -lssd node gets its data directory on the SSD with the knob at 0",
     "        1:*-lssd) NODE_DATADIR_LSSD[_bench_idx]=1;", "        *:*-lssd) NODE_DATADIR_LSSD[_bench_idx]=1;",
     T + "OptionETests.test_lssd_nodes_with_the_knob_at_0"),
    ("M9 the zone check is loosened to <letters>...-<letter>",
     '! [[ "${_bench_v}" =~ ^[a-z]+-[a-z]+[0-9]+-[a-z]$ ]]', '! [[ "${_bench_v}" =~ ^[a-z].*-[a-z]$ ]]',
     T + "RefusalTests.test_zones"),
    ("M10 the narrowed create keeps the fleet's MACHINE_TYPE",
     NARROW, NARROW.replace('    export MACHINE_TYPE="${BENCH_CREATE_MACHINE_TYPE}"\n', "")
     .replace('= "${MACHINE_TYPE}" ]', '= "${BENCH_CREATE_MACHINE_TYPE}" ]'),
     T + "CreateNarrowTests.test_create_instances_per_type"),
    ("M11 BENCH_CREATE_MACHINE_TYPE is accepted without BENCH_NODE_MACHINE_TYPES",
     '    if [ -z "${BENCH_NODE_MACHINE_TYPES:-}" ]; then', "    if false; then",
     T + "RefusalTests.test_create_machine_type"),
]


def build(dst):
    for rel in FILES:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(R / rel), str(dst / rel))


def run(tree, test):
    return subprocess.run(["python3", "-m", "unittest", "-v", test], cwd=str(tree / "benchmark" / "tests"),
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=600)


def main():
    bad = 0
    for label, old, new, test in CASES:
        with tempfile.TemporaryDirectory(prefix="l1a-mut-", dir=sys.argv[1]) as d:
            pristine, mutated = Path(d) / "pristine", Path(d) / "mutated"
            build(pristine)
            p = run(pristine, test)
            if p.returncode != 0:
                print("BROKEN  %s: %s\n%s" % (label, test, p.stderr[-1500:])); bad += 1; continue
            build(mutated)
            text = (mutated / CFG).read_text(encoding="utf-8")
            if text.count(old) != 1:
                print("ANCHOR  %s: original found %d times" % (label, text.count(old))); bad += 1; continue
            (mutated / CFG).write_text(text.replace(old, new), encoding="utf-8")
            if subprocess.run(["bash", "-n", str(mutated / CFG)]).returncode != 0:
                print("SYNTAX  %s" % label); bad += 1; continue
            p = run(mutated, test)
            if p.returncode == 0 or "AssertionError" not in p.stderr:
                print("SURVIVED %s: %s\n%s" % (label, test, p.stderr[-1500:])); bad += 1; continue
            first = [l for l in p.stderr.splitlines() if l.startswith("AssertionError")][:1]
            print("KILLED  %s -> %s | %s" % (label, test, first[0][:160] if first else ""))
    print("RESULT bad=%d of %d" % (bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
