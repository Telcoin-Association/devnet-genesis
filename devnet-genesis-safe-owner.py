#!/usr/bin/env python3
#
# devnet-genesis-safe-owner.py — devnet-only post-build override (devnet-genesis-build.sh
# step 6): add one extra owner to the governance Safe baked into genesis.yaml.
#
#   python3 devnet-genesis-safe-owner.py <genesis.yaml> <extra-owner> [--safe <addr>]
#
# genesis.yaml is regenerated from scratch by `telcoin genesis` on every build, so this
# runs post-build, like the step-5 threshold override. It edits ONLY the storage map of
# the Safe's alloc block, as raw text (no YAML round-trip): every other byte of the file
# is preserved.
#
# Safe storage layout (GnosisSafe / OwnerManager):
#   slot 2  owners  mapping(address => address), a singly linked list:
#           owners[SENTINEL] = head, owners[a] = next owner, owners[last] = SENTINEL
#   slot 3  ownerCount
#   key of owners[a] = keccak256(pad32(a) . pad32(2)) = `cast index address <a> 2`
#   (stdlib hashlib has SHA3, not keccak, so the keys come from foundry's cast)
#
# The patch is the storage effect of Safe.addOwnerWithThreshold(extra, threshold)
# without the threshold write (step 5 owns slot 4):
#   owners[extra]    := old head      (one inserted storage line, in sorted key order)
#   owners[SENTINEL] := extra         (value of the existing sentinel line replaced)
#   ownerCount       := ownerCount+1  (slot 3, same 32-byte formatting)
#
# Before writing, the owner list is walked from SENTINEL in the patched text and must
# hold ownerCount distinct owners ending at SENTINEL, with extra first.
#
# Idempotent: if owners[SENTINEL] == extra and owners[extra] exists, it re-verifies the
# list, prints "already applied" and exits 0 without writing.
# Exit 1 (message on stderr) on any missing or inconsistent state. Paths come from the
# arguments; the working directory is never used.

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

SENTINEL = "0x0000000000000000000000000000000000000001"
ZERO_ADDR = "0x" + "0" * 40
OWNERS_SLOT = "2"
OWNER_COUNT_SLOT = "0x" + "0" * 63 + "3"
DEFAULT_SAFE = "0x00000000000000000000000000000000000007a0"

ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")
WORD_RE = re.compile(r"^0x[0-9a-f]{64}$")
# Alloc entry header: two-space indent, quoted address, nothing after the colon.
ALLOC_ENTRY_RE = re.compile(r'^  "(0x[0-9a-fA-F]{40})":[ ]*$')
STORAGE_HDR_RE = re.compile(r"^    storage:[ ]*$")
# One storage entry: six-space indent, quoted 32-byte key and value.
STORAGE_LINE_RE = re.compile(r'^(      )"(0x[0-9a-fA-F]{64})": "(0x[0-9a-fA-F]{64})"[ ]*$')


class PatchError(Exception):
    pass


def fail(msg):
    raise PatchError(msg)


def find_cast():
    cast = shutil.which("cast")
    if not cast:
        fail("cast (foundry) not found on PATH; it computes the owners mapping keys")
    return cast


def run_cast(cast, args):
    try:
        out = subprocess.run([cast] + args, check=True, capture_output=True, text=True, timeout=60)
    except subprocess.CalledProcessError as e:
        fail("cast %s failed (exit %d): %s" % (" ".join(args), e.returncode, e.stderr.strip()))
    except subprocess.TimeoutExpired:
        fail("cast %s did not answer within 60 s" % " ".join(args))
    return out.stdout.strip()


def owners_key(cast, addr, cache):
    a = addr.lower()
    if a not in cache:
        k = run_cast(cast, ["index", "address", a, OWNERS_SLOT]).lower()
        if not WORD_RE.match(k):
            fail("unexpected `cast index` output for %s: %r" % (a, k))
        cache[a] = k
    return cache[a]


def pad_addr(addr):
    return "0x" + "0" * 24 + addr[2:].lower()


