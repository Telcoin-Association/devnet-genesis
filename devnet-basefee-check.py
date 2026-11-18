#!/usr/bin/env python3
"""devnet-basefee-check.py: read-only verifier for the per-epoch EIP-1559 base fee.

Normally driven by devnet-basefee-check.sh, which resolves the RPC URL and the expected
target from config.sh. Stdlib only, plus the `cast` binary for the WorkerConfigs reads.
Run `--self-test` for the unit tests of the transcribed fee step.

Source of truth: telcoin-network @ 3f9b0709c, tn-contracts submodule @ 10cc12b7d.

The fee step (crates/types/src/gas_accumulator.rs)
  :557-568  compute_next_base_fee_eip1559(cur, gas_used, target)
              target == 0           -> max(cur, 7)
              gas_limit = target.saturating_mul(2)          (BaseFeeParams::ethereum)
              gas_used  = min(gas_used, gas_limit)
              cur       = min(cur, u64::MAX - u64::MAX / 8) (SAFE_MAX_BASE_FEE, :537)
              alloy calc_next_block_base_fee(...), then max(., 7)
  :582-593  next_base_fee_for_config: Eip1559 -> the above; Static{fee} -> fee
  :635-649  entry_fee_for_worker: Eip1559 -> max(data, 7) (data > u64::MAX = error); Static -> value
alloy-eips 1.8.3 (the only alloy-eips in Cargo.lock) src/eip1559/helpers.rs:92-129
  calc_next_block_base_fee(gas_used, gas_limit, base_fee, params)
    gas_target = gas_limit / 2
    ==  -> base_fee
    >   -> base_fee + max(1, base_fee * (gas_used - gas_target) / (gas_target * 8))   (u128 math)
    <   -> base_fee.saturating_sub(base_fee * (gas_target - gas_used) / (gas_target * 8))

What feeds it (crates/tn-reth/src/evm/block.rs:608-680, record_next_epoch_base_fees, the fourth
system call of the epoch-closing block): current fee = the worker's fee for epoch N (the
accumulator slot, seeded at epoch entry from the WorkerConfigs data word at the previous closing
block); gas = the accumulator's gas for the worker (header gas_used of every block of epoch N,
payload_builder.rs:284 inc_block) plus the closing block's own gas. System-call gas never enters
header gasUsed. The result is written to WorkerConfigs.data and becomes epoch N+1's fee.

So for a boundary N -> N+1 this checks:
  fee(N+1) == next_base_fee_for_config(cfg@last(N), fee(N), sum gasUsed[first(N)..last(N)])
with fee(N) = entry_fee_for_worker(cfg@(first(N)-1)) (7 for epoch 0: no prior close), cross-checked
against the headers. Header caveat (crates/engine/src/payload_builder.rs:131-133): an epoch-closing
output with no batches executes one empty block that COPIES ITS PARENT'S baseFeePerGas, so a
zero-tx closing block may carry the previous epoch's fee. Batch blocks carry the batch fee
(:232-233), which the batch validator pins to the epoch fee by exact equality.

Epoch block range: ConsensusRegistry.concludeEpoch stamps the entered epoch's blockHeight as
closing block + 1 (tn-contracts ConsensusRegistry.sol:1415, _updateEpochInfo; asserted node-side at
crates/node/src/manager/node/run_epoch.rs:899-900). first(N) = getEpochInfo(N).blockHeight,
last(N) = getEpochInfo(N+1).blockHeight - 1. tn_getEpochInfo only answers inside the registry's
ring buffer [current-3, current+2] (ConsensusRegistry.sol:410-430); outside it the start
block is bisected on the header nonce (epoch << 32 | round, crates/types/src/helpers.rs:284) and
cross-checked with getCurrentEpochInfo() pinned at the block before it.
"""

import argparse
import json
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

U64_MAX = (1 << 64) - 1
MIN_PROTOCOL_BASE_FEE = 7  # alloy-eips eip1559/constants.rs:21
ELASTICITY_MULTIPLIER = 2  # BaseFeeParams::ethereum()
MAX_CHANGE_DENOMINATOR = 8  # BaseFeeParams::ethereum()
SAFE_MAX_BASE_FEE = U64_MAX - U64_MAX // 8  # gas_accumulator.rs:537

