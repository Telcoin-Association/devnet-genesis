#!/usr/bin/env python3
#
# devnet-stake-node5.py — stdlib helpers for devnet-stake-node5.sh. Python only where bash
# cannot do the job safely: a pty, JSON, and integers wider than 64 bits.
#
#   import-key --dir D --name N --expect ADDR   private key on STDIN -> D/N (keystore) + D/N.pw
#   receipt                                     `cast send --json` receipt on stdin -> one line
#   rpc-result                                  JSON-RPC response on stdin -> its result
#   int add|mul|ge|eq A B                       big-integer math on decimal or 0x-hex operands
#
# import-key exists because cast offers no argv-free way to sign with a raw key: `cast send
# --private-key` and `cast wallet import --private-key` both take the key on argv (visible in
# ps and /proc), cast documents the `env://VAR` signer form only for --tempo.sponsor-signer,
# and `cast wallet import -i` reads the key from /dev/tty, so with no terminal it fails
# ("No such device or address"). This helper gives `cast wallet import -i` a private pty and
# types the key into it, so the key travels STDIN -> this process -> pty, never argv or env.
# The keystore password is random (secrets.token_urlsafe), lives only in a 0600 file inside
# the caller's 0700 directory, and is typed the same way. Everything cast prints on the pty is
# swallowed: a pty can echo what was typed, so none of it reaches stdout, stderr or disk. The
# keystore is then opened with `cast wallet address --keystore --password-file` and its
# address must equal --expect. Only that address is printed.
#
# Exit codes: 0 ok, 1 failure (reason on stderr; never a key or password), 2 usage.
import argparse
import json
import os
import pty
import re
import secrets
import select
import subprocess
import sys
import termios
import time

ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
IMPORT_TIMEOUT_SECS = 60


def fail(msg):
    print(f"devnet-stake-node5.py: {msg}", file=sys.stderr)
    sys.exit(1)


def _echo_off(fd):
    # Best effort: clear ECHO on the pty before cast reads from it. Output is swallowed either way.
    try:
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except termios.error:
        pass


def _drive_import(keystore_dir, name, key, password):
    """Run `cast wallet import <name> -k <dir> -i` on a pty, answering its two prompts."""
    pid, fd = pty.fork()
    if pid == 0:  # child: cast, with the pty as its controlling terminal
        try:
            os.execvp("cast", ["cast", "wallet", "import", name, "--keystore-dir", keystore_dir, "-i"])
        finally:
            os._exit(127)
    _echo_off(fd)
    pending = b""
    sent_key = False
    sent_pw = 0
    deadline = time.monotonic() + IMPORT_TIMEOUT_SECS
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if fd not in ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:  # EIO: child closed the pty
                break
            if not chunk:
                break
            pending = (pending + chunk)[-256:].lower()
            if not sent_key and b"private key" in pending:
                os.write(fd, key.encode() + b"\n")
                sent_key, pending = True, b""
            elif sent_key and sent_pw < 2 and b"password" in pending:
                os.write(fd, password.encode() + b"\n")
                sent_pw, pending = sent_pw + 1, b""
        else:
            os.kill(pid, 9)
            fail(f"cast wallet import did not finish within {IMPORT_TIMEOUT_SECS}s")
    finally:
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    rc = os.waitstatus_to_exitcode(status)
    if rc != 0 or not sent_key:
        fail(f"cast wallet import failed (rc {rc}); its output is suppressed because the pty may echo the key")


def cmd_import_key(args):
    if not NAME_RE.match(args.name):
        fail(f"bad keystore name {args.name!r}")
    if not ADDR_RE.match(args.expect):
        fail(f"--expect {args.expect!r} is not a 0x-prefixed 20-byte address")
    st = os.stat(args.dir)
    if (st.st_mode & 0o077) != 0:
        fail(f"{args.dir} must be mode 0700 (it is {oct(st.st_mode & 0o777)})")
    line = sys.stdin.readline().strip()
    if not KEY_RE.match(line):
        fail("stdin is not a 32-byte hex private key (value not shown)")
    key = line if line.startswith("0x") else "0x" + line
    del line
    os.umask(0o077)
    keystore = os.path.join(args.dir, args.name)
    pwfile = keystore + ".pw"
    if os.path.exists(keystore) or os.path.exists(pwfile):
        fail(f"{keystore} already exists")
    password = secrets.token_urlsafe(32)
    fd = os.open(pwfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    _drive_import(args.dir, args.name, key, password)
    del key, password
    if not os.path.isfile(keystore):
        fail(f"cast wallet import reported success but wrote no {keystore}")
    os.chmod(keystore, 0o600)
    res = subprocess.run(
        ["cast", "wallet", "address", "--keystore", keystore, "--password-file", pwfile],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    addr = res.stdout.strip()
    if res.returncode != 0 or not ADDR_RE.match(addr):
        fail(f"could not open the new keystore {keystore}: {res.stderr.strip()[:200]}")
    if addr.lower() != args.expect.lower():
        fail(f"the key in Secret Manager belongs to {addr}, not the expected {args.expect}")
    print(addr)


def cmd_receipt(_args):
    raw = sys.stdin.read()
    try:
        r = json.loads(raw)
    except ValueError:
        fail(f"not a JSON receipt: {raw.strip()[:200]!r}")
    txh = r.get("transactionHash", "?")
    status = str(r.get("status", "?"))
    block = r.get("blockNumber", "?")
    gas = r.get("gasUsed", "?")

    def dec(v):
        try:
            return str(int(v, 0)) if isinstance(v, str) else str(int(v))
        except (TypeError, ValueError):
            return str(v)

    ok = status in ("0x1", "1", "True", "true")
    print(f"tx {txh} status {'1 (success)' if ok else status + ' (FAILED)'} block {dec(block)} gasUsed {dec(gas)}")
    sys.exit(0 if ok else 1)


def cmd_rpc_result(_args):
    raw = sys.stdin.read()
    try:
        r = json.loads(raw)
    except ValueError:
        fail(f"not a JSON-RPC response: {raw.strip()[:200]!r}")
    if not isinstance(r, dict) or "result" not in r:
        fail(f"JSON-RPC error: {json.dumps(r.get('error') if isinstance(r, dict) else r)[:200]}")
    res = r["result"]
    print(res if isinstance(res, str) else json.dumps(res))


def _int(v):
    v = v.strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def cmd_int(args):
    a, b = _int(args.a), _int(args.b)
    if args.op == "add":
        print(a + b)
    elif args.op == "mul":
        print(a * b)
    elif args.op == "ge":
        sys.exit(0 if a >= b else 1)
    elif args.op == "eq":
        sys.exit(0 if a == b else 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("import-key")
    s.add_argument("--dir", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--expect", required=True)
    s.set_defaults(fn=cmd_import_key)
    sub.add_parser("receipt").set_defaults(fn=cmd_receipt)
    sub.add_parser("rpc-result").set_defaults(fn=cmd_rpc_result)
    s = sub.add_parser("int")
    s.add_argument("op", choices=["add", "mul", "ge", "eq"])
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_int)
    args = p.parse_args()
    try:
        args.fn(args)
    except ValueError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