def word_to_addr(word, what):
    if not word.startswith("0x" + "0" * 24):
        fail("%s holds %s, which is not a 20-byte address" % (what, word))
    return "0x" + word[26:]


def split_lines(text):
    # Split on "\n" only and rejoin with "\n": byte-exact, whatever the line endings.
    return text.split("\n")


def body_eol(line):
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def parse_safe_storage(lines, safe):
    """Locate the Safe alloc block's storage map.

    Returns entries: lowercase key -> (line index, value). The entries sit on
    contiguous lines.
    """
    starts = []
    for i, ln in enumerate(lines):
        m = ALLOC_ENTRY_RE.match(body_eol(ln)[0])
        if m and m.group(1).lower() == safe:
            starts.append(i)
    if not starts:
        fail("Safe alloc block %s not found" % safe)
    if len(starts) > 1:
        fail("Safe alloc block %s appears %d times" % (safe, len(starts)))
    i = starts[0] + 1
    hdr = None
    while i < len(lines) and body_eol(lines[i])[0].startswith("    "):
        if STORAGE_HDR_RE.match(body_eol(lines[i])[0]):
            hdr = i
            break
        i += 1
    if hdr is None:
        fail("Safe alloc block %s has no storage map" % safe)
    entries = {}
    i = hdr + 1
    while i < len(lines):
        body = body_eol(lines[i])[0]
        if body.strip() == "" or body.lstrip().startswith("#"):
            # Valid YAML inside the map, but the generator never writes it and a scan that
            # stopped here could miss a later duplicate key (R1 finding). Refuse.
            fail("blank or comment line %d inside the Safe storage map; refusing to guess where the map ends" % (i + 1))
        if not body.startswith("      "):
            break
        m = STORAGE_LINE_RE.match(body)
        if not m:
            fail("unrecognised storage line %d in the Safe block: %r" % (i + 1, body))
        key, val = m.group(2), m.group(3)
        if key != key.lower() or val != val.lower():
            fail("storage line %d is not lowercase hex; refusing to guess the format" % (i + 1))
        if key in entries:
            fail("duplicate storage key %s in the Safe block" % key)
        entries[key] = (i, val)
        i += 1
    if not entries:
        fail("Safe alloc block %s has an empty storage map" % safe)
    return entries


def walk_owners(cast, entries, count, cache):
    """Follow owners[] from SENTINEL; return the owners in list order."""
    owners = []
    cur = SENTINEL
    while True:
        k = owners_key(cast, cur, cache)
        if k not in entries:
            fail("owner list broken: owners[%s] (slot %s) missing" % (cur, k))
        nxt = word_to_addr(entries[k][1], "owners[%s]" % cur)
        if nxt == SENTINEL:
            break
        if nxt == ZERO_ADDR:
            fail("owner list broken: owners[%s] is the zero address" % cur)
        if nxt in owners:
            fail("owner list has a cycle at %s" % nxt)
        owners.append(nxt)
        if len(owners) > count:
            fail("owner list is longer than ownerCount %d" % count)
        cur = nxt
    if len(owners) != count:
        fail("owner list holds %d owners but ownerCount is %d" % (len(owners), count))
    return owners


def check_extra(cast, extra, safe):
    if not ADDR_RE.match(extra):
        fail("extra owner %r is not a 0x-prefixed 20-byte address" % extra)
    body = extra[2:]
    if body != body.lower() and body != body.upper():
        # Mixed case claims an EIP-55 checksum: hold it to that (typo guard).
        want = run_cast(cast, ["to-check-sum-address", extra.lower()])
        if want != extra:
            fail("extra owner %s fails its EIP-55 checksum (expected %s)" % (extra, want))
    e = extra.lower()
    # Same guards as OwnerManager.addOwnerWithThreshold.
    if e in (ZERO_ADDR, SENTINEL, safe):
        fail("extra owner %s is the zero address, the sentinel or the Safe itself" % e)
    return e


