#!/usr/bin/env python3
"""Read the registry and closing block over RPC to plan and capture a boundary drill."""
import argparse
import json
import time
import urllib.error
import urllib.request

REGISTRY = "0x07E17e17E17e17E17e17E17E17E17e17e17E17e1"
CURRENT_EPOCH = "0xbabc394f"
EPOCH_RECORD = "0x374ed18c"


def rpc(url, method, params):
    """Return a JSON-RPC result, rejecting transport and RPC errors."""
    body = json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.load(response)
    if "error" in result or result.get("result") is None:
        raise ValueError(f"{method} failed: {result.get('error', 'missing result')}")
    return result["result"]


def decode_epoch(encoded):
    """Decode EpochInfo's dynamic tuple: committee, issuance, height, epoch, duration."""
    raw = bytes.fromhex(encoded.removeprefix("0x"))
    if len(raw) < 32 or len(raw) % 32:
        raise ValueError("invalid EpochInfo ABI length")
    offset = int.from_bytes(raw[:32], "big")
    if offset < 32 or offset % 32 or offset + 5 * 32 > len(raw):
        raise ValueError("invalid EpochInfo tuple offset")
    values = [int.from_bytes(raw[offset + i * 32:offset + (i + 1) * 32], "big")
              for i in (2, 3, 4)]
    height, epoch, duration = values
    if height >= 2**64 or epoch >= 2**32 or not 0 < duration < 2**32:
        raise ValueError("invalid EpochInfo scalar")
    return dict(block_height=height, epoch=epoch, duration_secs=duration)


def snapshot(url, epoch=None):
    """Pin the registry read to a block and resolve the preceding closing block."""
    head = rpc(url, "eth_getBlockByNumber", ["latest", False])
    selector = CURRENT_EPOCH if epoch is None else EPOCH_RECORD + f"{epoch:064x}"
    info = decode_epoch(rpc(url, "eth_call", [dict(to=REGISTRY, data=selector), head["number"]]))
    if epoch is not None and info["epoch"] != epoch:
        raise ValueError(f"epoch {epoch} has not opened")
    boundary = rpc(url, "eth_getBlockByNumber", [hex(max(0, info["block_height"] - 1)), False])
    return dict(info, epoch_start_unix=int(boundary["timestamp"], 16),
                start_boundary_block=boundary["number"], start_boundary_hash=boundary["hash"],
                read_head=head["number"], read_unix_ms=time.time_ns() // 1_000_000)


def schedule(info, earliest_kill, before_close, downtime):
    """Select a measured boundary after load begins, then hold across that boundary."""
    duration = info["duration_secs"]
    if not 0 < before_close < duration or downtime <= before_close:
        raise ValueError("kill offset must be within the epoch; downtime must cross the boundary")
    first_kill = info["epoch_start_unix"] + duration - before_close
    extra_epochs = max(0, (earliest_kill - first_kill + duration - 1) // duration)
    kill = first_kill + extra_epochs * duration
    return dict(info, closing_epoch=info["epoch"] + extra_epochs, kill_unix=kill,
                boundary_unix=kill + before_close, restart_unix=kill + downtime,
                seconds_before_close=before_close, downtime_secs=downtime)


def main():
    """Print measured schedule or the block that opened a requested epoch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--epoch", type=int)
    parser.add_argument("--earliest-kill", type=int)
    parser.add_argument("--before-close", type=int, default=59)
    parser.add_argument("--downtime", type=int, default=300)
    args = parser.parse_args()
    if args.epoch is not None and not 0 <= args.epoch < 2**32:
        parser.error("epoch must fit uint32")
    try:
        info = snapshot(args.rpc_url, args.epoch)
        if args.epoch is None:
            if args.earliest_kill is None:
                parser.error("--earliest-kill is required for a schedule")
            info = schedule(info, args.earliest_kill, args.before_close, args.downtime)
        print(json.dumps(info))
    except (ValueError, KeyError, urllib.error.URLError) as error:
        parser.exit(1, f"cannot measure recovery schedule: {error}\n")


if __name__ == "__main__":
    main()
