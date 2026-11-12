"""L1b mutation anchors, run on the sandbox copy (mut/): apply one, run its module, restore."""
import json
import os
import subprocess
import sys

MUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mut")
LIB = "benchmark/bench-lib.sh"

M = [
    ("marker check dropped", LIB,
     'MS="$(findmnt -no SOURCE --mountpoint "$M" 2>/dev/null || true)"\nif [ -e "$S" ]; then',
     'MS="$(findmnt -no SOURCE --mountpoint "$M" 2>/dev/null || true)"\nif false && [ -e "$S" ]; then',
     "test_local_ssd"),
    ("nofail dropped", LIB,
     "ext4 %s,nofail,x-systemd.device-timeout=30s 0 2", "ext4 %s,x-systemd.device-timeout=30s 0 2", "test_local_ssd"),
    ("mkfs over a non-empty directory", LIB,
     '            [ -z "$(ls -A "$M")" ] || lf "$M is not empty"\n', "", "test_local_ssd"),
    ("root-disk refusal dropped", LIB,
     'case "$R" in "$NV"|"$NV"p[0-9]*) lf "$NV holds / ($R)" ;; esac\n', "", "test_local_ssd"),
    ("fallback to another NVMe device added", LIB,
     '[ -e "$L" ] || lf "no $L (a machine type without a local SSD?)"',
     '[ -e "$L" ] || L=/dev/disk/by-id/google-local-nvme-ssd-1\n[ -e "$L" ] || lf "no $L (a machine type without a local SSD?)"',
     "test_local_ssd"),
    ("marker written before the reload", LIB,
     '    chmod 0644 "$U" || lf "chmod $U failed"\n    systemctl daemon-reload || lf "systemctl daemon-reload failed"\n'
     '    # 6. the marker, last: from here on a missing mount is a wiped SSD, never a first time\n'
     '    mkdir -p "${S%/*}" && chmod 0700 "${S%/*}" || lf "mkdir ${S%/*} failed"\n'
     '    (umask 077 && printf \'%s\\n\' "$UU" > "$S.tmp") && mv -f "$S.tmp" "$S" || lf "cannot write the marker $S"\n',
     '    chmod 0644 "$U" || lf "chmod $U failed"\n'
     '    mkdir -p "${S%/*}" && chmod 0700 "${S%/*}" || lf "mkdir ${S%/*} failed"\n'
     '    (umask 077 && printf \'%s\\n\' "$UU" > "$S.tmp") && mv -f "$S.tmp" "$S" || lf "cannot write the marker $S"\n'
     '    systemctl daemon-reload || lf "systemctl daemon-reload failed"\n',
     "test_local_ssd"),
    ("marker written before the mount", LIB,
     '        mount -t ext4 -o "$O" "$NV" "$M" || lf "mount $NV on $M failed"\n',
     '        mkdir -p "${S%/*}" && : > "$S"\n        mount -t ext4 -o "$O" "$NV" "$M" || lf "mount $NV on $M failed"\n',
     "test_local_ssd"),
    ("kept without the UUID comparison", LIB,
     '! uuid_ok "$W" || [ "$UU" != "$W" ]; then', '! uuid_ok "$W"; then', "test_local_ssd"),
    ("device mounted elsewhere not refused", LIB,
     '    [ -z "$T" ] || lf "$NV is mounted on $T (it is not unmounted here)"\n', "", "test_local_ssd"),
    ("drop-in without RequiresMountsFor", LIB,
     "printf '[Unit]\\nRequiresMountsFor=%s\\n' \"$M\" > \"$U\"", "printf '[Unit]\\n' > \"$U\"", "test_local_ssd"),
    ("mount without the root fstab options", LIB,
     '        mount -t ext4 -o "$O" "$NV" "$M" || lf', '        mount -t ext4 -o defaults "$NV" "$M" || lf', "test_local_ssd"),
    ("partition accepted as the namespace", LIB,
     'case "${NV#/dev/nvme}" in *[!0-9n]*) lf "$L is \'$NV\', not an NVMe namespace" ;; esac\n', "", "test_local_ssd"),
    ("check script compares nothing", LIB,
     'if [ -z "$NV" ] || [ "$MS" != "$NV" ]; then\n    echo "PRECFG_FAIL', 'if [ -z "$NV" ]; then\n    echo "PRECFG_FAIL',
     "test_local_ssd"),
    ("check script does not end the session", LIB, "    echo ') || exit 1'\n}", "    echo ') || true'\n}", "test_local_ssd"),
    ("record accepts any by-id", LIB, '$l | capture("^dev=(?<device>/dev/nvme[0-9]+n[0-9]+) by_id=google-local-nvme-ssd-0"',
     '$l | capture("^dev=(?<device>/dev/nvme[0-9]+n[0-9]+) by_id=[^ ]+"', "test_local_ssd"),
    ("record accepts a failed line", LIB, '        "failed "*|failed) echo "❌ bench_lssd_mount_record: ${inst} ${rest}" >&2; return 1 ;;\n',
     "", "test_local_ssd"),
    ("C4 counted as CPUS", LIB, "        c4) echo C4_CPUS ;;\n", "", "test_local_ssd"),
    ("C4 reason dropped", LIB,
     '        C4_CPUS) echo "C4 vCPUs count against', '        C4_CPUS_X) echo "C4 vCPUs count against', "test_local_ssd"),
    ("host probe: a whole disk read as its parent", LIB,
     "names.append(os.path.basename(os.path.dirname(real) if part else real))",
     "names.append(os.path.basename(os.path.dirname(real)))", "test_host_probe"),
    # section 9 (the resumed state)
    ("resume without the emptiness check", LIB,
     '        [ "$(ls -A "$M")" = lost+found ] && [ -d "$M/lost+found" ] && [ ! -L "$M/lost+found" ] \\\n'
     '            && [ -z "$(ls -A "$M/lost+found")" ] \\\n'
     '            || lf "$M is a mount of $NV that holds data and the marker $S is absent: it is neither formatted again nor adopted"\n',
     "", "test_local_ssd"),
    ("resume without the source check", LIB,
     '    if [ -n "$MS" ] && [ "$MS" = "$NV" ]; then\n', '    if [ -n "$MS" ]; then\n', "test_local_ssd"),
    ("resume without the ext4 check", LIB,
     '        [ "$FT" = ext4 ] || lf "$M is a mount of $NV with file system \'${FT:-?}\', not ext4, and the marker $S is absent"\n',
     "", "test_local_ssd"),
]


def main(only=None):
    out = []
    for i, (name, rel, old, new, mod) in enumerate(M):
        if only and str(i) not in only:
            continue
        path = os.path.join(MUT, rel)
        text = open(path).read()
        n = text.count(old)
        if n != 1:
            out.append({"i": i, "name": name, "result": "ANCHOR NOT UNIQUE (%d)" % n})
            print(out[-1], flush=True)
            continue
        open(path, "w").write(text.replace(old, new, 1))
        try:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            p = subprocess.run([sys.executable, "-m", "unittest", mod], cwd=os.path.join(MUT, "benchmark/tests"),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=1800, env=env)
            failing = sorted(set(l.split(" ")[1] for l in p.stdout.splitlines()
                                 if l.startswith(("FAIL: ", "ERROR: "))))
            out.append({"i": i, "name": name, "module": mod, "rc": p.returncode,
                        "result": "killed" if p.returncode else "SURVIVED", "failing": failing})
        finally:
            open(path, "w").write(text)
        print(json.dumps(out[-1]), flush=True)
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