def patch(path, extra_in, safe_in):
    cast = find_cast()
    if not ADDR_RE.match(safe_in):
        fail("--safe %r is not a 20-byte address" % safe_in)
    safe = safe_in.lower()
    extra = check_extra(cast, extra_in, safe)
    cache = {}

    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("%s is not UTF-8" % path)
    lines = split_lines(text)
    entries = parse_safe_storage(lines, safe)

    sent_key = owners_key(cast, SENTINEL, cache)
    if sent_key not in entries:
        fail("sentinel slot owners[%s] (%s) missing from the Safe storage" % (SENTINEL, sent_key))
    if OWNER_COUNT_SLOT not in entries:
        fail("ownerCount slot %s missing from the Safe storage" % OWNER_COUNT_SLOT)
    count = int(entries[OWNER_COUNT_SLOT][1], 16)
    head = word_to_addr(entries[sent_key][1], "owners[SENTINEL]")
    extra_key = owners_key(cast, extra, cache)

    if head == extra:
        if extra_key not in entries:
            fail("inconsistent: owners[SENTINEL] is already %s but owners[%s] (%s) is absent"
                 % (extra, extra, extra_key))
        owners = walk_owners(cast, entries, count, cache)
        print("    already applied: %s heads the Safe owner list (ownerCount %d); %s unchanged"
              % (extra, count, path))
        print("    owner list (%d): %s" % (len(owners), " -> ".join(owners)))
        return 0

    if extra_key in entries:
        fail("owners[%s] (%s) already exists while owners[SENTINEL] is %s: %s is already "
             "linked into the owner list, inserting it at the head would create a cycle"
             % (extra, extra_key, head, extra))
    before = walk_owners(cast, entries, count, cache)

    # 1. owners[SENTINEL] := extra
    s_idx = entries[sent_key][0]
    s_body, s_eol = body_eol(lines[s_idx])
    indent = STORAGE_LINE_RE.match(s_body).group(1)
    lines[s_idx] = '%s"%s": "%s"%s' % (indent, sent_key, pad_addr(extra), s_eol)
    # 2. ownerCount += 1, same 32-byte zero-padded form
    c_idx = entries[OWNER_COUNT_SLOT][0]
    c_eol = body_eol(lines[c_idx])[1]
    lines[c_idx] = '%s"%s": "0x%064x"%s' % (indent, OWNER_COUNT_SLOT, count + 1, c_eol)
    # 3. insert owners[extra] := old head, keeping the map's ascending key order
    new_line = '%s"%s": "%s"%s' % (indent, extra_key, pad_addr(head), s_eol)
    # (a map whose keys are not sorted gets the new line appended at its end)
    by_line = sorted(entries, key=lambda k: entries[k][0])
    at = entries[by_line[-1]][0] + 1
    if by_line == sorted(by_line):
        for k in by_line:
            if k > extra_key:
                at = entries[k][0]
                break
    lines.insert(at, new_line)

    # Self-check on the patched text before anything touches the disk.
    new_entries = parse_safe_storage(lines, safe)
    after = walk_owners(cast, new_entries, count + 1, cache)
    if after != [extra] + before:
        fail("self-check: patched owner list %s != [%s] + %s" % (after, extra, before))

    out = "\n".join(lines).encode("utf-8")
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".safe-owner.", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print("    owners[SENTINEL] (%s): %s -> %s" % (sent_key, head, extra))
    print("    inserted owners[%s] (%s) = %s (line %d)" % (extra, extra_key, head, at + 1))
    print("    ownerCount (slot 0x..03): %d -> %d" % (count, count + 1))
    print("    owner list (%d): %s" % (len(after), " -> ".join(after)))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Add an extra owner to the governance Safe in a TN genesis.yaml (devnet override).")
    ap.add_argument("genesis", help="path to genesis.yaml (edited in place)")
    ap.add_argument("extra_owner", help="address to add at the head of the Safe owner list")
    ap.add_argument("--safe", default=DEFAULT_SAFE,
                    help="Safe alloc address (default %s)" % DEFAULT_SAFE)
    args = ap.parse_args()
    try:
        return patch(args.genesis, args.extra_owner, args.safe)
    except PatchError as e:
        print("❌ Safe owner override: %s (%s)" % (e, args.genesis), file=sys.stderr)
        return 1
    except OSError as e:
        print("❌ Safe owner override: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