STRATEGY_EIP1559 = 0
STRATEGY_STATIC = 1

WORKER_CONFIGS = "0xFee0FEe0fee0fEE0FEe0fee0FEE0fEe0feE0FEe0"  # crates/config/src/genesis.rs:43
CONSENSUS_REGISTRY = "0x07E17e17E17e17E17e17E17E17E17e17e17E17e1"  # tn-reth system_calls.rs:56
# `cast sig 'getCurrentEpochInfo()'`
SEL_GET_CURRENT_EPOCH_INFO = "0xbabc394f"
# getWorkerConfig(uint16) returns (uint8 strategy, uint64 value, uint184 data):
# tn-contracts @ 10cc12b7d src/consensus/WorkerConfigs.sol:28-31 (struct), :169-171 (getter)
GET_WORKER_CONFIG_SIG = "getWorkerConfig(uint16)(uint8,uint64,uint184)"
WORKER_ID = 0

# Headers per JSON-RPC batch request. 100 is the RPC node's limit: a larger batch is refused
# with -32010 "The batch request was too large" ("Exceeded max limit of 100").
BATCH_SIZE = 100
FETCH_THREADS = 4
BISECT_FANOUT = 64  # probes per bisection round


# --------------------------------------------------------------------------------------------
# The fee step, transcribed integer-for-integer.
# --------------------------------------------------------------------------------------------

def calc_next_block_base_fee(gas_used, gas_limit, base_fee):
    """alloy-eips 1.8.3 calc_next_block_base_fee with BaseFeeParams::ethereum()."""
    gas_target = gas_limit // ELASTICITY_MULTIPLIER
    if gas_used == gas_target:
        return base_fee
    if gas_used > gas_target:
        delta = base_fee * (gas_used - gas_target) // (gas_target * MAX_CHANGE_DENOMINATOR)
        return base_fee + max(1, delta)
    delta = base_fee * (gas_target - gas_used) // (gas_target * MAX_CHANGE_DENOMINATOR)
    return max(0, base_fee - delta)  # saturating_sub


def compute_next_base_fee_eip1559(current_base_fee, gas_used, target_gas):
    """gas_accumulator.rs:557-568."""
    if target_gas == 0:
        return max(current_base_fee, MIN_PROTOCOL_BASE_FEE)
    gas_limit = min(target_gas * ELASTICITY_MULTIPLIER, U64_MAX)  # saturating_mul
    gas_used = min(gas_used, gas_limit)
    current_base_fee = min(current_base_fee, SAFE_MAX_BASE_FEE)
    new_fee = calc_next_block_base_fee(gas_used, gas_limit, current_base_fee)
    if new_fee > U64_MAX:  # unreachable given the two clamps; Rust would panic/wrap here
        raise OverflowError("next base fee left u64: %d" % new_fee)
    return max(new_fee, MIN_PROTOCOL_BASE_FEE)


def next_base_fee_for_config(strategy, value, current_base_fee, gas_used):
    """gas_accumulator.rs:582-593. Unknown strategy ids fall back to Eip1559
    (tn-reth system_calls.rs decode_worker_fee_configs)."""
    if strategy == STRATEGY_STATIC:
        return value
    return compute_next_base_fee_eip1559(current_base_fee, gas_used, value)


def entry_fee_for_worker(strategy, value, data):
    """gas_accumulator.rs:635-650: the fee an epoch is entered on."""
    if strategy == STRATEGY_STATIC:
        return value
    if data > U64_MAX:
        raise ValueError("data word %d exceeds u64::MAX (the node halts on this)" % data)
    return max(data, MIN_PROTOCOL_BASE_FEE)


# --------------------------------------------------------------------------------------------
# RPC plumbing
# --------------------------------------------------------------------------------------------

class RpcError(Exception):
    pass


class Chain(object):
    def __init__(self, url, verbose=False):
        self.url = url
        self.verbose = verbose
        self.requests = 0
        self._starts = {}  # epoch -> first block
        self._bisected = set()
        self._current = None

    def log(self, msg):
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()

    def _post(self, payload, timeout=30):
        # A 100-header batch answers in ~0.3 s; a short timeout retries a stalled request
        # instead of waiting it out.
        body = json.dumps(payload).encode()
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    self.url, data=body, headers={"content-type": "application/json"})
                self.requests += 1
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.load(resp)
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
                self.log("  [rpc] attempt %d failed (%s); retrying" % (attempt + 1, e))
                time.sleep(1.5 * (attempt + 1))
        raise RpcError("RPC %s unreachable: %s" % (self.url, last))

    def call(self, method, params):
        out = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in out:
            raise RpcError("%s%s: %s" % (method, json.dumps(params), json.dumps(out["error"])))
        return out.get("result")

    def batch(self, calls):
        """calls = [(method, params)]; returns results in order. Fails on any item error."""
        payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                   for i, (m, p) in enumerate(calls)]
        out = self._post(payload)
        if not isinstance(out, list):
            raise RpcError("batch request rejected: %s" % json.dumps(out)[:300])
        by_id = {}
        for item in out:
            if "error" in item:
                raise RpcError("batch item %s: %s" % (item.get("id"), json.dumps(item["error"])))
            by_id[item["id"]] = item.get("result")
        if len(by_id) != len(calls):
            raise RpcError("batch returned %d of %d results" % (len(by_id), len(calls)))
        return [by_id[i] for i in range(len(calls))]

    # -- chain views -------------------------------------------------------------------------

    def tip(self):
        return int(self.call("eth_blockNumber", []), 16)

    def chain_id(self):
        return int(self.call("eth_chainId", []), 16)

    def current_epoch_info(self):
        info = self.call("tn_getCurrentEpochInfo", [])
        self._current = int(info["epochId"])
        self._starts[self._current] = int(info["blockHeight"])
        return info

    def headers(self, numbers):
        """Fetch headers (no tx bodies) for `numbers`, BATCH_SIZE per request, in parallel."""
        numbers = list(numbers)
        chunks = [numbers[i:i + BATCH_SIZE] for i in range(0, len(numbers), BATCH_SIZE)]

        def fetch(chunk):
            res = self.batch([("eth_getBlockByNumber", [hex(n), False]) for n in chunk])
            for n, h in zip(chunk, res):
                if h is None:
                    raise RpcError("block %d not found" % n)
            return res

        out = {}
        if not chunks:
            return out
        with ThreadPoolExecutor(max_workers=min(FETCH_THREADS, len(chunks))) as pool:
            for chunk, res in zip(chunks, pool.map(fetch, chunks)):
                for n, h in zip(chunk, res):
                    out[n] = h
        return out

    def worker_config(self, block):
        """getWorkerConfig(WORKER_ID) pinned at `block` via cast -> (strategy, value, data)."""
        cmd = ["cast", "call", "--json", "--rpc-url", self.url, "-b", str(block),
               WORKER_CONFIGS, GET_WORKER_CONFIG_SIG, str(WORKER_ID)]
        last = None
        for attempt in range(3):
            self.requests += 1
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=90)
            if p.returncode == 0:
                vals = json.loads(p.stdout)
                return int(str(vals[0])), int(str(vals[1])), int(str(vals[2]))
            last = p.stderr.strip()
            time.sleep(1.5 * (attempt + 1))
        raise RpcError("cast call getWorkerConfig(%d) @%d failed: %s" % (WORKER_ID, block, last))

    def registry_epoch_at(self, block):
        """ConsensusRegistry.getCurrentEpochInfo() pinned at `block` -> (epochId, blockHeight).
        Return layout: word0 = tuple offset, then (committee offset, epochIssuance,
        blockHeight, epochId, epochDuration, stakeVersion)."""
        raw = self.call("eth_call", [{"to": CONSENSUS_REGISTRY, "data": SEL_GET_CURRENT_EPOCH_INFO},
                                     hex(block)])
        words = raw[2:]
        base = int(words[0:64], 16) * 2
        word = lambda i: int(words[base + 64 * i: base + 64 * (i + 1)], 16)
        return word(3), word(2)

    # -- epoch ranges ------------------------------------------------------------------------

    def current_epoch(self):
        if self._current is None:
            self.current_epoch_info()
        return self._current

    def epoch_start(self, epoch, force_bisect=False):
        """First block of `epoch` (registry blockHeight; 0 for epoch 0)."""
        if epoch in self._bisected or (epoch in self._starts and not force_bisect):
            return self._starts[epoch]
        cur = self.current_epoch()
        if epoch > cur:
            raise RpcError("epoch %d has not started (current %d)" % (epoch, cur))
        if epoch == cur:  # tn_getCurrentEpochInfo already answered; it may have no block yet
            return self._starts[epoch]
        if not force_bisect and epoch >= cur - 3:
            start = int(self.call("tn_getEpochInfo", [epoch])["blockHeight"])
        else:
            start = self.bisect_epoch_start(epoch)
            self._bisected.add(epoch)
        self._starts[epoch] = start
        return start

    def bisect_epoch_start(self, epoch):
        """Smallest block whose header-nonce epoch is >= `epoch`, cross-checked on the registry."""
        if epoch == 0:
            return 0
        tip = self.tip()
        nonce_epoch = lambda h: int(h["nonce"], 16) >> 32
        tip_epoch = nonce_epoch(self.headers([tip])[tip])
        if tip_epoch < epoch:
            raise RpcError("epoch %d has no blocks yet (tip %d is epoch %d)" % (epoch, tip, tip_epoch))
        # invariant: nonce_epoch(lo) < epoch <= nonce_epoch(hi); genesis is epoch 0. Known starts
        # of neighbouring epochs narrow the bracket.
        lo = max([s for e, s in self._starts.items() if e < epoch] or [0])
        hi = min([s for e, s in self._starts.items() if e > epoch and s <= tip] or [tip])
        rounds = probes = 0
        self.log("  [range] epoch %d: bisecting header nonces (epoch << 32 | round) over [%d, %d]"
                 % (epoch, lo, hi))
        while hi - lo > 1:
            span = hi - lo
            step = max(1, span // (BISECT_FANOUT + 1))
            pts = list(range(lo + step, hi, step))[:BISECT_FANOUT]
            hdrs = self.headers(pts)
            rounds += 1
            probes += len(pts)
            for n in pts:
                if nonce_epoch(hdrs[n]) < epoch:
                    lo = n
                else:
                    hi = n
                    break
            self.log("  [range]   round %d: %d probes -> (%d, %d], width %d"
                     % (rounds, len(pts), lo, hi, hi - lo))
        got = nonce_epoch(self.headers([hi])[hi])
        if got != epoch:
            raise RpcError("bisect for epoch %d landed on block %d of epoch %d" % (epoch, hi, got))
        reg_epoch, reg_height = self.registry_epoch_at(hi - 1)
        ok = (reg_epoch, reg_height) == (epoch, hi)
        self.log("  [range]   converged: first(%d) = %d after %d rounds / %d probes; registry "
                 "getCurrentEpochInfo() @%d = (epochId %d, blockHeight %d) %s"
                 % (epoch, hi, rounds, probes, hi - 1, reg_epoch, reg_height,
                    "OK" if ok else "MISMATCH"))
        if not ok:
            raise RpcError("bisected start of epoch %d (%d) disagrees with the registry" % (epoch, hi))
        return hi


# --------------------------------------------------------------------------------------------
# One boundary
# --------------------------------------------------------------------------------------------

COLUMNS = ("boundary", "blocks", "gas_used", "target", "fee_N", "fee_N1_expected",
           "fee_N1_actual", "verdict")
WIDTHS = (11, 7, 13, 20, 20, 20, 20, 7)


def fmt_row(cells):
    return "  ".join(str(c).rjust(w) if i else str(c).ljust(w)
                     for i, (c, w) in enumerate(zip(cells, WIDTHS)))


def check_boundary(chain, n, expect_target, formula_only, force_bisect):
    """Verify fee(n+1) for the closed epoch n -> (verdict, row cells, notes, (first, last))."""
    notes = []
    fails = []
    cur = chain.current_epoch()
    if n + 1 > cur:
        raise RpcError("epoch %d is not closed yet (current epoch %d)" % (n, cur))
    tip = chain.tip()

    first_n = chain.epoch_start(n, force_bisect)
    first_n1 = chain.epoch_start(n + 1, force_bisect)
    last_n = first_n1 - 1
    lo = max(first_n, 1)  # block 0 is genesis: no gas, genesis base fee
    if last_n < lo:
        raise RpcError("epoch %d has an empty block range [%d, %d]" % (n, first_n, last_n))

    # every header of epoch n, plus the parent of its first block (empty-close fee copy)
    hdrs = chain.headers(range(lo - 1, last_n + 1))
    gas_used = 0
    other_worker_blocks = 0
    wrong_epoch = []
    for b in range(lo, last_n + 1):
        h = hdrs[b]
        if (int(h["nonce"], 16) >> 32) != n:  # header nonce = epoch << 32 | round
            wrong_epoch.append(b)
        if int(h["difficulty"], 16) & 0xFFFF != WORKER_ID:  # worker id = low 16 bits
            other_worker_blocks += 1
            continue
        gas_used += int(h["gasUsed"], 16)
    blocks = last_n - lo + 1
    if wrong_epoch:
        fails.append("%d blocks in [%d, %d] whose nonce epoch != %d (first %d)"
                     % (len(wrong_epoch), lo, last_n, n, wrong_epoch[0]))
    if other_worker_blocks:
        notes.append("%d blocks of other workers excluded" % other_worker_blocks)

    # strategy/target used by the close, the recorded next fee, and the entry fee for n
    strategy, target, data_close = chain.worker_config(last_n)
    if n == 0:
        fee_n = MIN_PROTOCOL_BASE_FEE  # epoch 0 keeps the BaseFeeContainer MIN default
    else:
        p_strategy, p_value, p_data = chain.worker_config(first_n - 1)
        try:
            fee_n = entry_fee_for_worker(p_strategy, p_value, p_data)
        except ValueError as e:
            fee_n = p_data
            fails.append("entry word @%d: %s" % (first_n - 1, e))
    try:
        fee_n1_actual = entry_fee_for_worker(strategy, target, data_close)
    except ValueError as e:
        fee_n1_actual = data_close
        fails.append("recorded word @%d: %s" % (last_n, e))
    fee_n1_expected = next_base_fee_for_config(strategy, target, fee_n, gas_used)

    # header cross-check, epoch n: batch blocks carry fee(n); a zero-tx closing block may copy
    # its parent's fee (payload_builder.rs:131-133)
    bad = []
    for b in range(lo, last_n + 1):
        h = hdrs[b]
        fee = int(h["baseFeePerGas"], 16)
        if fee == fee_n:
            continue
        if b == last_n and not h["transactions"] and fee == int(hdrs[b - 1]["baseFeePerGas"], 16):
            notes.append("hdr %d: empty close block copies parent fee" % b)
            continue
        bad.append(b)
    if bad:
        fails.append("%d epoch-%d headers with baseFee != fee_N (first %d)" % (len(bad), n, bad[0]))

    # epoch n+1 side: its first header and the data word at its first block
    if first_n1 <= tip:
        h1 = chain.headers([first_n1])[first_n1]
        n1_is_close = (n + 2 <= cur) and chain.epoch_start(n + 2, force_bisect) == first_n1 + 1
        fee_hdr = int(h1["baseFeePerGas"], 16)
        if fee_hdr != fee_n1_actual:
            if n1_is_close and not h1["transactions"] and fee_hdr == int(hdrs[last_n]["baseFeePerGas"], 16):
                notes.append("hdr %d (sole block of %d): empty close block copies parent fee"
                             % (first_n1, n + 1))
            else:
                fails.append("hdr %d baseFee %d != recorded %d" % (first_n1, fee_hdr, fee_n1_actual))
        s1, v1, d1 = chain.worker_config(first_n1)
        if n1_is_close:
            notes.append("data @%d is epoch %d's own close record" % (first_n1, n + 1))
        elif d1 != data_close:
            fails.append("data word changed between %d and %d (%d -> %d)"
                         % (last_n, first_n1, data_close, d1))
        if (s1, v1) != (strategy, target):
            notes.append("config @%d is now strategy %d target %d" % (first_n1, s1, v1))
    else:
        notes.append("epoch %d has no block yet" % (n + 1))

    # verdict
    target_cell = target if strategy != STRATEGY_STATIC else "static:%d" % target
    inert = strategy != STRATEGY_STATIC and target == U64_MAX
    if strategy not in (STRATEGY_EIP1559, STRATEGY_STATIC):
        notes.append("unknown strategy %d treated as Eip1559 (node fallback)" % strategy)
    formula_ok = fee_n1_expected == fee_n1_actual
    if not formula_ok:
        fails.append("fee step mismatch")
    if inert:
        notes.append("inert target u64::MAX; fee step %s" % ("matches" if formula_ok else "MISMATCH"))
        verdict = "SKIP"
    else:
        if expect_target is not None and (strategy != STRATEGY_EIP1559 or target != expect_target):
            fails.append("target %s != expected eip1559:%d" % (target_cell, expect_target))
        if strategy != STRATEGY_STATIC and not formula_only and gas_used < target:
            fails.append("gas_used < target (no load?)")
        verdict = "FAIL" if fails else "PASS"
    notes = fails + notes  # under SKIP the failures are informational only
    row = ("%d->%d" % (n, n + 1), blocks, gas_used, target_cell, fee_n, fee_n1_expected,
           fee_n1_actual, verdict)
    return verdict, row, notes, (first_n, last_n)


# --------------------------------------------------------------------------------------------
# Self-test: hand cases for the fee step
# --------------------------------------------------------------------------------------------

class FeeStepTests(unittest.TestCase):
    T = 10000000  # the reset genesis target (config.sh WORKER_FEE_CONFIG 0:0:10000000)

    def test_rising_at_cap(self):
        # gas >= 2 * target clamps to gas_limit: delta = fee * T / (T * 8) = fee / 8
        self.assertEqual(compute_next_base_fee_eip1559(8000, 900000000, self.T), 9000)
        # live devnet 1028 -> 1029 (target 1e6, 10,611,907 gas)
        self.assertEqual(compute_next_base_fee_eip1559(5625227823087, 10611907, 1000000),
                         6328381300972)

    def test_falling_at_cap(self):
        # gas 0: delta = fee * T / (T * 8) = fee / 8, floored division
        self.assertEqual(compute_next_base_fee_eip1559(8000, 0, self.T), 7000)
        # live devnet 1030 -> 1031 (target 1e6, 0 gas): 7119428963593 - 889928620449
        self.assertEqual(compute_next_base_fee_eip1559(7119428963593, 0, 1000000), 6229500343144)

    def test_floor_clamps_to_7(self):
        self.assertEqual(compute_next_base_fee_eip1559(7, 0, self.T), 7)  # 7 - 0 (7*T//(8T)=0)
        self.assertEqual(compute_next_base_fee_eip1559(8, 0, 1), 7)  # 8 - 1, the TN unit case
        self.assertEqual(compute_next_base_fee_eip1559(1, 0, self.T), 7)  # below-floor input
        self.assertEqual(entry_fee_for_worker(STRATEGY_EIP1559, self.T, 0), 7)  # unwritten word

    def test_min_plus_one_when_rising(self):
        # from the floor: 7 * T / (T * 8) = 0 -> max(1, 0) = 1, the first reset boundary 0 -> 1
        self.assertEqual(compute_next_base_fee_eip1559(7, 900000000, self.T), 8)
        # just over target: 1000 * 1 / (T * 8) = 0 -> +1
        self.assertEqual(compute_next_base_fee_eip1559(1000, self.T + 1, self.T), 1001)

    def test_gas_equals_target_unchanged(self):
        self.assertEqual(compute_next_base_fee_eip1559(123456789, self.T, self.T), 123456789)
        self.assertEqual(compute_next_base_fee_eip1559(1000, 500, 500), 1000)  # TN unit case

    def test_partial_and_edges(self):
        # 1.5 * T: delta = 8000 * 0.5T / (8T) = 500
        self.assertEqual(compute_next_base_fee_eip1559(8000, 15000000, self.T), 8500)
        self.assertEqual(compute_next_base_fee_eip1559(1000, 1000, 500), 1125)  # TN unit cases
        self.assertEqual(compute_next_base_fee_eip1559(1000, 0, 500), 875)
        self.assertEqual(compute_next_base_fee_eip1559(1000, 500, 0), 1000)  # zero target
        base = 10 ** 18  # TN overflow_safety_large_values
        self.assertEqual(compute_next_base_fee_eip1559(base, U64_MAX, 1), base + base // 8)
        # inert target u64::MAX: gas_limit saturates, gas_target = u64::MAX // 2, so any real
        # load reads as ~0 %: delta = 8000 * (gt - 9e8) // (8 gt) = 999 (just under fee / 8)
        self.assertEqual(compute_next_base_fee_eip1559(8000, 900000000, U64_MAX), 7001)
        # worst case stays inside u64: fee clamps to SAFE_MAX, gas to the saturated limit
        worst = compute_next_base_fee_eip1559(U64_MAX, U64_MAX, U64_MAX)
        self.assertTrue(SAFE_MAX_BASE_FEE < worst <= U64_MAX)
        self.assertEqual(next_base_fee_for_config(STRATEGY_STATIC, 42, 9999, 0), 42)


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description="Verify per-epoch EIP-1559 base-fee steps (read-only).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--epoch", type=int, metavar="N", help="check boundary N -> N+1")
    mode.add_argument("--last", type=int, metavar="K", help="check the last K closed boundaries")
    mode.add_argument("--watch", action="store_true",
                      help="poll tn_getCurrentEpochInfo; check each boundary as it closes")
    mode.add_argument("--self-test", action="store_true", help="run the fee-step unit tests")
    ap.add_argument("--rpc", metavar="URL", help="JSON-RPC endpoint")
    ap.add_argument("--expect-target", metavar="GAS|any", default="any",
                    help="required EIP-1559 target for worker 0 (default any)")
    ap.add_argument("--formula-only", action="store_true",
                    help="do not FAIL a boundary whose gas_used is below target")
    ap.add_argument("--interval", type=int, default=30, metavar="SECS", help="--watch poll period")
    ap.add_argument("--count", type=int, default=0, metavar="M",
                    help="--watch: stop after M boundaries (0 = run until interrupted)")
    ap.add_argument("--bisect", action="store_true",
                    help="locate epoch ranges by header-nonce bisection even inside the "
                         "tn_getEpochInfo window (exercises the fallback)")
    args = ap.parse_args(argv)

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FeeStepTests)
        ok = unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
        return 0 if ok else 1
    if not args.rpc:
        ap.error("--rpc is required")
    expect = None if args.expect_target == "any" else int(args.expect_target)

    chain = Chain(args.rpc)
    t0 = time.time()
    try:
        info = chain.current_epoch_info()
        tip = chain.tip()
        cur = int(info["epochId"])
        s, v, d = chain.worker_config(tip)
        print("rpc %s  chain %d  tip %d  current epoch %d (started @%d, duration %ss)"
              % (args.rpc, chain.chain_id(), tip, cur, int(info["blockHeight"]), info["epochDuration"]))
        print("WorkerConfigs(%d) @latest(%d): strategy %d (%s)  target %d%s  data %d  | expected "
              "target %s" % (WORKER_ID, tip, s, {0: "eip1559", 1: "static"}.get(s, "unknown"), v,
                             " (INERT u64::MAX)" if v == U64_MAX and s != STRATEGY_STATIC else "",
                             d, "any" if expect is None else expect))
        print(fmt_row(COLUMNS) + "  notes")
        sys.stdout.flush()

        verdicts = []

        def run(n):
            b0 = time.time()
            verdict, row, notes, rng = check_boundary(chain, n, expect, args.formula_only,
                                                      args.bisect)
            verdicts.append(verdict)
            extra = "blocks %d..%d, %.1fs" % (rng[0], rng[1], time.time() - b0)
            print(fmt_row(row) + "  " + "; ".join(notes + [extra]))
            sys.stdout.flush()

        if args.epoch is not None:
            run(args.epoch)
        elif args.last is not None:
            for n in range(max(0, cur - args.last), cur):
                run(n)
        else:
            seen = cur
            done = 0
            chain.log("watching: current epoch %d, polling every %ds" % (seen, args.interval))
            try:
                while args.count == 0 or done < args.count:
                    time.sleep(args.interval)
                    now = int(chain.current_epoch_info()["epochId"])
                    for n in range(seen, now):
                        run(n)
                        done += 1
                        if args.count and done >= args.count:
                            break
                    seen = max(seen, now)
            except KeyboardInterrupt:
                pass
    except RpcError as e:
        sys.stderr.write("error: %s\n" % e)
        return 2

    nfail = verdicts.count("FAIL")
    print("summary: %d boundaries  PASS %d  FAIL %d  SKIP %d  | %d RPC requests, %.1fs wall"
          % (len(verdicts), verdicts.count("PASS"), nfail, verdicts.count("SKIP"),
             chain.requests, time.time() - t0))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
