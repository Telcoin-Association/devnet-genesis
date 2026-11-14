#!/usr/bin/env python3
"""Per-arm summary of a bench run: one row per arm and blast type, with its window and drift correction.

Usage:
  arms-summary.py --run-dir results/<run> [--out-dir DIR] [--prefiltered DIR] [--cache-dir DIR]
                  [--types T[,T...]] [--drift-axis chain-mtx|wall-min] [--no-stages] [--jobs N]
                  [--disk-iops N] [--disk-mibps N]
  arms-summary.py --self-check [--results-root DIR] [--out-dir DIR] [--no-stages] [--jobs N]

Writes <out-dir>/arms.md and <out-dir>/arms.json (default out-dir: <run-dir>/analysis).

Rows. An arm is a manifest param_arms[] entry; its window runs from `ready` (else `begin`) to `end`.
A run without param_arms[] (bench 5 and older) is one implicit arm, `implicit`, over the whole run.
Each blast (every blast-<i>-<UTC>/blasters/ and the main blasters/ directory, whose index is
blast.run_index) is one row, under its blasts[].arm or else the arm in force when its window starts;
each arm's marks[] (the idle windows) are rows of type I. A blast blasts[] does not list (run by
hand: fund and run, as tools/../launch/run-arms.sh runs every blast of run 1) takes its senders and
window from its generators' run.args and its rc from manifest blast_runs[] (else from the manifest
copy archived with it); a blast_runs[] run that left no blasters/ directory is listed too. A blast's
window is the span in which every one of its generators was in its mixed phase (the blasters' own
run.phases), else its recorded real mixed phase, clipped to the arm's window and cut at the first
chaos action inside it (an archived blast's from its manifest copy). Blasts whose rc is not 0 are
listed, not measured. The type is the first row of TYPES that matches the blast. An arm that repeats
the switch state of the arm before it (a resumed arm, <name>-r2) keeps that arm's roles.

Switch list. A run is read with the switch list of its build (the roles, the controls, the switches-on
column): arms/switches.tsv (the live build) or a retired build's arms/switches-<build>.tsv, the one that
shares the most keys with the run's param_arms[].switches states (report/provenance.py run_switch_rows).
When param_arms[] records no state, the keys on the nodes' 'node switches' lines decide and a note names
the list; a tie or no key in either place gives the live list, with a note when the run has param_arms[].

Columns (each "n/a (missing: <what>)" when its input is absent; never a silent zero):
  chain tx/s     sum of tx_count over the blocks timestamped in the window (every generator's block
                 table, de-duplicated by number) / seconds
  landed tx/s    the blast's generators' own landings per second (series.per_second own_tx)
  land, seen     p50/p95 seconds, the generators' pooled histograms (report/kpis.py pooled_latency:
                 mixed-phase submissions of the whole blast, not cut to the window)
  engine         per node, from the node log: execute and persist us/tx ("output executed"), commit
                 us/tx and ms per output ("persisted output"), task us/tx ("output execution task
                 finished" joined on consensus_number); the fleet value is the validators' median
  amplification  per node: persist CSV disk_wr_bytes_total delta between the first and the last 30-s
                 sample inside the window / ((page_newly + page_cow) x 4096) summed over the
                 "persisted output" lines between those two samples; fleet = median of the nodes
  rr / vma       the last 300-s persist sample in the window: mdbx_dat_rr_bytes / mdbx_dat_vma_bytes
  certification  per validator, tools/cert-rate.py (imported, unmodified) over the same log files:
                 own headers certified (quorum / proposed) and own certificates committed
  landings       sampled landings rows (1 in run.args.landings_sample) of the mixed phase with
                 seen_ms - submit_ms >= 300 s; resends = totals.resends summed over the generators
                 (total = transient + other + gap_txs + resign_nonce + resign_fee);
                 late = run.tail_scan.landed_late summed; late_secs = max of manifest blasters[]
  silent         the longest run of seconds in the window in which a generator made no send call
                 (series.send_per_second: submitted + resent + resigned == 0), max over generators
  stages         tools/stage-latency.py (imported) with the rows as its windows: chain seen p50/p95
                 and the S10 / S11 / S12 p50
  drift          inside each row: commit s/output = a + b x (txs/1000) + c x minutes since the window
                 start, least squares over the validators' whole minutes (I-3's model: per validator and
                 minute, the mean commit and txs per output; b is dropped when the output size never
                 varies). Across arms: the
                 first and the last control arm (every switch at its default) with the same blast type
                 give a slope of commit us/tx and ms/output along the drift axis (cumulative chain
                 transactions, in millions, at the window's midpoint; or wall minutes); every row of
                 that type gets its commit cost raw and corrected to the first control's position.
                 When the commit us/tx moved more than 15 % between the two controls, only adjacent
                 arms are compared (the flag is in the header and in the drift block).
  bench-6 inputs (a second table; names from tasks/bench6-contract.md, fields read by name in any order; None
  where the arm's switch is off):
    storage      prefault_ratio_by_node / _min / prefault_on_all: sum(page_prefault) over the window's persists after
                 the first / growth of mdbx_last_pgno (on >= 0.9); advice arms: advice_on_by_node by what the node
                 measured (mdbx_advised_bytes > 0 on its lines, else the gauge tn_reth_mdbx_random_advice_bytes in
                 metrics.json, and no 'advice not applied' warning since the arm's begin), mdbx_advised_min_bytes,
                 mdbx_advised_all_nodes, storage_note naming a node where it is not in force; refault_per_min,
                 majfault_per_min, memcg_refault_per_min per node (persist CSV counters, per minute between the first
                 and last sample in the window) and their medians. A field left off a 'persisted output' line makes
                 the sum it feeds (amplification, proc_written_bytes, page_*) n/a, never 0.
    recovery     recovery arms: recovery_pool_by_node (true when every 'signers recovered' line in the window says
                 pool=dedicated and no 'signer recovery pool failed to build' warning since the arm's begin; the
                 switch line and gauge read the threads even then), recovery_pool_note naming a node not on it
    sealed keep  sealed_keep: "acting" when every validator's 'batch builder started' since the arm's begin says
                 keeps_sealed=true, else "switch not acting (...)"; sealed_marked_peak (metrics.json gauge)
    bound        admission_refused (the node counter's increase, metrics.json, by the collector's window_count rule:
                 a drop is a restart and adds the new value; a series first seen inside the window on a node
                 sampled before counts from 0), gen_pool_full (nodes[].errors, whole
                 blast), gen_dropped (totals.resends.dropped); the admitted transactions' latency is land p50 / p95
    grace        grace_share_pct, grace_wait_p50_ms / _p90_ms (grace_ms > 0 on the validators' 'header proposed'),
                 grace_outcomes ('parent grace ended'), grace_nodes_certified_min_pct beside the committed share
    vote fix     exec_policy_pct, exec_lag_p50 (exec_tip - exec_block), votes_refused_behind per voter
    cycle        commit_interval_ms (median gap between 'persisted output' lines, validators' median) on every row:
                 a pipelined arm (pipelined) is compared on it, not on task us/tx (D55); its proc_written_bytes
                 carries proc_written_bytes_upper_bound (D56)
    disk         (D84) per node, from the persist CSV's /proc/diskstats counters between the first and the last sample in
                 the window that carry them (the sampler's 30-s rows): wr_ops_per_output (write operations / 'persisted
                 output' lines between the samples), wr_kib_per_op, flush_ops_per_output, wr_iops and wr_mibps (the
                 increase / the seconds between the samples: sustained, as the probe's cycle_iops), wr_iops_peak and
                 wr_mibps_peak (the busiest step between two consecutive samples: a 30-s mean, not an instant),
                 wr_ms_per_op and flush_ms_per_op (device ticks / operations), iops_pct_of_cap and mibps_pct_of_cap
                 (the sustained rates against the provisioned caps), binds (iops | throughput: the larger share when it
                 is >= 80 %; neither below), cap_floor_ms_per_output (the least device time the caps allow one output's
                 writes); <column>_median over the nodes, binds_nodes, and disk_reading, one line with the thresholds
                 named ("no node above 50 % of either cap" when every share is <= 50). The caps are --disk-iops /
                 --disk-mibps, else the manifest's node_disk (the provisioning the deploy asked for), else n/a. The
                 counters are the whole disk under the sampler's data dir (/var/lib/telcoin, its st_dev's disk, a
                 partition's parent; PERSIST_DISK overrides): on the fleet the boot disk, so logs, the consensus DB and
                 every other writer on it count too, and wr_ops_per_output is an upper bound for the persist's own.
                 The probe's commit_iops (operations / commit seconds) is not used: it reads 4-8x the cap on the probe
                 itself, so it is not a device rate.
    tn-lmdb      (bench 7) only when a node's store is tn-lmdb (its 'opening database' line says backend=tn-lmdb,
                 else its persist CSV carries tn_lmdb_dat_size_bytes): store_by_node at the top, and per node and
                 row (the validators' median): wr_ops_per_tx and wr_bytes_per_tx (the device's write count AND
                 bytes between the first and the last 30-s sample in the window / the transactions on the
                 'persisted output' lines between them), save_blocks_ms_output (the mean save_blocks_ms of those
                 lines in the window), store_growth_bytes_per_tx (the increase of tn_lmdb_used_bytes +
                 static_files_size_bytes between the first and the last sample carrying both / those
                 transactions); beside the disk columns that hold on any store (wr_kib_per_op, the mean write size;
                 flush_ops_per_output, the syncs; commit_ms_output). On such a node amp reads n/a (MDBX page
                 counts, which tn-lmdb does not log) and rr / vma comes from tn_lmdb_dat_rr_bytes /
                 tn_lmdb_dat_vma_bytes. A run whose stores are all MDBX or unknown summarizes as before, byte
                 for byte.
    local SSD    (bench 6) only when an instance carries data_disk (the deploy with BENCH_NODE_DATADIR_LSSD=1): a node
                 whose instances[].data_disk.class is local-ssd has no provisioned caps, so its shares, binds and
                 cap floor read "n/a (local SSD, no provisioned caps)" and its rates stay measured; --disk-iops /
                 --disk-mibps and node_disk are the boot-disk nodes' caps only (disk_caps; disk_caps_by_node beside
                 it when a node is local-SSD). Per node disk_class (local-ssd | boot); disk_reading has one clause
                 per disk class (the boot-disk clause in the wording above) and names the machine types of a class
                 that spans more than one. When the validators fall into more than one (disk class, machine type)
                 group (machine type: instances[].machine_type, else the manifest's machine_type), by_disk_class
                 lists each group's validators and their medians (statistics.median: an even count takes the mean
                 of the middle two) of the engine, amplification, refault and disk columns, arms.md prints them in
                 a "by disk class" table and the row heading names the groups; the fleet medians stay over all
                 validators.
  verdict        the CHECKS rows that apply to the arm's role (from the topic of the switches it
                 turned on, switches.tsv) and the row's type: "<threshold>: <value> met|not met", or
                 n/a with the missing input. No other judgement.
  votes          vote_lock_p95_ms (lock_ms on the validators' 'vote path timing' lines in the window) and
                 behind_per_header_max (the most voters that refused one header as behind). (bench 7) Only when a
                 line in a window carries prelock_wait_ms: vote_total_p50_ms / vote_total_p95_ms (total_ms, a
                 request's whole path on the voter, from its arrival to the answer), vote_prelock_p95_ms
                 (prelock_wait_ms, the wait before the vote lock, where vote_queue_fix moves the wait for execution
                 out of lock_ms; a line without the field counts 0), votes_superseded (refused because a newer
                 request of the same author had arrived), votes_refused_superseded per voter, and the vote gate
                 reads total_ms p95 instead of lock_ms p95 (CHECK_REPLACES), so an arm with the switch on and one
                 with it off are measured alike. A run without the field summarizes as before, byte for byte.

Logs. Per node the files are stage-latency.py's choice ({node}-unit-stdout*.log*, else every
{node}-*.log* but stderr). They are read from --prefiltered (default benchmark/work/prefilter/<run>/,
the teardown's grep pass) when that directory has the node's files and tools/log-shapes.txt holds
every literal this tool, cert-rate.py and stage-latency.py match; otherwise from the run's logs/,
streamed once through `gzip -dc | grep -F` (python gzip when those are missing) into --cache-dir
(default benchmark/work/arms-summary/<run>/), which later runs reuse.

--self-check runs on bench 5 (results/r20261107-1504, read-only; output under
benchmark/work/bench6-scratch/H7b/self-check unless --out-dir) with --types M4,M16 and compares the
two windows and chain tx/s with the I-3 recut (600 x 4: 16:57:31-17:02:55, 3,868.5 tx/s; 600 x 16
to the kill: 17:41:01-17:54:44, 3,466.2 tx/s) and checks every bench-6-only column is n/a.

Exit status: 0 = written (self-check: every figure matched); 1 = bad arguments or unreadable
input; 2 = no row; 3 = self-check mismatch. Stdlib only (plus the sibling tools it imports).
"""
import argparse
import bisect
import collections
import concurrent.futures
import csv
import datetime
import fnmatch
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

# ---- FIELDS (begin): every name this tool reads from another writer, spelled once. A rename is a one-line edit.
F = {
    # node log lines (message text) and their fields; the page_* and proc_write_bytes fields are U3's (contract, FROZEN)
    "msg_persisted": "persisted output", "msg_executed": "output executed",
    "msg_task": "output execution task finished", "msg_vote": "vote path timing",
    "lit_tracker": "Failed to track spawned task",
    "f_epoch": "epoch", "f_cn": "consensus_number", "f_txs": "txs", "f_commit_ms": "commit_ms",
    "f_execute_ms": "execute_ms", "f_persist_ms": "persist_ms", "f_task_ms": "task_ms",
    "f_newly": "page_newly", "f_cow": "page_cow", "f_spill": "page_spill", "f_unspill": "page_unspill",
    "f_prefault": "page_prefault", "f_wops": "page_wops", "f_msync": "page_msync", "f_proc_write": "proc_write_bytes",
    "f_author": "author", "f_round": "round", "f_outcome": "outcome", "f_lock_ms": "lock_ms", "v_behind": "behind",
    # bench-6 node lines (tasks/bench6-contract.md "Node log lines and metrics"); read by name, any field order
    "f_last_pgno": "mdbx_last_pgno", "f_advised": "mdbx_advised_bytes",
    # bench-7 node lines (tn-lmdb store): the engine the node opened, and the persist's save_blocks phase
    "msg_open_db": "opening database", "f_backend": "backend", "v_tn_lmdb": "tn-lmdb", "v_mdbx": "MDBX",
    "f_save_ms": "save_blocks_ms",
    # bench-7 'vote path timing' fields and outcome (vote_queue_fix: the wait for execution moves before the vote lock)
    "f_total_ms": "total_ms", "f_prelock_ms": "prelock_wait_ms", "v_superseded": "superseded",
    # the node's switch line (report/provenance.py): its keys tell a run's build when param_arms[] records no state
    "msg_switches": "node switches",
    # report/provenance.py run_switch_rows(manifest, starts): a start's logged switch state
    "pv_start_switches": "switches",
    "msg_proposed": "header proposed", "f_grace_ms": "grace_ms", "f_exec_policy": "exec_policy",
    "f_exec_tip": "exec_tip", "f_exec_block": "exec_block",
    "msg_grace_ended": "parent grace ended", "f_waited_ms": "waited_ms",
    "msg_builder": "batch builder started", "f_keeps_sealed": "keeps_sealed", "v_true": "true",
    "msg_advice_refused": "mdbx random-access advice not applied; the database works without it",
    "msg_recovered": "signers recovered", "f_pool": "pool", "v_dedicated": "dedicated",
    "msg_pool_failed": "signer recovery pool failed to build - recovering on the global pool",
    # metrics.json (deploy step 15) prometheus.series and the generator's error classes (tn-blast nodes[].errors)
    "m_prom": "prometheus", "m_series": "series", "m_by_node": "by_node",
    "p_sealed_marked": "tn_reth_sealed_txs_marked", "p_refused": "tn_reth_rpc_admission_refused_total",
    "p_advice_bytes": "tn_reth_mdbx_random_advice_bytes",
    "b_nodes": "nodes", "b_errors": "errors", "b_pool_full": "pool_full", "b_r_dropped": "dropped",
    # switches.tsv keys whose arms read the columns below
    "sw_advice": "mdbx_random_advice", "sw_sealed": "sealed_tx_keep", "sw_bound": "rpc_admission_backlog_outputs",
    "sw_grace": "parent_grace", "sw_vote": "quorum_exec_block", "sw_pipelined": "pipelined_persist",
    "sw_recovery": "recovery_threads",
    # persist CSV (benchmark/tools/persist-csv-header.txt)
    "c_ts": "ts_unix", "c_disk_wr": "disk_wr_bytes_total", "c_vma": "mdbx_dat_vma_bytes", "c_rr": "mdbx_dat_rr_bytes",
    "c_size": "mdbx_dat_size_bytes", "c_refault": "vm_workingset_refault_file_pages_total",
    "c_majfault": "vm_pgmajfault_total", "c_memcg_refault": "memcg_workingset_refault_file_pages_total",
    "c_wr_ios": "disk_wr_ios_total", "c_wr_ticks": "disk_wr_ticks_ms_total", "c_flush_ios": "disk_flush_ios_total",
    "c_flush_ticks": "disk_flush_ticks_ms_total",
    # bench 7 (node-persist-sampler.sh on a tn-lmdb data dir)
    "c_lmdb_size": "tn_lmdb_dat_size_bytes", "c_lmdb_used": "tn_lmdb_used_bytes", "c_static_size": "static_files_size_bytes",
    "c_lmdb_vma": "tn_lmdb_dat_vma_bytes", "c_lmdb_rr": "tn_lmdb_dat_rr_bytes",
    # manifest node_disk (bench-lib.sh bench_manifest_init: the requested NODE_DISK_IOPS / NODE_DISK_THROUGHPUT, MiB/s)
    "m_node_disk": "node_disk", "m_prov_iops": "provisioned_iops", "m_prov_tput": "provisioned_throughput",
    # manifest instances[].data_disk and machine_type (bench 6 local SSD, arms/MANIFEST-FIELDS.md "Local-SSD deployment")
    "m_data_disk": "data_disk", "m_dd_class": "class", "v_lssd": "local-ssd", "v_boot": "boot",
    "m_machine_type": "machine_type",
    # arms.json by_disk_class group keys and engine_by_node[].disk_class (they share spellings with the names above)
    "o_disk_class": "disk_class", "o_machine_type": "machine_type", "o_nodes": "nodes",
    # switches.tsv columns
    "s_key": "key", "s_default": "default", "s_topic": "topic",
    # manifest (benchmark/arms/MANIFEST-FIELDS.md)
    "m_arms": "param_arms", "m_name": "name", "m_begin": "begin", "m_ready": "ready", "m_end": "end",
    "m_switches": "switches", "m_host": "host", "m_step": "step", "m_nodes": "nodes", "m_evict": "evict-mdbx",
    "m_res_after": "resident_pages_after", "m_marks": "marks", "m_label": "label",
    "m_blasts": "blasts", "m_index": "index", "m_senders": "senders", "m_window": "window", "m_chaos": "chaos",
    "m_arm": "arm", "m_phases": "phases", "m_planned": "phases_planned", "m_rc": "rc",
    "m_start": "start", "m_ts": "ts", "m_action": "action", "m_node": "node", "m_blasters": "blasters",
    "m_late": "late_secs", "m_blast": "blast", "m_run_index": "run_index", "m_instances": "instances",
    "m_role": "role", "m_run_id": "run_id", "v_validator": "validator", "v_observer": "observer",
    "m_blast_runs": "blast_runs", "v_run_action": "run", "m_abort": "abort", "m_start_at": "start_at",
    # blaster JSON (tn-blast/v2; send_per_second, resends: H9a; tail_scan: H9b)
    "b_schema": "schema", "b_run": "run", "b_start_unix": "start_unix", "b_end_unix": "end_unix",
    "b_args": "args", "b_senders": "senders", "b_window": "window", "b_duration": "duration_secs", "b_sample": "landings_sample", "b_label": "label",
    "b_blocks": "blocks", "b_columns": "columns", "b_rows": "rows", "b_number": "number", "b_timestamp": "timestamp",
    "b_tx_count": "tx_count", "b_series": "series", "b_ps_cols": "per_second_columns", "b_ps": "per_second",
    "b_ps_t0": "per_second_t0_unix", "b_own_tx": "own_tx", "b_send_cols": "send_per_second_columns",
    "b_send": "send_per_second", "b_send_t0": "send_per_second_t0_unix", "b_s": "s", "b_submitted": "submitted",
    "b_resent": "resent", "b_resigned": "resigned", "b_totals": "totals", "b_resends": "resends",
    "b_r_transient": "transient", "b_r_other": "other", "b_r_gap_txs": "gap_txs", "b_r_nonce": "resign_nonce",
    "b_r_fee": "resign_fee", "b_tail": "tail_scan", "b_landed_late": "landed_late", "b_unlanded_after": "unlanded_after",
    "v_mixed": "mixed",
    # landings rows (landings-<label>.ndjson.gz)
    "l_submit": "submit_ms", "l_seen": "seen_ms", "l_phase": "phase",
    # report/kpis.py pooled_latency, tools/cert-rate.py and tools/stage-latency.py outputs
    "k_ts": "ts_ms", "k_seen": "seen_ms", "k_p50": "p50", "k_p95": "p95",
    "r_windows": "windows", "r_nodes": "nodes", "r_rate": "rate_pct", "r_not_committed": "not_committed_pct",
    "r_proposed": "proposed",
    "t_headline": "headline", "t_pooled": "pooled", "t_seen50": "seen_p50_s", "t_seen95": "seen_p95_s",
    "t_p50ms": "p50_ms", "t_count": "count", "t_wstart": "start_unix", "t_wend": "end_unix",
}
# switches.tsv topic -> the arm role whose "must show" thresholds apply when an arm turns that topic on.
TOPIC_ROLES = {
    "mdbx-advice": "persist", "quorum-exec-block": "vote", "voter-lock": "vote", "sealed-keep": "pool",
    "digest-dedupe": "pool", "recovery-pool": "pool", "tracker-drain": "pool", "pipelined-persist": "pipe",
    "inflight-bound": "bound", "parent-grace": "grace",
}
HOST_ROLE = "persist"                                        # an arm that adds a host step (evict, read-ahead)
GRACE_NODES = ("bench-validator-02", "bench-validator-06")   # the plan's v02 / v06 (London, Netherlands)
CERT_RATE, STAGE_LATENCY, KPIS = "cert-rate.py", "stage-latency.py", "kpis.py"
LOG_SHAPES = "log-shapes.txt"
# ---- FIELDS (end)

# Blast types, first match wins: (type, senders, window, minimum planned mixed seconds or None).
TYPES = (("L", 8, 16, None), ("M4", 600, 4, None), ("M16", 600, 16, 400), ("M16s", 600, 16, 0))
IDLE_TYPE = "I"
IMPLICIT_ARM = "implicit"
CONTROL, DRIFT = "control", "drift"
# The plan's "must show" thresholds (W4 run-1 table): (role, label, row types or None for every type,
# metric key of the row, operator, threshold). A metric that is n/a makes the check n/a.
CHECKS = (
    (CONTROL, "amplification > 1.2 (bench-5 signature)", ("M16",), "amp_fleet_median", ">", 1.2),
    (CONTROL, "min own-header certification < 98 % (starved validators)", ("M16",), "cert_min_pct", "<", 98.0),
    (CONTROL, "landings >= 300 s > 0 (the cliff)", ("M16",), "landings_ge300", ">", 0),
    ("persist", "amplification <= 1.2", ("M16",), "amp_fleet_median", "<=", 1.2),
    ("persist", "resident pages after eviction = 0", None, "evict_resident_after_max", "==", 0),
    ("persist", "rr bytes / VMA bytes >= 0.99 on every node", ("M16",), "rr_vma_min", ">=", 0.99),
    ("vote", "own-header certification >= 98 % on every validator", ("L", "M16"), "cert_min_pct", ">=", 98.0),
    ("vote", "behind refusals per header <= f", ("L", "M16"), "behind_per_header_max_minus_f", "<=", 0),
    ("vote", "lock_ms p95 < 1100", ("L", "M16"), "vote_lock_p95_ms", "<", 1100.0),
    ("vote", "total_ms p95 < 1100", ("L", "M16"), "vote_total_p95_ms", "<", 1100.0),
    ("vote", "no generator silent > 30 s", ("L", "M16"), "gen_silent_max_s", "<=", 30),
    ("pool", "landings >= 300 s = 0", ("M16",), "landings_ge300", "==", 0),
    ("pool", "task-tracker errors = 0", ("M16",), "tracker_errors", "==", 0),
    ("bound", "chain tx/s >= the previous arm's (same type)", ("M16",), "chain_txps_vs_prev", ">=", 0.0),
    ("grace", "own certificates committed >= 90 %% on %s" % " and ".join(GRACE_NODES), (IDLE_TYPE, "L"),
     "grace_nodes_committed_min_pct", ">=", 90.0),
    (DRIFT, "commit us/tx moved <= 15 % against the first control", ("M16",), "drift_moved_pct_abs", "<=", 15.0),
)
# {metric: the metric whose check it replaces}: a row that holds the first is judged on it instead of the second, and a
# row without it never gets its check. The vote gate reads the whole vote path (total_ms) on a run whose 'vote path
# timing' lines carry prelock_wait_ms (bench 7): with vote_queue_fix on, the wait for execution moves out of lock_ms
# into prelock_wait_ms, so lock_ms p95 falls by construction and would not compare an arm with the switch on to one
# without it. A bench-6 run keeps the lock_ms check.
CHECK_REPLACES = {"vote_total_p95_ms": "vote_lock_p95_ms"}
LANDING_CLIFF_MS = 300000
DRIFT_LIMIT = 0.15
PREFAULT_ON_MIN = 0.9      # prefault on: sum(page_prefault) / growth of mdbx_last_pgno at least this (contract: "~")
PAGE = 4096
RECUT = (("M4", "2026-11-07T16:57:31Z", "2026-11-07T17:02:55Z", 3868.5),
         ("M16", "2026-11-07T17:41:01Z", "2026-11-07T17:54:44Z", 3466.2))
SELF_CHECK_RUN = "r20261107-1504"
# Columns that only a bench-6 run can fill; the self-check expects each of them n/a on bench 5.
BENCH6_ONLY = ("amp_fleet_median", "rr_vma_min", "evict_resident_after_max", "resends_total", "late_secs_max",
               "gen_silent_max_s", "tail_landed_late", "switch_set", "prefault_ratio_min", "prefault_on_all",
               "refault_per_min_median", "sealed_marked_peak", "admission_refused", "gen_dropped", "grace_share_pct",
               "exec_policy_pct", "exec_lag_p50", "wr_ops_per_output_median", "wr_iops_median", "wr_mibps_median",
               "iops_pct_of_cap_median", "mibps_pct_of_cap_median", "binds_nodes", "disk_reading")
# Device writes against the disk's caps (H18): per node, (column, decimals), in table order. binds = the cap whose
# sustained share is the larger when it is at least DISK_BINDS_PCT, else "neither"; the row's reading says "no node
# above DISK_LOW_PCT" when every node is below it on both caps.
DISK_COLS = (("wr_ops_per_output", 1), ("wr_kib_per_op", 1), ("flush_ops_per_output", 2), ("wr_iops", 1),
             ("wr_mibps", 2), ("wr_iops_peak", 1), ("wr_mibps_peak", 2), ("wr_ms_per_op", 3), ("flush_ms_per_op", 3),
             ("iops_pct_of_cap", 1), ("mibps_pct_of_cap", 1), ("cap_floor_ms_per_output", 1))
DISK_BINDS_PCT = 80.0
DISK_LOW_PCT = 50.0
BINDS = ("iops", "throughput", "neither")
MIB = 1048576.0
# A local SSD has no provisioned caps: the text starts with n/a, so is_na holds and nothing divides by it.
NO_CAPS = "n/a (local SSD, no provisioned caps)"
DISK_CLASSES = (F["v_lssd"], F["v_boot"])     # the "by disk class" order
# by_disk_class: the validators' median per (disk class, machine type) group, (column, decimals) in table order
GROUP_COLS = (tuple((k, 1) for k in ("exec_txps", "execute_us_tx", "persist_us_tx", "commit_us_tx", "commit_ms_output",
                                     "task_us_tx", "txs_per_output")) + (("amp", 3),) +
              tuple((k, 1) for k in ("refault_per_min", "majfault_per_min", "memcg_refault_per_min")) + DISK_COLS)

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
TS_RE = re.compile(r"^(?:ts=)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?")
MSG_RE = re.compile(r'message="([^"]*)"')
KV_RE = re.compile(r'(?:^|\s)([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\S+)')
NODE_FILE_RE = re.compile(r"^(bench-(?:validator|observer)-\d+)-")
BLAST_DIR_RE = re.compile(r"^blast-(\d+)-")


def na(what):
    return "n/a (missing: %s)" % what


def is_na(v):
    return isinstance(v, str) and v.startswith("n/a")


def iso(t):
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    m = TS_RE.match(str(text).strip())
    if not m:
        raise ValueError("not an ISO-8601 UTC time: %r" % text)
    y, mo, d, h, mi, s, frac = m.groups()
    base = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=datetime.timezone.utc)
    return base.timestamp() + (float(frac) if frac else 0.0)


def line_ts(line):
    m = TS_RE.match(line)
    if not m:
        return None
    y, mo, d, h, mi, s, frac = m.groups()
    base = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=datetime.timezone.utc)
    return base.timestamp() + (float(frac) if frac else 0.0)


def num(v):
    if v is None:
        return None
    try:
        return float(v) if ("." in v or "e" in v) else int(v)
    except (TypeError, ValueError):
        return None


def r1(x):
    return None if x is None else round(x, 1)


def median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def pctl(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(-(-q * len(xs) // 1)) - 1))     # nearest rank
    return xs[k]


def load_tool(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def open_bin(path):
    with open(path, "rb") as fh:
        magic = fh.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


# ---------------------------------------------------------------- inputs: manifest, blasts, arms

def read_json(path):
    with open(path) as fh:
        return json.load(fh)


def run_switch_list(manifest, line_keys=()):
    """(file name, evidence) of the switch list a run is read with, the list of its build (report/provenance.py
    run_switch_rows): of arms/switches.tsv (the live build) and each retired build's arms/switches-<build>.tsv, the one
    that shares the most keys with the run's param_arms[].switches states, else with <line_keys> (the keys on the run's
    'node switches' lines); a tie or no key at all gives switches.tsv. evidence: "manifest", "lines", None (no key in
    either), or "error: <why>" when the lists could not be read (then switches.tsv)."""
    sys.path.insert(0, os.path.join(BENCH, "report"))
    try:
        import provenance
        starts = [{F["pv_start_switches"]: dict.fromkeys(line_keys)}] if line_keys else []
        name = provenance.run_switch_rows(manifest, starts)[0]
        evidence = "manifest" if provenance.recorded_switch_keys(manifest, None) else "lines" if line_keys else None
        return name, evidence
    except (ImportError, OSError, ValueError) as exc:
        return "switches.tsv", "error: %s" % exc
    finally:
        sys.path.pop(0)


def switch_list_note(name, evidence):
    """The note of a run whose switch list param_arms[] did not decide (run_switch_list)."""
    if evidence == "lines":
        return ("switch list: arms/%s, the list whose keys the run's '%s' lines match best (param_arms[] records "
                "no switch state)" % (name, F["msg_switches"]))
    if evidence is None:
        return ("switch list: arms/%s, the live build's, for want of evidence: no switch key in param_arms[] nor on a "
                "'%s' line" % (name, F["msg_switches"]))
    return "switch list: arms/%s, the run's own list could not be chosen (%s)" % (name, evidence)


def switch_table(path):
    """[(key, default, topic)] from switches.tsv, or [] when it is unreadable."""
    try:
        with open(path) as fh:
            return [(r[F["s_key"]], r[F["s_default"]], r[F["s_topic"]]) for r in csv.DictReader(fh, delimiter="\t")]
    except (OSError, KeyError):
        return []


def arm_list(manifest, switches):
    """[{name, from, to, switches, host, marks, role, control}] in manifest order; one implicit arm without param_arms."""
    arms = []
    defaults = dict((k, d) for k, d, _ in switches)
    topic = dict((k, t) for k, _, t in switches)
    prev = dict(defaults)
    for a in manifest.get(F["m_arms"]) or []:
        if not isinstance(a, dict):
            continue
        start = a.get(F["m_ready"]) or a.get(F["m_begin"]) or a.get(F["m_start"])
        if not start:
            continue
        sw = a.get(F["m_switches"])
        host = [h for h in (a.get(F["m_host"]) or []) if isinstance(h, dict)]
        roles = set()
        # An arm that repeats the switch state of the arm before it (a resumed arm under its second name,
        # run-arms --from-arm: <name>-r2) turns nothing on against it: it is the same arm, with its roles.
        if isinstance(sw, dict) and arms and arms[-1]["switch_set"] is not None \
                and dict((k, str(v)) for k, v in sw.items()) == prev:
            roles, control = set(arms[-1]["roles"]) - {CONTROL}, arms[-1]["control"]
        elif isinstance(sw, dict):
            for k, v in sorted(sw.items()):
                if str(v) != str(prev.get(k, defaults.get(k))) and str(v) != str(defaults.get(k)):
                    role = TOPIC_ROLES.get(topic.get(k))
                    if role:
                        roles.add(role)
            control = bool(defaults) and all(str(sw.get(k, d)) == str(d) for k, d in defaults.items())
            prev = dict((k, str(v)) for k, v in sw.items())
        else:
            control = False
        if host and not roles and not control:
            roles.add(HOST_ROLE)
        arms.append({"arm_name": str(a.get(F["m_name"]) or "?"), "from": parse_iso(start),
                     "arm_t0": parse_iso(a.get(F["m_begin"]) or start),
                     "to": parse_iso(a[F["m_end"]]) if a.get(F["m_end"]) else float("inf"),
                     "switch_set": sw if isinstance(sw, dict) else None, "defaults": defaults, "host_steps": host,
                     "mark_list": [m for m in (a.get(F["m_marks"]) or []) if isinstance(m, dict)],
                     "roles": sorted(roles) or ([CONTROL] if control else []), "control": control})
    if not arms:
        arms.append({"arm_name": IMPLICIT_ARM, "from": float("-inf"), "arm_t0": float("-inf"), "to": float("inf"), "switch_set": None,
                     "defaults": defaults, "host_steps": [], "mark_list": [], "roles": [CONTROL], "control": True})
    controls = [a for a in arms if a["control"]]
    if len(controls) > 1:
        controls[-1]["roles"] = sorted(set(controls[-1]["roles"]) | {DRIFT})
    return arms


def load_docs(directory):
    out = []
    if not os.path.isdir(directory):
        return out
    for f in sorted(os.listdir(directory)):
        if f.endswith(".json"):
            try:
                d = read_json(os.path.join(directory, f))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and str(d.get(F["b_schema"], "")).startswith("tn-blast/"):
                out.append(d)
    return out


def doc_mixed(doc):
    for p in (doc.get(F["b_run"]) or {}).get(F["m_phases"]) or []:
        if p.get(F["m_name"]) == F["v_mixed"] and p.get(F["b_start_unix"]) is not None and p.get(F["b_end_unix"]) is not None:
            return float(p[F["b_start_unix"]]), float(p[F["b_end_unix"]])
    return None


def hand_runs(manifest):
    """{index: rc} of the blasts run by hand (manifest blast_runs[] `run` entries, the last one per index)."""
    out = {}
    for r in manifest.get(F["m_blast_runs"]) or []:
        if isinstance(r, dict) and r.get(F["m_action"]) == F["v_run_action"] and isinstance(r.get(F["m_index"]), int):
            out[r[F["m_index"]]] = r.get(F["m_rc"])
    return out


def own_entry(g, runs):
    """The entry of a blast that blasts[] does not list (a blast run by hand, as every blast of bench 6
    run 1 is), from its own records: senders and window from its generators' run.args (senders else from
    the blasters[] of its manifest copy), chaos from that copy's .blast, its real phases (with
    phases_planned) when the copy holds them, and rc from the live blast_runs[] `run` of its index, else
    from the copy: the first blaster rc that is not 0, 1 for a recorded abort, else not recorded (None).
    Sets g["blast_t0"], the blast's start (.blast.start_at), when the copy records it."""
    bm = g["bm"] or {}
    blast = bm.get(F["m_blast"]) or {}
    own = blast.get(F["m_run_index"]) == g["idx"]
    args = ((g["docs"][0].get(F["b_run"]) or {}).get(F["b_args"]) or {}) if g["docs"] else {}
    blasters = [b for b in bm.get(F["m_blasters"]) or [] if isinstance(b, dict)] if own else []
    senders = args.get(F["b_senders"])
    if senders is None and blasters:
        senders = blasters[0].get(F["m_senders"])
    entry = {F["m_senders"]: senders, F["m_window"]: args.get(F["b_window"]),
             F["m_chaos"]: blast.get(F["m_chaos"]) if own else None}
    if own and bm.get(F["m_planned"]):
        entry[F["m_phases"]], entry[F["m_planned"]] = bm.get(F["m_phases"]), bm[F["m_planned"]]
    if own and blast.get(F["m_start_at"]):
        g["blast_t0"] = parse_iso(blast[F["m_start_at"]])
    if g["idx"] in runs:
        entry[F["m_rc"]] = runs[g["idx"]]
    else:
        bad = [b.get(F["m_rc"]) for b in blasters if b.get(F["m_rc"]) not in (None, 0)]
        entry[F["m_rc"]] = bad[0] if bad else (1 if own and bm.get(F["m_abort"]) else None)
    return entry


def blast_groups(run_dir, manifest):
    """[{idx, dir, docs, entry, bm}] for blasters/ and every blast-<i>-<UTC>/blasters (bm: the manifest of
    the group, the live one for blasters/, else the copy archived beside it). entry is the blast's blasts[]
    entry, else own_entry()."""
    entries = dict((int(b[F["m_index"]]), b) for b in manifest.get(F["m_blasts"]) or []
                   if isinstance(b, dict) and b.get(F["m_index"]) is not None)
    runs = hand_runs(manifest)
    top = manifest.get(F["m_blast"]) or {}
    groups = []
    for f in sorted(os.listdir(run_dir)):
        m = BLAST_DIR_RE.match(f)
        d = os.path.join(run_dir, f, F["m_blasters"])
        if m and os.path.isdir(d):
            mp = os.path.join(run_dir, f, "manifest.json")
            groups.append({"idx": int(m.group(1)), "dir": d, "bm": read_json(mp) if os.path.isfile(mp) else {}})
    main_idx = top.get(F["m_run_index"])
    if main_idx is None:
        rest = [i for i in entries if i not in {g["idx"] for g in groups}]
        main_idx = rest[0] if len(rest) == 1 else None
    groups.append({"idx": main_idx, "dir": os.path.join(run_dir, F["m_blasters"]), "bm": manifest})
    out = []
    for g in groups:
        g["docs"] = load_docs(g["dir"])
        entry = dict(entries.get(g["idx"]) or {})
        if not entry and g["docs"]:
            entry = own_entry(g, runs)
        g["entry"] = entry
        if g["docs"] or entry:
            out.append(g)
    return out


def blast_type(entry, docs, mixed_secs):
    s, w = entry.get(F["m_senders"]), entry.get(F["m_window"]) or 16
    planned = None
    for d in docs:
        planned = ((d.get(F["b_run"]) or {}).get(F["b_args"]) or {}).get(F["b_duration"])
        if planned is not None:
            break
    length = planned if planned is not None else mixed_secs
    for name, ts, tw, min_mixed in TYPES:
        if str(s) == str(ts) and str(w) == str(tw) and (min_mixed is None or (length or 0) >= min_mixed):
            return name
    return "%sx%s" % (s, w)


def entry_real_mixed(entry):
    if not entry.get(F["m_planned"]):
        return None
    for p in entry.get(F["m_phases"]) or []:
        if isinstance(p, dict) and p.get(F["m_name"]) == F["v_mixed"] and p.get(F["m_start"]) and p.get(F["m_end"]):
            return parse_iso(p[F["m_start"]]), parse_iso(p[F["m_end"]])
    return None


def chaos_times(manifest):
    out = []
    events = manifest.get(F["m_chaos"])
    for c in events if isinstance(events, list) else []:
        if isinstance(c, dict) and c.get(F["m_ts"]):
            out.append((parse_iso(c[F["m_ts"]]), "%s %s" % (c.get(F["m_action"]) or "?", c.get(F["m_node"]) or "")))
    return sorted(out)


def build_rows(run_dir, manifest, arms, types):
    rows, skipped = [], []
    chaos = chaos_times(manifest)

    def arm_at(t, name=None):
        """The arm <name>, else the arm in force at <t>: the latest whose begin is at or before it."""
        if name is not None:
            for a in arms:
                if a["arm_name"] == name:
                    return a
        cands = [a for a in arms if a["arm_t0"] <= t]
        return cands[-1] if cands else arms[0]

    groups = blast_groups(run_dir, manifest)
    listed = set(g["idx"] for g in groups)
    for idx, rc in sorted(hand_runs(manifest).items()):
        if idx not in listed:      # a blast run by hand that left no blasters/ directory
            skipped.append("blast index %s: %s" % (idx, "rc %s, not measured" % rc if rc not in (None, 0)
                                                    else na("its %s/ directory" % F["m_blasters"])))
    for g in groups:
        e, docs = g["entry"], g["docs"]
        label = "blast index %s" % g["idx"]
        rc = e.get(F["m_rc"])
        if rc not in (None, 0):
            skipped.append("%s: rc %s, not measured" % (label, rc))
            continue
        spans = [s for s in (doc_mixed(d) for d in docs) if s]
        if spans:
            a, b, basis = max(s[0] for s in spans), min(s[1] for s in spans), "every generator in mixed (%d)" % len(spans)
        elif entry_real_mixed(e):
            (a, b), basis = entry_real_mixed(e), "blasts[].phases mixed (real)"
        else:
            skipped.append("%s: %s" % (label, na("generator files and a real mixed phase")))
            continue
        arm = arm_at(g.get("blast_t0", a), e.get(F["m_arm"]))
        a, b = max(a, arm["from"]), min(b, arm["to"])
        # an archived blast's chaos actions are in its manifest copy: the live chaos[] is reset by the archive
        events = chaos if g["bm"] is manifest else sorted(set(chaos) | set(chaos_times(g["bm"] or {})))
        cut = next(((t, what) for t, what in events if a < t < b), None)
        if cut:
            b = cut[0]
            basis += ", cut at chaos %s" % cut[1]
        if b <= a:
            skipped.append("%s: empty window after clipping to arm %s" % (label, arm["arm_name"]))
            continue
        typ = blast_type(e, docs, b - a)
        rows.append({"arm_rec": arm, "blast_type": typ, "blast_idx": g["idx"], "from": a, "to": b, "basis": basis,
                     "docs": docs, "group": g})
    for arm in arms:
        for mk in arm["mark_list"]:
            if mk.get(F["m_begin"]) and mk.get(F["m_end"]):
                rows.append({"arm_rec": arm, "blast_type": IDLE_TYPE, "blast_idx": None, "from": parse_iso(mk[F["m_begin"]]),
                             "to": parse_iso(mk[F["m_end"]]), "basis": "mark %s" % mk.get(F["m_label"]), "docs": [],
                             "group": None})
    if types:
        kept = [r for r in rows if r["blast_type"] in types]
        skipped += ["%s/%s: not in --types" % (r["arm_rec"]["arm_name"], r["blast_type"]) for r in rows if r not in kept]
        rows = kept
    rows.sort(key=lambda r: r["from"])
    seen = collections.Counter()
    for r in rows:
        rid = "%s/%s" % (r["arm_rec"]["arm_name"], r["blast_type"])
        seen[rid] += 1
        r["row_id"] = rid if seen[rid] == 1 else "%s-%d" % (rid, seen[rid])
    return rows, skipped


# ---------------------------------------------------------------- inputs: logs

def node_names(manifest, logs_dir):
    names = []
    for i in manifest.get(F["m_instances"]) or []:
        if isinstance(i, dict) and i.get(F["m_role"]) in (F["v_validator"], F["v_observer"]) and i.get(F["m_name"]):
            names.append(i[F["m_name"]])
    if not names and os.path.isdir(logs_dir):
        names = sorted({m.group(1) for m in (NODE_FILE_RE.match(f) for f in os.listdir(logs_dir)) if m})
    return names


def literals(sl, cr):
    """Every substring a line must hold for this tool, stage-latency.py or cert-rate.py to read it."""
    lits = [F["msg_persisted"], F["msg_executed"], F["msg_task"], F["msg_vote"], F["lit_tracker"], F["msg_proposed"],
            F["msg_grace_ended"], F["msg_builder"], F["msg_advice_refused"], F["msg_recovered"], F["msg_pool_failed"]]
    lits.append(F["msg_open_db"])
    lits.append(F["msg_switches"])          # its keys tell the run's build (run_switch_list)
    lits += list(sl.MSGS)
    for part in cr.EVENT_RE.pattern.split("|"):
        if re.search(r"[\\.^$*+?{}\[\]()]", part):
            raise ValueError("cert-rate.py EVENT_RE is no longer a list of literals: %r" % part)
        lits.append(part)
    return sorted(set(lits))


def prefilter_usable(prefiltered, lits):
    """None when <prefiltered> holds every literal per tools/log-shapes.txt, else what is missing."""
    if not prefiltered or not os.path.isdir(prefiltered):
        return "prefiltered directory %s" % (prefiltered or "-")
    try:
        with open(os.path.join(HERE, LOG_SHAPES)) as fh:
            shapes = [l.rstrip("\n") for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return "tools/%s" % LOG_SHAPES
    lacking = [x for x in lits if not any(s in x for s in shapes)]
    return ("%s lacks %s" % (LOG_SHAPES, ", ".join(lacking))) if lacking else None


def filter_one(src, dst, lits):
    """Stream <src> (gzip or plain) through a fixed-string grep into <dst> (gzip); reuse a finished <dst>."""
    side = os.path.join(os.path.dirname(dst), ".filtered-from", os.path.basename(dst))   # out of every log glob
    st = os.stat(src)
    want = "%s %d %d\n" % (os.path.realpath(src), st.st_size, st.st_mtime_ns) + "\n".join(lits) + "\n"
    if os.path.isfile(dst) and os.path.isfile(side):
        with open(side) as fh:
            if fh.read() == want:
                return dst
    tmp = dst + ".part"
    pat = tmp + ".lits"
    with open(pat, "w") as fh:
        fh.write("\n".join(lits) + "\n")
    try:
        with open(tmp, "wb") as out:
            unz = subprocess.Popen(["gzip", "-dcf", src], stdout=subprocess.PIPE)
            grep = subprocess.Popen(["grep", "-F", "-f", pat], stdin=unz.stdout, stdout=subprocess.PIPE)
            unz.stdout.close()
            zp = subprocess.Popen(["gzip", "-1"], stdin=grep.stdout, stdout=out)
            grep.stdout.close()
            rcs = (zp.wait(), grep.wait(), unz.wait())
        if rcs[0] != 0 or rcs[1] not in (0, 1) or rcs[2] != 0:
            raise OSError("filter of %s ended rc %s" % (src, rcs))
    except FileNotFoundError:                                   # no gzip/grep binaries: python, still streamed
        enc = [x.encode() for x in lits]
        with open_bin(src) as fin, gzip.open(tmp, "wb", compresslevel=1) as fout:
            for raw in fin:
                if any(x in raw for x in enc):
                    fout.write(raw)
    finally:
        if os.path.exists(pat):
            os.remove(pat)
    os.replace(tmp, dst)
    os.makedirs(os.path.dirname(side), exist_ok=True)
    with open(side, "w") as fh:
        fh.write(want)
    return dst


class NodeData(object):
    """One node's engine, vote and tracker events inside any row window."""

    def __init__(self, name, windows):
        self.name = name
        merged = []
        for a, b in sorted(windows):            # the union of the row windows, as disjoint spans
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.spans = merged
        self.starts = [w[0] for w in merged]
        self.executed, self.persisted, self.votes, self.tracker = [], [], [], []
        # bench 6: (t, grace_ms, exec_policy, exec_tip, exec_block) per own header; (t, outcome, waited_ms) per ended
        # parent grace; (t, keeps_sealed) per batch builder start, kept at any time (a builder starts before `ready`)
        self.proposed, self.grace_ended, self.builders = [], [], []
        self.advice_refused = []        # times of the 'advice not applied' warning, kept at any time (it is at open)
        # (t, pool) per recovered output; times of the recovery pool's build failure, kept at any time (once a process)
        self.recovered, self.pool_failed = [], []
        self.task = {}
        self.page_fields = False
        self.backend = None             # the engine the node's last 'opening database' line named (bench 7)
        self.switch_keys = set()        # the keys on its 'node switches' lines, kept at any time (one a start)
        self.files = []
        self._seen = set()

    def inside(self, t):
        i = bisect.bisect_right(self.starts, t) - 1
        return i >= 0 and t < self.spans[i][1]

    def read(self, path, dedupe):
        want = (F["msg_persisted"], F["msg_executed"], F["msg_task"], F["msg_vote"], F["msg_proposed"],
                F["msg_grace_ended"], F["msg_builder"], F["msg_advice_refused"], F["msg_recovered"],
                F["msg_pool_failed"], F["msg_open_db"], F["msg_switches"])
        anytime = (F["msg_builder"], F["msg_advice_refused"], F["msg_pool_failed"])
        anytime += (F["msg_open_db"], F["msg_switches"])          # bench 7: once per node start, before any window
        with open_bin(path) as fh:
            for raw in fh:
                line = raw.decode("utf-8", "replace")
                tracker = F["lit_tracker"] in line
                m = MSG_RE.search(line)
                msg = m.group(1) if m else None
                if msg not in want and not tracker:
                    continue
                t = line_ts(line)
                if t is None or not (msg in anytime or self.inside(t)):
                    continue
                if dedupe:
                    h = hash(line)
                    if h in self._seen:
                        continue
                    self._seen.add(h)
                if tracker:
                    self.tracker.append(t)
                    continue
                f = {}
                for k, v in KV_RE.findall(line[m.end():]):
                    f.setdefault(k, v)
                if msg == F["msg_executed"]:
                    self.executed.append((t, num(f.get(F["f_txs"])), num(f.get(F["f_execute_ms"])),
                                          num(f.get(F["f_persist_ms"])), num(f.get(F["f_cn"]))))
                elif msg == F["msg_persisted"]:
                    pages = dict((k, num(f.get(F[k]))) for k in ("f_newly", "f_cow", "f_spill", "f_unspill",
                                                                 "f_prefault", "f_wops", "f_msync", "f_proc_write",
                                                                 "f_last_pgno", "f_advised", "f_save_ms"))
                    if pages["f_newly"] is not None and pages["f_cow"] is not None:
                        self.page_fields = True
                    self.persisted.append((t, num(f.get(F["f_txs"])), num(f.get(F["f_commit_ms"])), pages))
                elif msg == F["msg_task"]:
                    self.task.setdefault(num(f.get(F["f_cn"])), num(f.get(F["f_task_ms"])))
                elif msg == F["msg_vote"]:
                    # then total_ms and bench 7's prelock_wait_ms (None on a line without the field)
                    self.votes.append((t, f.get(F["f_author"]), num(f.get(F["f_epoch"])), num(f.get(F["f_round"])),
                                       f.get(F["f_outcome"]), num(f.get(F["f_lock_ms"])), num(f.get(F["f_total_ms"])),
                                       num(f.get(F["f_prelock_ms"]))))
                elif msg == F["msg_proposed"]:
                    self.proposed.append((t, num(f.get(F["f_grace_ms"])), f.get(F["f_exec_policy"]),
                                          num(f.get(F["f_exec_tip"])), num(f.get(F["f_exec_block"]))))
                elif msg == F["msg_grace_ended"]:
                    self.grace_ended.append((t, f.get(F["f_outcome"]), num(f.get(F["f_waited_ms"]))))
                elif msg == F["msg_builder"]:
                    self.builders.append((t, f.get(F["f_keeps_sealed"])))
                elif msg == F["msg_advice_refused"]:
                    self.advice_refused.append(t)
                elif msg == F["msg_recovered"]:
                    self.recovered.append((t, f.get(F["f_pool"])))
                elif msg == F["msg_pool_failed"]:
                    self.pool_failed.append(t)
                elif msg == F["msg_open_db"]:
                    self.backend = (f.get(F["f_backend"]) or "").strip('"') or self.backend
                elif msg == F["msg_switches"]:
                    self.switch_keys.update(f)
        self.files.append(os.path.basename(path))

    def finish(self):
        for xs in (self.executed, self.persisted, self.votes, self.tracker, self.proposed, self.grace_ended,
                   self.builders, self.advice_refused, self.recovered, self.pool_failed):
            xs.sort(key=lambda x: x[0] if isinstance(x, tuple) else x)
        self._seen = set()


def between(xs, a, b, key=lambda x: x[0]):
    return [x for x in xs if a <= key(x) < b]


# ---------------------------------------------------------------- inputs: persist CSV, blasters

def persist_rows(path):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            row = {}
            for k in ("c_ts", "c_disk_wr", "c_vma", "c_rr", "c_size", "c_refault", "c_majfault", "c_memcg_refault",
                      "c_wr_ios", "c_wr_ticks", "c_flush_ios", "c_flush_ticks", "c_lmdb_size", "c_lmdb_used",
                      "c_static_size", "c_lmdb_vma", "c_lmdb_rr"):
                v = (r.get(F[k]) or "").strip()
                row[k] = float(v) if v else None
            if row["c_ts"] is not None:
                rows.append(row)
    rows.sort(key=lambda r: r["c_ts"])
    return rows


def block_table(docs_lists):
    """Sorted [(timestamp, tx_count)] over every generator's blocks, de-duplicated by number."""
    by_num = {}
    for docs in docs_lists:
        for d in docs:
            b = d.get(F["b_blocks"]) or {}
            cols = list(b.get(F["b_columns"]) or [])
            if not all(c in cols for c in (F["b_number"], F["b_timestamp"], F["b_tx_count"])):
                continue
            i_n, i_t, i_x = cols.index(F["b_number"]), cols.index(F["b_timestamp"]), cols.index(F["b_tx_count"])
            for r in b.get(F["b_rows"]) or []:
                by_num.setdefault(r[i_n], (float(r[i_t]), int(r[i_x] or 0)))
    return sorted(by_num.values())


def series(doc, cols_key, rows_key, t0_key):
    s = doc.get(F["b_series"]) or {}
    cols, rows = s.get(F[cols_key]), s.get(F[rows_key])
    if not cols or rows is None or s.get(F[t0_key]) is None:
        return None
    return list(cols), rows, float(s[F[t0_key]])


def landings(group, docs):
    """(count >= 300 s, sampled mixed landings, sample rate) over the blast's landings files, or None."""
    total, cliff, rate = 0, 0, None
    found = False
    for d in docs:
        args = (d.get(F["b_run"]) or {}).get(F["b_args"]) or {}
        rate = args.get(F["b_sample"], rate)
        p = os.path.join(group["dir"], "landings-%s.ndjson.gz" % ((d.get(F["b_run"]) or {}).get(F["b_label"]) or "?"))
        if not os.path.isfile(p):
            continue
        found = True
        with open_bin(p) as fh:
            for raw in fh:
                try:
                    x = json.loads(raw)
                except ValueError:
                    continue
                if x.get(F["l_phase"]) != F["v_mixed"] or x.get(F["l_seen"]) is None or x.get(F["l_submit"]) is None:
                    continue
                total += 1
                if x[F["l_seen"]] - x[F["l_submit"]] >= LANDING_CLIFF_MS:
                    cliff += 1
    return (cliff, total, rate) if found else None


# ---------------------------------------------------------------- measurements

def lsq(X, y):
    """Least squares by the normal equations: (coefficients, r2), or None when singular or too few points."""
    n = len(X[0]) if X else 0
    if len(X) <= n:
        return None
    A = [[sum(r[i] * r[j] for r in X) for j in range(n)] + [sum(r[i] * v for r, v in zip(X, y))] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(A[k][i]))
        A[i], A[p] = A[p], A[i]
        if abs(A[i][i]) < 1e-9 * max(1.0, max(abs(u) for u in A[i][:n])):
            return None
        for k in range(n):
            if k != i:
                f = A[k][i] / A[i][i]
                A[k] = [u - f * v for u, v in zip(A[k], A[i])]
    co = [A[i][n] / A[i][i] for i in range(n)]
    ybar = sum(y) / len(y)
    ss = sum((v - ybar) ** 2 for v in y)
    res = sum((v - sum(c * x for c, x in zip(co, r))) ** 2 for v, r in zip(y, X))
    return co, ((1 - res / ss) if ss else None)


def lsq3(pts):
    """commit = a + b x1 + c x2 over [(commit, x1, x2)]: (a, b, c, r2); b is None when x1 never varies
    (then c comes from commit = a + c x2); None when even that is singular."""
    y = [p[0] for p in pts]
    full = lsq([[1.0, x1, x2] for _, x1, x2 in pts], y)
    if full:
        return full[0][0], full[0][1], full[0][2], full[1]
    two = lsq([[1.0, x2] for _, _, x2 in pts], y)
    return (two[0][0], None, two[0][1], two[1]) if two else None


def engine_row(nd, a, b):
    ex = [e for e in between(nd.executed, a, b) if e[1] is not None]
    ps = [p for p in between(nd.persisted, a, b) if p[1] is not None]
    out = {}
    txs = sum(e[1] for e in ex)
    ptx = sum(p[1] for p in ps)
    if not txs:
        for k in ("exec_txps", "execute_us_tx", "persist_us_tx", "task_us_tx"):
            out[k] = na("'%s' lines in the window" % F["msg_executed"])
    else:
        out["exec_txps"] = r1(txs / (b - a))
        out["execute_us_tx"] = r1(sum(e[2] or 0 for e in ex) * 1000.0 / txs)
        out["persist_us_tx"] = r1(sum(e[3] or 0 for e in ex) * 1000.0 / txs)
        tasks = [nd.task.get(e[4]) for e in ex]
        out["task_us_tx"] = (r1(sum(tasks) * 1000.0 / txs) if all(x is not None for x in tasks)
                             else na("'%s' for every output" % F["msg_task"]))
    if not ptx:
        for k in ("commit_us_tx", "commit_ms_output", "txs_per_output"):
            out[k] = na("'%s' lines in the window" % F["msg_persisted"])
    else:
        out["commit_us_tx"] = r1(sum(p[2] or 0 for p in ps) * 1000.0 / ptx)
        out["commit_ms_output"] = r1(sum(p[2] or 0 for p in ps) / float(len(ps)))
        out["txs_per_output"] = round(ptx / float(len(ps)))
    return out


def summed(ps, k):
    """The sum of a 'persisted output' field over the lines, or n/a when a line left it off (never 0 for it)."""
    vals = [p[3][k] for p in ps]
    return int(sum(vals)) if None not in vals else na("%s on %d of %d '%s' lines between the samples" % (
        F[k], len(vals) - vals.count(None), len(vals), F["msg_persisted"]))


def amp_row(nd, csv_rows, a, b, lmdb=False):
    """(amplification dict, rr dict) of one node in [a, b); lmdb: a tn-lmdb node (no page counts, its own map)."""
    if csv_rows is None:
        miss = na("persist/%s.csv" % nd.name)
        return {"amp": miss, "refault_per_min": miss, "majfault_per_min": miss, "memcg_refault_per_min": miss}, \
            {"rr_vma": miss}
    inside = [r for r in csv_rows if a <= r["c_ts"] <= b and r["c_disk_wr"] is not None]
    amp = {}
    if len(inside) < 2:
        amp["amp"] = na("two persist samples with %s in the window" % F["c_disk_wr"])
    elif not nd.page_fields:
        amp["amp"] = na("%s / %s on '%s'%s" % (F["f_newly"], F["f_cow"], F["msg_persisted"], (
            ": MDBX page counts, which a %s node does not log" % F["v_tn_lmdb"]) if lmdb else ""))
    else:
        t1, t2 = inside[0]["c_ts"], inside[-1]["c_ts"]
        dev = inside[-1]["c_disk_wr"] - inside[0]["c_disk_wr"]
        ps = [p for p in nd.persisted if t1 < p[0] <= t2]
        pages = sum((p[3]["f_newly"] or 0) + (p[3]["f_cow"] or 0) for p in ps)
        left_off = [p for p in ps if p[3]["f_newly"] is None or p[3]["f_cow"] is None]
        if left_off:      # a field left off a line is unknown, never 0 (bench6-contract: unreadable source -> no field)
            amp["amp"] = na("%s / %s on %d of %d '%s' lines between the samples" % (
                F["f_newly"], F["f_cow"], len(left_off), len(ps), F["msg_persisted"]))
        elif dev < 0:
            amp["amp"] = na("a monotonic %s (it went back)" % F["c_disk_wr"])
        elif not pages:
            amp["amp"] = na("page operations in '%s' between the samples" % F["msg_persisted"])
        else:
            amp["amp"] = round(dev / (pages * float(PAGE)), 3)
            amp["device_bytes"] = int(dev)
            amp["page_bytes"] = int(pages * PAGE)
            amp["proc_written_bytes"] = summed(ps, "f_proc_write")
            amp["samples"] = [iso(t1), iso(t2)]
            for k in ("f_spill", "f_unspill", "f_prefault", "f_wops", "f_msync"):
                amp[F[k]] = summed(ps, k)
    # page-cache refaults beside the amplification (with the advice on, reclaim stops counting recent access on the
    # advised range): per node, the counter's increase per minute between the first and last sample in the window
    for k, key in (("c_refault", "refault_per_min"), ("c_majfault", "majfault_per_min"),
                   ("c_memcg_refault", "memcg_refault_per_min")):
        have = [r for r in csv_rows if a <= r["c_ts"] <= b and r[k] is not None]
        if len(have) < 2 or have[-1]["c_ts"] <= have[0]["c_ts"]:
            amp[key] = na("two persist samples with %s in the window" % F[k])
        else:
            amp[key] = r1((have[-1][k] - have[0][k]) * 60.0 / (have[-1]["c_ts"] - have[0]["c_ts"]))
    k_rr, k_vma, k_size = ("c_lmdb_rr", "c_lmdb_vma", "c_lmdb_size") if lmdb else ("c_rr", "c_vma", "c_size")
    rr = [r for r in csv_rows if a <= r["c_ts"] <= b and r[k_rr] is not None and r[k_vma]]
    if not rr:
        rrd = {"rr_vma": na("a 300-s persist sample with %s in the window" % F[k_rr])}
    else:
        last = rr[-1]
        rrd = {"rr_vma": round(last[k_rr] / last[k_vma], 4), "rr_bytes": int(last[k_rr]),
               "vma_bytes": int(last[k_vma]), "dat_bytes": None if last[k_size] is None else int(last[k_size])}
    return amp, rrd


def node_store(nd, csv_rows):
    """The node's store engine: what its 'opening database' line said, else what its persist CSV sampled (the
    tn-lmdb columns, else the mdbx.dat ones), else None."""
    if nd is not None and nd.backend:
        return nd.backend
    if csv_rows and any(r["c_lmdb_size"] is not None for r in csv_rows):
        return F["v_tn_lmdb"]
    if csv_rows and any(r["c_size"] is not None for r in csv_rows):
        return F["v_mdbx"]
    return None


STORE_COLS = (("wr_ops_per_tx", 4), ("wr_bytes_per_tx", 1), ("save_blocks_ms_output", 1), ("store_growth_bytes_per_tx", 1))


def store_row(nd, csv_rows, a, b):
    """One tn-lmdb node's store figures in [a, b] (STORE_COLS), each n/a with what is missing, never 0 for it."""
    v = collections.OrderedDict()
    saves = [p[3]["f_save_ms"] for p in between(nd.persisted, a, b)]
    if not saves:
        v["save_blocks_ms_output"] = na("'%s' lines in the window" % F["msg_persisted"])
    elif None in saves:
        v["save_blocks_ms_output"] = na("%s on %d of %d '%s' lines in the window" % (
            F["f_save_ms"], len(saves) - saves.count(None), len(saves), F["msg_persisted"]))
    else:
        v["save_blocks_ms_output"] = sum(saves) / float(len(saves))
    if csv_rows is None:
        miss = na("persist/%s.csv" % nd.name)
        v["wr_ops_per_tx"] = v["wr_bytes_per_tx"] = v["store_growth_bytes_per_tx"] = miss
        return collections.OrderedDict((k, v[k]) for k, _ in STORE_COLS)

    def txs(have):
        xs = [p[1] for p in nd.persisted if have[0]["c_ts"] < p[0] <= have[-1]["c_ts"]]
        if not xs:
            return None, na("'%s' lines between the samples" % F["msg_persisted"])
        if None in xs:
            return None, na("%s on every '%s' line between the samples" % (F["f_txs"], F["msg_persisted"]))
        return (sum(xs), None) if sum(xs) else (None, na("transactions on the '%s' lines between the samples" %
                                                         F["msg_persisted"]))
    have, why = disk_span(csv_rows, a, b, ("c_wr_ios", "c_disk_wr"))
    if have is None:
        v["wr_ops_per_tx"] = v["wr_bytes_per_tx"] = why
    else:
        n, why = txs(have)
        v["wr_ops_per_tx"] = why or (have[-1]["c_wr_ios"] - have[0]["c_wr_ios"]) / float(n)
        v["wr_bytes_per_tx"] = why or (have[-1]["c_disk_wr"] - have[0]["c_disk_wr"]) / float(n)
    have = [r for r in csv_rows if a <= r["c_ts"] <= b and r["c_lmdb_used"] is not None and r["c_static_size"] is not None]
    if len(have) < 2 or have[-1]["c_ts"] <= have[0]["c_ts"]:
        v["store_growth_bytes_per_tx"] = na("two persist samples with %s and %s in the window" % (
            F["c_lmdb_used"], F["c_static_size"]))
    else:
        n, why = txs(have)
        v["store_growth_bytes_per_tx"] = why or (have[-1]["c_lmdb_used"] + have[-1]["c_static_size"] -
                                                 have[0]["c_lmdb_used"] - have[0]["c_static_size"]) / float(n)
    return collections.OrderedDict((k, v[k] if is_na(v[k]) else round(v[k], d)) for k, d in STORE_COLS)


def disk_caps(manifest, iops=None, mibps=None):
    """The disk's provisioned caps (IOPS, MiB/s) and where each came from: an option wins over the manifest's
    node_disk (what the deploy asked for); a cap that neither gives is n/a, never a type default."""
    nd = manifest.get(F["m_node_disk"])
    nd = nd if isinstance(nd, dict) else {}
    out = collections.OrderedDict()
    for key, opt, field, flag, unit in (("iops", iops, "m_prov_iops", "--disk-iops", "IOPS"),
                                        ("mibps", mibps, "m_prov_tput", "--disk-mibps", "MiB/s")):
        v = nd.get(F[field])
        if opt is not None:
            out[key], out[key + "_from"] = opt, flag
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[key], out[key + "_from"] = v, "manifest %s.%s" % (F["m_node_disk"], F[field])
        else:
            out[key] = na("the provisioned %s (manifest %s.%s, or %s)" % (unit, F["m_node_disk"], F[field], flag))
            out[key + "_from"] = None
    return out


def node_groups(manifest, names):
    """{node: (disk class, machine type)} for <names> when an instance carries data_disk (the deploy with
    BENCH_NODE_DATADIR_LSSD=1), else {} (every run before it). A node whose data_disk.class is not local-ssd, or that
    has no data_disk, is on the boot disk; its machine type is instances[].machine_type, else the manifest's."""
    inst = dict((i[F["m_name"]], i) for i in manifest.get(F["m_instances"]) or []
                if isinstance(i, dict) and i.get(F["m_role"]) in (F["v_validator"], F["v_observer"]) and i.get(F["m_name"]))
    if not any(isinstance(i.get(F["m_data_disk"]), dict) for i in inst.values()):
        return {}
    top = manifest.get(F["m_machine_type"]) or na("%s (manifest %s[].%s or %s)" % (
        F["m_machine_type"], F["m_instances"], F["m_machine_type"], F["m_machine_type"]))
    out = collections.OrderedDict()
    for n in names:
        i = inst.get(n) or {}
        dd = i.get(F["m_data_disk"])
        local = isinstance(dd, dict) and dd.get(F["m_dd_class"]) == F["v_lssd"]
        out[n] = (F["v_lssd"] if local else F["v_boot"], str(i.get(F["m_machine_type"]) or top))
    return out


def lssd_caps():
    return collections.OrderedDict([("iops", NO_CAPS), ("mibps", NO_CAPS)])


def node_caps(caps, groups, n):
    """The caps node <n>'s shares are read against: none on a local SSD, else the boot disk's (options or node_disk)."""
    return lssd_caps() if n in groups and groups[n][0] == F["v_lssd"] else caps


def disk_span(rows, a, b, ks):
    """(samples, None): the persist samples in [a, b] that carry every counter in <ks>, sorted; or (None, n/a) with
    fewer than two of them, or when a counter went back between two of them (a reboot restarts /proc/diskstats)."""
    have = [r for r in rows if a <= r["c_ts"] <= b and all(r[k] is not None for k in ks)]
    if len(have) < 2 or have[-1]["c_ts"] <= have[0]["c_ts"]:
        return None, na("two persist samples with %s in the window" % " and ".join(F[k] for k in ks))
    for x, y in zip(have, have[1:]):
        back = [k for k in ks if y[k] < x[k]]
        if back:
            return None, na("a monotonic %s (it went back at %s)" % (F[back[0]], iso(y["c_ts"])))
    return have, None


def disk_row(nd, csv_rows, a, b, caps):
    """One node's device writes in [a, b] against the disk's caps, from the persist CSV's /proc/diskstats counters
    (the whole disk under the data dir, every writer on it), between the first and the last sample in the window
    that carry the counters a column needs. Each value is n/a with what is missing, never 0 for it."""
    v = {}
    if csv_rows is None:
        miss = na("persist/%s.csv" % nd.name)
        return collections.OrderedDict([(k, miss) for k, _ in DISK_COLS] + [("binds", miss)])
    no_out = na("'%s' lines between the samples" % F["msg_persisted"])

    def outputs(have):
        return len([p for p in nd.persisted if have[0]["c_ts"] < p[0] <= have[-1]["c_ts"]])
    have, why = disk_span(csv_rows, a, b, ("c_wr_ios", "c_disk_wr"))
    if have is None:
        for k in ("wr_ops_per_output", "wr_kib_per_op", "wr_iops", "wr_mibps", "wr_iops_peak", "wr_mibps_peak",
                  "iops_pct_of_cap", "mibps_pct_of_cap", "cap_floor_ms_per_output"):
            v[k] = why
    else:
        x, y, n = have[0], have[-1], outputs(have)
        secs, ops, byt = y["c_ts"] - x["c_ts"], y["c_wr_ios"] - x["c_wr_ios"], y["c_disk_wr"] - x["c_disk_wr"]
        v["wr_ops_per_output"] = ops / n if n else no_out
        v["wr_kib_per_op"] = byt / ops / 1024.0 if ops else na("write operations between the samples")
        v["wr_iops"], v["wr_mibps"] = ops / secs, byt / secs / MIB
        # the peak: the busiest step between two consecutive samples (the sampler's cadence, 30 s, bounds it)
        steps = [(q["c_ts"] - p["c_ts"], q["c_wr_ios"] - p["c_wr_ios"], q["c_disk_wr"] - p["c_disk_wr"])
                 for p, q in zip(have, have[1:]) if q["c_ts"] > p["c_ts"]]
        v["wr_iops_peak"] = max(o / s for s, o, _ in steps)
        v["wr_mibps_peak"] = max(w / s / MIB for s, _, w in steps)
        v["iops_pct_of_cap"] = caps["iops"] if is_na(caps["iops"]) else v["wr_iops"] * 100.0 / caps["iops"]
        v["mibps_pct_of_cap"] = caps["mibps"] if is_na(caps["mibps"]) else v["wr_mibps"] * 100.0 / caps["mibps"]
        # the least device time the caps allow one output's writes: back-to-back persists run no faster than this
        cap_na = next((caps[k] for k in ("iops", "mibps") if is_na(caps[k])), None)
        v["cap_floor_ms_per_output"] = cap_na or (no_out if not n else 1000.0 * max(
            ops / float(n) / caps["iops"], byt / float(n) / MIB / caps["mibps"]))
    have, why = disk_span(csv_rows, a, b, ("c_wr_ios", "c_wr_ticks"))
    if have is None:
        v["wr_ms_per_op"] = why
    else:
        ops = have[-1]["c_wr_ios"] - have[0]["c_wr_ios"]
        v["wr_ms_per_op"] = ((have[-1]["c_wr_ticks"] - have[0]["c_wr_ticks"]) / ops if ops
                             else na("write operations between the samples"))
    have, why = disk_span(csv_rows, a, b, ("c_flush_ios",))
    if have is None:
        v["flush_ops_per_output"] = why
    else:
        n = outputs(have)
        v["flush_ops_per_output"] = (have[-1]["c_flush_ios"] - have[0]["c_flush_ios"]) / float(n) if n else no_out
    have, why = disk_span(csv_rows, a, b, ("c_flush_ios", "c_flush_ticks"))
    if have is None:
        v["flush_ms_per_op"] = why
    else:
        fl = have[-1]["c_flush_ios"] - have[0]["c_flush_ios"]
        v["flush_ms_per_op"] = ((have[-1]["c_flush_ticks"] - have[0]["c_flush_ticks"]) / fl if fl
                                else na("flush operations between the samples"))
    ip, mp = v["iops_pct_of_cap"], v["mibps_pct_of_cap"]
    if is_na(ip) or is_na(mp):
        binds = ip if is_na(ip) else mp
    elif max(ip, mp) < DISK_BINDS_PCT:
        binds = BINDS[2]
    else:
        binds = BINDS[0] if ip >= mp else BINDS[1]
    return collections.OrderedDict([(k, v[k] if is_na(v[k]) else round(v[k], d)) for k, d in DISK_COLS] +
                                   [("binds", binds)])


def cap_text(c):
    return "{:,}".format(int(c)) if float(c) == int(c) else str(c)


def disk_reading(per_node, caps):
    """The row's one line on its nodes' sustained write rates against the disk's caps, with the thresholds named."""
    got = [(n, e) for n, e in per_node.items() if not is_na(e["wr_iops"])]
    if not got:
        return ("%s; no node measured (0 of %d)" % (next(iter(per_node.values()))["wr_iops"], len(per_node)) if per_node
                else na("node logs"))
    absent = [n for n in per_node if is_na(per_node[n]["wr_iops"])]
    tail = "; not measured on %s" % ", ".join(absent) if absent else ""
    meas = [(n, e) for n, e in got if e["binds"] in BINDS]
    if not meas:
        return "%s against the caps; sustained write IOPS %s, MiB/s %s (median of %d nodes)%s" % (
            got[0][1]["binds"], cell(r1(median([e["wr_iops"] for _, e in got]))),
            cell(round(median([e["wr_mibps"] for _, e in got]), 2)), len(got), tail)
    near = 100.0 - DISK_BINDS_PCT
    cnt = dict((x, len([1 for _, e in meas if e["binds"] == x])) for x in BINDS)
    med_i, med_m = r1(median([e["iops_pct_of_cap"] for _, e in meas])), r1(median([e["mibps_pct_of_cap"] for _, e in meas]))
    medians = "median %.1f %% of %s IOPS, %.1f %% of %s MiB/s" % (med_i, cap_text(caps["iops"]), med_m,
                                                                 cap_text(caps["mibps"]))
    top = BINDS[0] if cnt[BINDS[0]] >= cnt[BINDS[1]] else BINDS[1]
    if cnt[top] * 2 > len(meas):
        iops = top == BINDS[0]
        return ("write %s within %g %% of the provisioned %s %s on %d of %d nodes (sustained over the window; median "
                "%.1f %% of the cap): the disk's %s cap bounds this arm%s" % (
                    "IOPS" if iops else "MiB/s", near, cap_text(caps["iops"] if iops else caps["mibps"]),
                    "IOPS" if iops else "MiB/s", cnt[top], len(meas), med_i if iops else med_m,
                    "IOPS" if iops else "throughput", tail))
    share = dict((n, max(e["iops_pct_of_cap"], e["mibps_pct_of_cap"])) for n, e in meas)
    if max(share.values()) <= DISK_LOW_PCT:
        return "no node above %g %% of either cap (sustained over the window; %s)%s" % (DISK_LOW_PCT, medians, tail)
    hi = max(meas, key=lambda ne: share[ne[0]])
    k = cnt[BINDS[0]] + cnt[BINDS[1]]
    which = ", ".join("%s %d" % ("IOPS" if x == BINDS[0] else "throughput", cnt[x]) for x in BINDS[:2] if cnt[x])
    return ("%d of %d nodes within %g %% of a cap%s, the highest %.1f %% of the %s cap on %s (sustained over the window; "
            "%s): no cap bounds most nodes%s" % (
                k, len(meas), near, " (%s)" % which if which else "", share[hi[0]],
                "IOPS" if hi[1]["iops_pct_of_cap"] >= hi[1]["mibps_pct_of_cap"] else "throughput", hi[0], medians, tail))


def lssd_reading(per_node, types):
    """The local-SSD clause: no caps to read against, so the sustained rates, the write size and the flushes."""
    head = "local SSD%s, no provisioned caps" % types
    got = [e for e in per_node.values() if not is_na(e["wr_iops"])]
    if not got:
        return "%s: %s; no node measured (0 of %d)" % (head, next(iter(per_node.values()))["wr_iops"], len(per_node))
    absent = [n for n, e in per_node.items() if is_na(e["wr_iops"])]

    def med(k, d):
        vals = [e[k] for e in got if not is_na(e[k])]
        return cell(round(median(vals), d)) if vals else "n/a"
    return "%s: sustained write IOPS %s, MiB/s %s, %s KiB per write, %s flushes per output (median of %d nodes)%s" % (
        head, med("wr_iops", 1), med("wr_mibps", 2), med("wr_kib_per_op", 1), med("flush_ops_per_output", 2), len(got),
        "; not measured on %s" % ", ".join(absent) if absent else "")


def class_reading(per_node, caps, groups):
    """disk_reading with the nodes' disk classes: one clause per class (the boot disk's in disk_reading's wording),
    naming the machine types of a class that spans more than one; without data_disk, or with every node on one boot
    disk type, disk_reading itself."""
    by = collections.OrderedDict()
    for c in DISK_CLASSES:
        sub = collections.OrderedDict((n, e) for n, e in per_node.items() if n in groups and groups[n][0] == c)
        if sub:
            by[c] = sub
    types = dict((c, collections.OrderedDict()) for c in by)
    for c, sub in by.items():
        for n in sub:
            types[c][groups[n][1]] = types[c].get(groups[n][1], 0) + 1
    if not by or (list(by) == [F["v_boot"]] and len(types[F["v_boot"]]) == 1):
        return disk_reading(per_node, caps)
    out = []
    for c, sub in by.items():
        span = " (%s)" % ", ".join("%d on %s" % (k, t) for t, k in types[c].items()) if len(types[c]) > 1 else ""
        out.append(lssd_reading(sub, span) if c == F["v_lssd"] else "boot disk%s: %s" % (span, disk_reading(sub, caps)))
    return "; ".join(out)


def group_medians(per_node, validators, groups):
    """by_disk_class: the validators' median of GROUP_COLS per (disk class, machine type) group, classes in
    DISK_CLASSES order and machine types in validator order; [] unless the validators fall into two groups or more."""
    keys = []
    for c in DISK_CLASSES:
        for n in validators:
            if n in groups and groups[n][0] == c and groups[n] not in keys:
                keys.append(groups[n])
    if len(keys) < 2:
        return []
    out = []
    for c, t in keys:
        names = [n for n in validators if groups.get(n) == (c, t)]
        es = [per_node[n] for n in names if n in per_node]
        g = collections.OrderedDict([(F["o_disk_class"], c), (F["o_machine_type"], t), (F["o_nodes"], names)])
        for k, d in GROUP_COLS:
            vals = [e[k] for e in es if not is_na(e[k])]
            g[k] = round(median(vals), d) if vals else next((e[k] for e in es), na("validator logs"))
        out.append(g)
    return out


def group_label(g):
    return "%s / %s (%d)" % (g[F["o_disk_class"]], g[F["o_machine_type"]], len(g[F["o_nodes"]]))


def commit_fit(nds, validators, a, b):
    """I-3's fit: per validator and whole minute of the window (the minute ending a + 60 k), the mean commit
    s per output and the mean txs per output of its persists, against k."""
    pts = []
    for n in validators:
        ps = [p for p in (nds[n].persisted if n in nds else []) if a <= p[0] < b and p[1] is not None and p[2] is not None]
        k = 1
        while a + 60 * k <= b:
            sel = [p for p in ps if a + 60 * (k - 1) <= p[0] < a + 60 * k]
            if sel and sum(p[1] for p in sel):
                pts.append((sum(p[2] for p in sel) / 1000.0 / len(sel), sum(p[1] for p in sel) / 1000.0 / len(sel), float(k)))
            k += 1
    fit = lsq3(pts)
    if not fit:
        return na("validator outputs with '%s' spread over the window (the fit is singular)" % F["msg_persisted"])
    return {"a_s": round(fit[0], 4), "b_s_per_1k_txs": None if fit[1] is None else round(fit[1], 4),
            "c_s_per_min": round(fit[2], 4),
            "r2": None if fit[3] is None else round(fit[3], 3), "n": len(pts)}


# Bench 7: the row keys of a run whose 'vote path timing' lines carry prelock_wait_ms, and arms.md's words for them.
VOTE_PATH_KEYS = ("vote_total_p50_ms", "vote_total_p95_ms", "vote_prelock_p95_ms", "votes_superseded")
VOTE_LEGEND = ("Votes (the '%(msg_vote)s' lines carry %(f_prelock_ms)s): %(f_total_ms)s is a vote request's whole "
               "path on the voter, from its arrival to the answer; %(f_prelock_ms)s the part of it spent before the vote "
               "lock (with vote_queue_fix on, the wait for execution, which moves there out of %(f_lock_ms)s; a line "
               "without the field counts 0); %(f_lock_ms)s the wait for the vote lock. The vote gate reads "
               "%(f_total_ms)s p95, so an arm with vote_queue_fix on is judged like one with it off; %(f_lock_ms)s p95 "
               "stays beside it. Refusals: %(v_behind)s (the voter was not ready: its execution had not reached the "
               "header's block) and %(v_superseded)s (a newer request of the same author had arrived; vote_queue_fix "
               "on).")


def prelock_logged(nds, validators):
    """True when a validator's 'vote path timing' line in a row window carries prelock_wait_ms (a bench-7 build): the
    run then gets VOTE_PATH_KEYS on every row and its vote gate reads total_ms (CHECK_REPLACES)."""
    return any(v[7] is not None for n in validators if n in nds for v in nds[n].votes)


def vote_rows(nds, validators, a, b, prelock_run=False):
    out = {}
    votes = [v for n in validators if n in nds for v in between(nds[n].votes, a, b)]
    if not votes:
        miss = na("'%s' lines in the window" % F["msg_vote"])
        out = {"vote_lock_p95_ms": miss, "behind_per_header_max": miss, "behind_per_header_max_minus_f": miss}
        if prelock_run:
            out.update((k, miss) for k in VOTE_PATH_KEYS)
        return out
    locks = [v[5] for v in votes if v[5] is not None]
    out["vote_lock_p95_ms"] = pctl(locks, 0.95) if locks else na("%s on '%s'" % (F["f_lock_ms"], F["msg_vote"]))
    per = collections.defaultdict(set)                         # header -> the voters that refused it as behind
    for n in validators:
        for v in between(nds[n].votes, a, b) if n in nds else []:
            if v[4] == F["v_behind"]:
                per[(v[1], v[2], v[3])].add(n)
    f = (len(validators) - 1) // 3
    worst = max(len(x) for x in per.values()) if per else 0
    out["behind_per_header_max"] = worst
    out["behind_per_header_max_minus_f"] = worst - f
    if prelock_run:     # bench 7: the whole vote path, the wait before the lock (0 where a line lacks it), superseded
        totals = [v[6] for v in votes if v[6] is not None]
        miss = na("%s on '%s'" % (F["f_total_ms"], F["msg_vote"]))
        out["vote_total_p50_ms"] = pctl(totals, 0.5) if totals else miss
        out["vote_total_p95_ms"] = pctl(totals, 0.95) if totals else miss
        out["vote_prelock_p95_ms"] = pctl([v[7] if v[7] is not None else 0 for v in votes], 0.95)
        out["votes_superseded"] = sum(1 for v in votes if v[4] == F["v_superseded"])
    return out


def switch_on(arm_rec, key):
    """An arm's switch as a bool (a YAML scalar: false, 0, 0s and 0ms are off); None without param_arms switches."""
    sw = arm_rec["switch_set"]
    if not isinstance(sw, dict):
        return None
    return str(sw.get(key, arm_rec["defaults"].get(key, ""))).strip().lower() not in ("", "false", "0", "0s", "0ms")


def read_series(run_dir, names):
    """({name: {node: [(t, v)]}}, {node: t}) from <run>/metrics.json prometheus.series: the points of the names it
    holds (each node's first query, sorted by name), and each node's first sample in any series (the collector
    writes every query's points in time order); ({}, {}) without the file."""
    path = os.path.join(run_dir, "metrics.json")
    try:
        doc = read_json(path) if os.path.isfile(path) else {}
    except (OSError, ValueError):
        doc = {}
    series = ((doc.get(F["m_prom"]) or {}) if isinstance(doc, dict) else {}).get(F["m_series"]) or {}
    out, first = {}, {}
    for name in names:
        for node, queries in ((series.get(name) or {}).get(F["m_by_node"]) or {}).items():
            if isinstance(queries, dict) and queries:
                pts = [(float(t), float(v)) for t, v in queries[sorted(queries)[0]] or [] if v is not None]
                out.setdefault(name, {})[node] = sorted(p for p in pts if p[1] == p[1])      # NaN dropped
    for ent in series.values():
        for node, queries in ((ent.get(F["m_by_node"]) or {}) if isinstance(ent, dict) else {}).items():
            for pts in (queries.values() if isinstance(queries, dict) else ()):
                if pts and isinstance(pts[0], list) and pts[0]:
                    first[node] = min(first.get(node, float(pts[0][0])), float(pts[0][0]))
    return out, first


def counter_rise(pts, a, b, since):
    """A cumulative counter's increase over [a, b] from all of one node's points [(t, v)] (in time order), by the
    collector's rule (tn-transaction-generator bench/collect-gcp-metrics.py window_count): a value below its
    predecessor is a restart, so the new value is all gained since; the first point inside the window is the base,
    unless it is the series' first point and the node was sampled before (`since`, its first sample in any series),
    when the node created the counter at first use inside the window and it counts from 0. None when nothing in the
    window measures an increase (one point that is neither). A restart in the step that straddles `a` counts the
    whole new value; a restart whose first value is not below the last before it counts only the difference (the
    collector's lower bound)."""
    idx = [k for k, p in enumerate(pts) if a <= p[0] <= b]
    if not idx:
        return None
    k = idx[0]
    if k == 0:
        n = pts[0][1] if since is not None and since < pts[0][0] else None
    else:
        n = pts[k][1] if pts[k][1] < pts[k - 1][1] else None
    if n is None and len(idx) < 2:
        return None
    n = n or 0.0
    for k in idx[1:]:
        x, y = pts[k - 1][1], pts[k][1]
        n += y - x if y >= x else y
    return n


def counter_total(prom, first, name, a, b):
    """The sum over nodes of counter_rise; None when no node's increase is measurable."""
    rises = [counter_rise(pts, a, b, first.get(n)) for n, pts in sorted((prom.get(name) or {}).items())]
    rises = [x for x in rises if x is not None]
    return sum(rises) if rises else None


def series_in(prom, name, a, b):
    """[(node, [(t, v)])] of the series' points in [a, b]; None when metrics.json does not hold the series."""
    if name not in prom:
        return None
    return [(n, [p for p in pts if a <= p[0] <= b]) for n, pts in sorted(prom[name].items())]


def bench6_cols(nds, validators, a, b, r, prom, first, prelock_run=False):
    """One row's bench-6 arm inputs (each n/a with what is missing, None where the arm's switch is off): storage,
    sealed keep, the admission bound, parent grace, the vote fix and the cycle time (commit interval)."""
    arm, m = r["arm_rec"], collections.OrderedDict()
    hdr = [p for n in validators if n in nds for p in between(nds[n].proposed, a, b)]
    # storage: prefault on <=> sum(page_prefault) ~ growth of mdbx_last_pgno; the advice applied on every node
    ratios, advised = collections.OrderedDict(), collections.OrderedDict()
    for n in sorted(nds):
        ps = between(nds[n].persisted, a, b)
        pts = [(p[3]["f_prefault"], p[3]["f_last_pgno"]) for p in ps]
        if len(pts) < 2 or any(x is None or y is None for x, y in pts):
            ratios[n] = na("%s and %s on every '%s' line in the window (two at least)" % (
                F["f_prefault"], F["f_last_pgno"], F["msg_persisted"]))
        elif pts[-1][1] <= pts[0][1]:
            ratios[n] = na("growth of %s in the window" % F["f_last_pgno"])
        else:
            ratios[n] = round(sum(x for x, _ in pts[1:]) / float(pts[-1][1] - pts[0][1]), 3)
        adv = [p[3]["f_advised"] for p in ps]
        advised[n] = max(adv) if adv and None not in adv else na("%s on every '%s' line in the window" % (
            F["f_advised"], F["msg_persisted"]))
    m["prefault_ratio_by_node"] = ratios
    vals = [v for v in ratios.values() if not is_na(v)]
    miss = [n for n, v in ratios.items() if is_na(v)]
    m["prefault_ratio_min"] = min(vals) if vals else next(iter(ratios.values()), na("node logs"))
    m["prefault_on_all"] = (na("the prefault ratio of %s" % ", ".join(miss)) if miss else
                            all(v >= PREFAULT_ON_MIN for v in vals) if vals else na("node logs"))
    if switch_on(arm, F["sw_advice"]):
        # what the node measured, not the switch line: advised bytes > 0 on its lines (else the gauge) and no
        # 'advice not applied' warning since the arm's begin; `node switches` shows the value even when refused
        gauge = dict(series_in(prom, F["p_advice_bytes"], a, b) or [])
        state, why = collections.OrderedDict(), []
        for n in sorted(nds):
            v = advised[n]
            if is_na(v) and gauge.get(n):
                v = advised[n] = max(x for _, x in gauge[n])
            refused = [t for t in nds[n].advice_refused if arm["arm_t0"] <= t < b]
            if refused:
                state[n] = False
                why.append("%s ('%s' at %s)" % (n, F["msg_advice_refused"], iso(refused[0])))
            elif is_na(v):
                state[n] = v
            else:
                state[n] = v > 0
                if not state[n]:
                    why.append("%s (%s 0)" % (n, F["f_advised"]))
        miss = [n for n, v in state.items() if is_na(v)]
        vals = [v for v in advised.values() if not is_na(v)]
        m["mdbx_advised_min_bytes"] = min(vals) if vals else na("%s or metrics.json %s" % (F["f_advised"],
                                                                                          F["p_advice_bytes"]))
        m["advice_on_by_node"] = state
        m["mdbx_advised_all_nodes"] = (False if why else na("%s or metrics.json %s on %s" % (
            F["f_advised"], F["p_advice_bytes"], ", ".join(miss))) if miss else bool(state))
        m["storage_note"] = ("advice not in force on %s: the storage columns of this arm are not an advice "
                             "measurement for that node" % "; ".join(why)) if why else None
    else:
        m["mdbx_advised_min_bytes"] = m["advice_on_by_node"] = m["mdbx_advised_all_nodes"] = m["storage_note"] = None
    # recovery pool: a node recovers on the dedicated pool only when its 'signers recovered' lines in the window all
    # say pool=dedicated and it logged no build failure since the arm's begin (the switch line and gauge still read
    # the configured threads after a failure, and the node recovers on the global pool for the rest of the process)
    if switch_on(arm, F["sw_recovery"]):
        state, why = collections.OrderedDict(), []
        for n in sorted(nds):
            failed = [t for t in nds[n].pool_failed if arm["arm_t0"] <= t < b]
            pools = [x[1] for x in between(nds[n].recovered, a, b)]
            other = [p for p in pools if p != F["v_dedicated"]]
            if failed:
                state[n] = False
                why.append("%s ('%s' at %s)" % (n, F["msg_pool_failed"], iso(failed[0])))
            elif not pools:
                state[n] = na("'%s' lines in the window" % F["msg_recovered"])
            else:
                state[n] = not other
                if other:
                    why.append("%s (%s=%s on %d of %d '%s' lines)" % (n, F["f_pool"], other[0], len(other),
                                                                    len(pools), F["msg_recovered"]))
        m["recovery_pool_by_node"] = state
        m["recovery_pool_note"] = ("dedicated recovery pool not in use on %s: this arm does not measure the pool on "
                                   "that node" % "; ".join(why)) if why else None
    else:
        m["recovery_pool_by_node"] = m["recovery_pool_note"] = None
    # sealed keep: keeps_sealed=true on every validator's builder start since the arm's begin, else not acting
    if switch_on(arm, F["sw_sealed"]):
        seen = dict((n, [x[1] for x in (nds[n].builders if n in nds else []) if arm["arm_t0"] <= x[0] < b])
                    for n in validators)
        miss = [n for n in validators if not seen[n]]
        off = [n for n in validators if seen[n] and any(v != F["v_true"] for v in seen[n])]
        m["sealed_keep"] = (na("'%s' since the arm's begin on %s" % (F["msg_builder"], ", ".join(miss))) if miss else
                            "switch not acting (%s not true on %s)" % (F["f_keeps_sealed"], ", ".join(off)) if off
                            else "acting")
    else:
        m["sealed_keep"] = None
    pts = series_in(prom, F["p_sealed_marked"], a, b)
    peak = [v for _, xs in pts or [] for _, v in xs]
    m["sealed_marked_peak"] = max(peak) if peak else na("metrics.json %s samples in the window" % F["p_sealed_marked"])
    # admission bound: refused requests (node counter, else the generator's pool_full class), what the generator
    # dropped after refusals; the confirmation latency of what was admitted is land_p50_s / land_p95_s
    rise = counter_total(prom, first, F["p_refused"], a, b)
    m["admission_refused"] = (int(rise) if rise is not None else
                              na("metrics.json %s samples in the window" % F["p_refused"]))
    pool_full = dropped = None
    for d in r["docs"]:
        for x in d.get(F["b_nodes"]) or []:
            errs = x.get(F["b_errors"]) if isinstance(x, dict) else None
            if isinstance(errs, dict) and isinstance(errs.get(F["b_pool_full"]), (int, float)):
                pool_full = (pool_full or 0) + errs[F["b_pool_full"]]
        res = (d.get(F["b_totals"]) or {}).get(F["b_resends"])
        if isinstance(res, dict) and isinstance(res.get(F["b_r_dropped"]), (int, float)):
            dropped = (dropped or 0) + res[F["b_r_dropped"]]
    m["gen_pool_full"] = pool_full if pool_full is not None else na("%s[].%s.%s (tn-blast)" % (
        F["b_nodes"], F["b_errors"], F["b_pool_full"]))
    m["gen_dropped"] = dropped if dropped is not None else na("%s.%s.%s (tn-blast H9a)" % (
        F["b_totals"], F["b_resends"], F["b_r_dropped"]))
    # parent grace: the cost (headers that waited, how long) beside the outcomes; the benefit is the far
    # validators' certified / committed share (measure())
    graces = [p[1] for p in hdr if p[1] is not None]
    if not graces:
        m["grace_share_pct"] = m["grace_wait_p50_ms"] = m["grace_wait_p90_ms"] = m["grace_outcomes"] = na(
            "%s on '%s'" % (F["f_grace_ms"], F["msg_proposed"]))
    else:
        waits = [x for x in graces if x > 0]
        m["grace_share_pct"] = r1(100.0 * len(waits) / len(graces))
        m["grace_wait_p50_ms"], m["grace_wait_p90_ms"] = pctl(waits, 0.5), pctl(waits, 0.9)
        ended = collections.Counter(e[1] for n in validators if n in nds for e in between(nds[n].grace_ended, a, b))
        m["grace_outcomes"] = collections.OrderedDict(sorted(ended.items()))
    # vote fix: the execution-block policy of the own headers, the lag it allowed, the votes refused as behind
    pol = [p[2] for p in hdr if p[2] is not None]
    m["exec_policy_pct"] = (collections.OrderedDict((k, r1(100.0 * v / len(pol)))
                                                    for k, v in sorted(collections.Counter(pol).items()))
                            if pol else na("%s on '%s'" % (F["f_exec_policy"], F["msg_proposed"])))
    lag = [p[3] - p[4] for p in hdr if p[3] is not None and p[4] is not None]
    m["exec_lag_p50"] = median(lag) if lag else na("%s / %s on '%s'" % (F["f_exec_tip"], F["f_exec_block"],
                                                                         F["msg_proposed"]))
    refused, superseded = collections.OrderedDict(), collections.OrderedDict()
    for n in validators:
        vs = between(nds[n].votes, a, b) if n in nds else []
        refused[n] = sum(1 for v in vs if v[4] == F["v_behind"]) if vs else na("'%s' lines in the window" % F["msg_vote"])
        superseded[n] = sum(1 for v in vs if v[4] == F["v_superseded"]) if vs else refused[n]
    m["votes_refused_behind"] = refused
    if prelock_run:     # bench 7: refused because a newer request of the same author arrived (vote_queue_fix on)
        m["votes_refused_superseded"] = superseded
    # cycle time: the commit interval compares a pipelined arm with a sequential one; task_ms does not (D55)
    iv = []
    for n in validators:
        ts = [p[0] for p in between(nds[n].persisted, a, b)] if n in nds else []
        if len(ts) > 1:
            iv.append(median([y - x for x, y in zip(ts, ts[1:])]) * 1000.0)
    m["commit_interval_ms"] = r1(median(iv)) if iv else na("two '%s' lines in the window" % F["msg_persisted"])
    m["pipelined"] = switch_on(arm, F["sw_pipelined"])
    return m


# ---------------------------------------------------------------- the report

def measure(run_dir, manifest, rows, nds, validators, persist_dir, cert_doc, stage_doc, blocks, axis, caps, groups):
    t_first = blocks[0][0] if blocks else None
    cum = []
    acc = 0
    for t, x in blocks:
        acc += x
        cum.append(acc)
    btimes = [t for t, _ in blocks]
    prom, first = read_series(run_dir, (F["p_sealed_marked"], F["p_refused"], F["p_advice_bytes"]))
    csv_cache = {}
    for name in nds:
        p = os.path.join(persist_dir, "%s.csv" % name)
        csv_cache[name] = persist_rows(p) if os.path.isfile(p) else None
    stores = collections.OrderedDict((n, node_store(nds[n], csv_cache[n])) for n in sorted(nds))
    lmdb_run = F["v_tn_lmdb"] in stores.values()
    prelock_run = prelock_logged(nds, validators)
    for r in rows:
        a, b = r["from"], r["to"]
        m = collections.OrderedDict()
        sw = r["arm_rec"]["switch_set"]
        m["switch_set"] = (",".join("%s=%s" % (k, v) for k, v in sorted(sw.items())
                                    if str(v) != str(r["arm_rec"]["defaults"].get(k))) or "all defaults") if sw else \
            na("param_arms[].%s" % F["m_switches"])
        i0, i1 = bisect.bisect_left(btimes, a), bisect.bisect_left(btimes, b)
        if r["docs"] or i1 > i0:
            m["chain_txps"] = r1(sum(x for _, x in blocks[i0:i1]) / (b - a)) if i1 > i0 else na("blocks in the window")
            m["chain_blocks"] = i1 - i0
        else:
            m["chain_txps"] = na("generator block tables")
        own = 0
        have = False
        for d in r["docs"]:
            s = series(d, "b_ps_cols", "b_ps", "b_ps_t0")
            if s and F["b_own_tx"] in s[0]:
                have = True
                io_ = s[0].index(F["b_own_tx"])
                i_s = s[0].index(F["b_s"]) if F["b_s"] in s[0] else 0
                own += sum(row[io_] for row in s[1] if a <= s[2] + row[i_s] < b)
        m["landed_txps"] = r1(own / (b - a)) if have else na("series.%s %s" % (F["b_ps"], F["b_own_tx"]))
        lat = pooled_latency(r["docs"])
        for k, src, q in (("land_p50_s", "k_ts", "k_p50"), ("land_p95_s", "k_ts", "k_p95"),
                          ("gen_seen_p50_s", "k_seen", "k_p50"), ("gen_seen_p95_s", "k_seen", "k_p95")):
            v = (lat.get(F[src]) or {}).get(F[q]) if isinstance(lat, dict) else None
            m[k] = round(v / 1000.0, 2) if isinstance(v, (int, float)) else (lat if is_na(lat) else na("generator latency histograms"))
        # engine, amplification, rr per node
        per_node = collections.OrderedDict()
        for n in sorted(nds):
            e = engine_row(nds[n], a, b)
            lmdb = stores[n] == F["v_tn_lmdb"]
            amp, rr = amp_row(nds[n], csv_cache.get(n), a, b, lmdb)
            e.update(amp)
            e.update(rr)
            e.update(disk_row(nds[n], csv_cache.get(n), a, b, node_caps(caps, groups, n)))
            if lmdb_run:
                e["store"] = stores[n]
                e.update(store_row(nds[n], csv_cache.get(n), a, b) if lmdb else collections.OrderedDict(
                    (k, na("a %s store on this node (%s)" % (F["v_tn_lmdb"], stores[n] or "unknown"))) for k, _ in STORE_COLS))
            if groups:
                e[F["o_disk_class"]] = groups[n][0]
            if "proc_written_bytes" in e and switch_on(r["arm_rec"], F["sw_pipelined"]):
                e["proc_written_bytes_upper_bound"] = True     # D56: pipelined persists overlap the next build
            per_node[n] = e
        m["engine_by_node"] = per_node
        for k in ("exec_txps", "execute_us_tx", "persist_us_tx", "commit_us_tx", "commit_ms_output", "task_us_tx",
                  "txs_per_output"):
            vals = [per_node[n][k] for n in validators if n in per_node and not is_na(per_node[n][k])]
            m[k] = r1(median(vals)) if vals else (next((per_node[n][k] for n in validators if n in per_node), None)
                                                 or na("validator logs"))
        amps = [v["amp"] for v in per_node.values() if not is_na(v["amp"])]
        m["amp_fleet_median"] = round(median(amps), 3) if amps else next((v["amp"] for v in per_node.values()),
                                                                         na("node logs"))
        for k in ("refault_per_min", "majfault_per_min", "memcg_refault_per_min"):
            vals = [v[k] for v in per_node.values() if not is_na(v[k])]
            m[k + "_median"] = r1(median(vals)) if vals else next((v[k] for v in per_node.values()), na("node logs"))
        rrs = [v["rr_vma"] for v in per_node.values() if not is_na(v["rr_vma"])]
        m["rr_vma_min"] = min(rrs) if rrs else next((v["rr_vma"] for v in per_node.values()), na("node logs"))
        m["rr_vma_median"] = round(median(rrs), 4) if rrs else m["rr_vma_min"]
        # device writes against the disk's caps (H18): every node's median, how many nodes each cap binds, one line
        for k, d in DISK_COLS:
            vals = [v[k] for v in per_node.values() if not is_na(v[k])]
            m[k + "_median"] = round(median(vals), d) if vals else next((v[k] for v in per_node.values()), na("node logs"))
        bl = [v["binds"] for v in per_node.values() if v["binds"] in BINDS]
        m["binds_nodes"] = (collections.OrderedDict((x, bl.count(x)) for x in BINDS) if bl
                            else next((v["binds"] for v in per_node.values()), na("node logs")))
        m["disk_reading"] = class_reading(per_node, caps, groups)
        if lmdb_run:     # bench 7: the tn-lmdb figures, the validators' median (count and bytes, always both)
            for k, d in STORE_COLS:
                vals = [per_node[n][k] for n in validators if n in per_node and not is_na(per_node[n][k])]
                m[k + "_median"] = round(median(vals), d) if vals else next(
                    (per_node[n][k] for n in validators if n in per_node), na("validator logs"))
        by_group = group_medians(per_node, validators, groups)
        if by_group:
            m["by_disk_class"] = by_group
        ev = [res.get(F["m_res_after"]) for h in r["arm_rec"]["host_steps"] if h.get(F["m_step"]) == F["m_evict"]
              for res in (h.get(F["m_nodes"]) or {}).values() if isinstance(res, dict)]
        ev = [x for x in ev if isinstance(x, (int, float))]
        m["evict_resident_after_max"] = max(ev) if ev else na("param_arms[].%s %s results" % (F["m_host"], F["m_evict"]))
        m["commit_fit"] = commit_fit(nds, validators, a, b)
        # certification
        cw = (cert_doc or {}).get(r["row_id"])
        if cw:
            certs = collections.OrderedDict()
            for n in validators:
                c = cw.get(n)
                if c:
                    nc = c.get(F["r_not_committed"])
                    certs[n] = {"certified_pct": c.get(F["r_rate"]), "proposed_n": c.get(F["r_proposed"]),
                                "committed_pct": None if nc is None else round(100.0 - nc, 1)}
            m["cert_by_validator"] = certs
            rates = [(v["certified_pct"], n) for n, v in certs.items() if v["certified_pct"] is not None]
            m["cert_min_pct"] = min(rates)[0] if rates else na("own headers proposed in the window")
            m["cert_min_node"] = min(rates)[1] if rates else None
            gn = [certs[n]["committed_pct"] for n in GRACE_NODES if n in certs and certs[n]["committed_pct"] is not None]
            m["grace_nodes_committed_min_pct"] = min(gn) if gn else na("%s committed share" % "/".join(GRACE_NODES))
            gc = [certs[n]["certified_pct"] for n in GRACE_NODES if n in certs and certs[n]["certified_pct"] is not None]
            m["grace_nodes_certified_min_pct"] = min(gc) if gc else na("%s certified share" % "/".join(GRACE_NODES))
        else:
            m["cert_by_validator"] = {}
            m["cert_min_pct"] = m["grace_nodes_committed_min_pct"] = na("validator logs for cert-rate.py")
            m["grace_nodes_certified_min_pct"] = m["cert_min_pct"]
        m.update(vote_rows(nds, validators, a, b, prelock_run))
        trk = [t for n in nds for t in between(nds[n].tracker, a, b, key=lambda x: x)]
        m["tracker_errors"] = len(trk) if nds else na("node logs")
        # generators
        lnd = landings(r["group"], r["docs"]) if r["group"] else None
        m["landings_ge300"] = lnd[0] if lnd else na("landings-<blaster>.ndjson.gz")
        m["landings_sampled"] = lnd[1] if lnd else None
        m["landings_sample_rate"] = lnd[2] if lnd else None
        res = [((d.get(F["b_totals"]) or {}).get(F["b_resends"])) for d in r["docs"]]
        res = [x for x in res if isinstance(x, dict)]
        if res:
            tot = collections.OrderedDict()
            for x in res:
                for k, v in x.items():
                    if isinstance(v, (int, float)):
                        tot[k] = tot.get(k, 0) + v
            m["resends_by_cause"] = tot
            m["resends_total"] = sum(tot.get(F[k], 0) for k in ("b_r_transient", "b_r_other", "b_r_gap_txs", "b_r_nonce",
                                                                "b_r_fee"))
        else:
            m["resends_by_cause"] = m["resends_total"] = na("%s.%s (tn-blast H9a)" % (F["b_totals"], F["b_resends"]))
        tails = [(d.get(F["b_run"]) or {}).get(F["b_tail"]) for d in r["docs"]]
        tails = [t for t in tails if isinstance(t, dict)]
        m["tail_landed_late"] = (sum(t.get(F["b_landed_late"]) or 0 for t in tails) if tails
                                 else na("run.%s (tn-blast H9b)" % F["b_tail"]))
        m["tail_unlanded_after"] = (sum(t.get(F["b_unlanded_after"]) or 0 for t in tails) if tails
                                    else m["tail_landed_late"])
        bl = (r["group"] or {}).get("bm") or {}
        lates = [x.get(F["m_late"]) for x in bl.get(F["m_blasters"]) or [] if isinstance(x, dict)]
        lates = [x for x in lates if isinstance(x, (int, float))]
        m["late_secs_max"] = max(lates) if lates else na("manifest %s[].%s" % (F["m_blasters"], F["m_late"]))
        silent = []
        for d in r["docs"]:
            s = series(d, "b_send_cols", "b_send", "b_send_t0")
            if not s:
                continue
            idx = [s[0].index(F[k]) for k in ("b_submitted", "b_resent", "b_resigned") if F[k] in s[0]]
            i_s = s[0].index(F["b_s"]) if F["b_s"] in s[0] else 0
            run_len = best = 0
            for row in s[1]:
                if not (a <= s[2] + row[i_s] < b):
                    continue
                run_len = run_len + 1 if sum(row[i] for i in idx) == 0 else 0
                best = max(best, run_len)
            silent.append(best)
        m["gen_silent_max_s"] = max(silent) if silent else na("series.%s (tn-blast H9a)" % F["b_send"])
        # stages
        sw_ = (stage_doc or {}).get(r["row_id"])
        if sw_ is None:
            m["stages"] = na("tools/stage-latency.py output for this window")
            m["stage_seen_p50_s"] = m["stage_seen_p95_s"] = m["stages"]
        else:
            m["stage_seen_p50_s"] = sw_["h"].get(F["t_seen50"])
            m["stage_seen_p95_s"] = sw_["h"].get(F["t_seen95"])
            m["stages"] = collections.OrderedDict((s, {"median_ms": v.get(F["t_p50ms"]), "n": v.get(F["t_count"])})
                                                  for s, v in sw_["p"].items())
        m.update(bench6_cols(nds, validators, a, b, r, prom, first, prelock_run))
        # drift axis position
        mid = (a + b) / 2.0
        if axis == "wall-min":
            m["drift_x"] = r1((mid - (t_first if t_first is not None else rows[0]["from"])) / 60.0)
        else:
            m["drift_x"] = round(cum[bisect.bisect_left(btimes, mid) - 1] / 1e6, 3) if btimes and mid > btimes[0] else 0.0
        r["m"] = m
    return stores if lmdb_run else None


_KPIS = []


def pooled_latency(docs):
    if not docs:
        return na("generator files")
    try:
        if not _KPIS:
            _KPIS.append(load_tool(os.path.join(BENCH, "report", KPIS), "kpis_for_arms"))
        return _KPIS[0].pooled_latency(docs)
    except (OSError, ImportError, AttributeError, ValueError) as e:
        return na("report/%s pooled_latency (%s)" % (KPIS, e))


def apply_drift(rows):
    """Per blast type: slope from the first and last control rows of distinct arms; corrected values per row."""
    out = collections.OrderedDict()
    for typ in sorted({r["blast_type"] for r in rows}):
        ctl = [r for r in rows if r["blast_type"] == typ and r["arm_rec"]["control"] and not is_na(r["m"]["commit_us_tx"])]
        arms_seen = []
        for r in ctl:
            if r["arm_rec"]["arm_name"] not in [x["arm_rec"]["arm_name"] for x in arms_seen]:
                arms_seen.append(r)
        if len(arms_seen) < 2:
            out[typ] = {"note": na("two control arms with a %s row and engine logs" % typ)}
            for r in rows:
                if r["blast_type"] == typ:
                    r["m"]["commit_us_tx_corrected"] = r["m"]["commit_ms_output_corrected"] = out[typ]["note"]
                    r["m"]["drift_moved_pct_abs"] = out[typ]["note"]
            continue
        first, last = arms_seen[0], arms_seen[-1]
        dx = last["m"]["drift_x"] - first["m"]["drift_x"]
        moved = last["m"]["commit_us_tx"] / first["m"]["commit_us_tx"] - 1.0
        d = {"first": first["row_id"], "last": last["row_id"], "x_first": first["m"]["drift_x"], "x_last": last["m"]["drift_x"],
             "commit_us_tx_first": first["m"]["commit_us_tx"], "commit_us_tx_last": last["m"]["commit_us_tx"],
             "moved_pct": round(100.0 * moved, 1), "adjacent_only": abs(moved) > DRIFT_LIMIT}
        if not dx:
            d["note"] = na("a drift-axis distance between %s and %s" % (first["row_id"], last["row_id"]))
        else:
            d["slope_us_tx_per_x"] = round((last["m"]["commit_us_tx"] - first["m"]["commit_us_tx"]) / dx, 3)
            mo = (first["m"]["commit_ms_output"], last["m"]["commit_ms_output"])
            d["slope_ms_output_per_x"] = None if any(is_na(v) for v in mo) else round((mo[1] - mo[0]) / dx, 3)
        out[typ] = d
        for r in rows:
            if r["blast_type"] != typ:
                continue
            m = r["m"]
            if "slope_us_tx_per_x" not in d or is_na(m["commit_us_tx"]):
                m["commit_us_tx_corrected"] = d.get("note") or m["commit_us_tx"]
            else:
                m["commit_us_tx_corrected"] = r1(m["commit_us_tx"] - d["slope_us_tx_per_x"] * (m["drift_x"] - d["x_first"]))
            if d.get("slope_ms_output_per_x") is None or is_na(m["commit_ms_output"]):
                m["commit_ms_output_corrected"] = d.get("note") or na("commit ms/output on both controls")
            else:
                m["commit_ms_output_corrected"] = r1(m["commit_ms_output"] - d["slope_ms_output_per_x"] *
                                                     (m["drift_x"] - d["x_first"]))
            m["drift_moved_pct_abs"] = abs(d["moved_pct"])
    return out


def apply_checks(rows):
    done = []
    for r in rows:
        m = r["m"]
        p = next((x for x in reversed(done) if x["blast_type"] == r["blast_type"] and
                  x["arm_rec"]["arm_name"] != r["arm_rec"]["arm_name"]), None)
        done.append(r)
        if p is not None and not is_na(m["chain_txps"]) and not is_na(p["m"]["chain_txps"]):
            m["chain_txps_vs_prev"] = r1(m["chain_txps"] - p["m"]["chain_txps"])
        else:
            m["chain_txps_vs_prev"] = na("a previous arm's %s row with chain tx/s" % r["blast_type"])
        verdict = []
        replaced = set(old for new, old in CHECK_REPLACES.items() if new in m)
        for role, label, types, key, op, thr in CHECKS:
            if role not in r["arm_rec"]["roles"] or (types is not None and r["blast_type"] not in types):
                continue
            if key in replaced or (key in CHECK_REPLACES and key not in m):
                continue
            v = m.get(key)
            if v is None or is_na(v):
                verdict.append({"check": label, "value": v if is_na(v) else na(key), "met": None})
                continue
            ok = {">": v > thr, ">=": v >= thr, "<": v < thr, "<=": v <= thr, "==": v == thr}[op]
            verdict.append({"check": label, "value": v, "met": ok})
        m["verdict"] = verdict


def cell(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return "{:,.1f}".format(v) if abs(v) >= 100 else ("%.3f" % v if abs(v) < 10 else "%.1f" % v)
    return str(v)


def dict_cell(d):
    if not isinstance(d, dict):
        return cell(d)
    return ", ".join("%s %s" % (k, cell(v)) for k, v in d.items()) or "none"


def verdict_text(vs):
    if not vs:
        return "– (no threshold for this arm and type)"
    return "; ".join("%s: %s" % (x["check"], x["value"] if x["met"] is None else "%s %s" % (
        cell(x["value"]), "met" if x["met"] else "not met")) for x in vs)


def to_markdown(doc, rows, drift, axis):
    out = ["# Arms summary: %s" % doc["run_name"], ""]
    for s in doc["notes"]:
        out.append("- %s" % s)
    flags = [t for t, d in drift.items() if d.get("adjacent_only")]
    out.append("- drift axis: %s; %s" % (axis, ("commit us/tx moved > 15 %% between the controls for %s: compare "
                                                "adjacent arms only" % ", ".join(flags)) if flags else
                                       "no control pair moved > 15 %"))
    for t, d in drift.items():
        out.append("- drift %s: %s" % (t, d.get("note") or "%s -> %s, commit %s -> %s us/tx (%+.1f %%), slope %s us/tx per "
                                       "axis unit" % (d["first"], d["last"], cell(d["commit_us_tx_first"]),
                                                      cell(d["commit_us_tx_last"]), d["moved_pct"],
                                                      cell(d.get("slope_us_tx_per_x")))))
    out += ["", "| row | window (UTC) | s | switches on | chain tx/s | landed tx/s | land p50 / p95 s | seen p50 / p95 s "
            "| execute / persist / commit us/tx | commit ms/output | commit us/tx corrected | drift fit c s/min | amp "
            "(median) | rr/vma (min) | cert min % | landings >= 300 s | resends | late_secs max | silent max s "
            "| tracker errors | verdict |", "|---|---|---:|---|" + "---:|" * 16 + "---|"]
    for r in rows:
        m = r["m"]
        fit = m["commit_fit"]
        out.append("| %s | %s → %s | %d | %s | %s | %s | %s / %s | %s / %s | %s / %s / %s | %s | %s | %s | %s | %s | %s | "
                   "%s | %s | %s | %s | %s | %s |" % (
                       r["row_id"], iso(r["from"])[11:19], iso(r["to"])[11:19], int(r["to"] - r["from"]), m["switch_set"],
                       cell(m["chain_txps"]), cell(m["landed_txps"]), cell(m["land_p50_s"]), cell(m["land_p95_s"]),
                       cell(m["gen_seen_p50_s"]), cell(m["gen_seen_p95_s"]), cell(m["execute_us_tx"]), cell(m["persist_us_tx"]),
                       cell(m["commit_us_tx"]), cell(m["commit_ms_output"]), cell(m.get("commit_us_tx_corrected")),
                       fit if is_na(fit) else "%.4f" % fit["c_s_per_min"], cell(m["amp_fleet_median"]), cell(m["rr_vma_min"]),
                       cell(m["cert_min_pct"]) + (" (%s)" % m["cert_min_node"] if m.get("cert_min_node") else ""),
                       cell(m["landings_ge300"]), cell(m["resends_total"]), cell(m["late_secs_max"]),
                       cell(m["gen_silent_max_s"]), cell(m["tracker_errors"]), verdict_text(m["verdict"])))
    out += ["", "| row | prefault on (min ratio) | advice on every node (min bytes) | refault / majfault / memcg "
            "refault per min (median) | sealed keep (marked peak) | refused (node) / pool_full / dropped (gen) | grace "
            "share % (wait p50 / p90 ms) | grace outcomes | far certified / committed min % | exec policy % | exec "
            "lag p50 | commit interval ms |", "|---|" + "---|" * 11]
    storage_notes = []
    for r in rows:
        m = r["m"]
        out.append("| %s | %s (%s) | %s (%s) | %s / %s / %s | %s (%s) | %s / %s / %s | %s (%s / %s) | %s | %s / %s | %s | "
                   "%s | %s%s |" % (
                       r["row_id"], cell(m["prefault_on_all"]), cell(m["prefault_ratio_min"]),
                       cell(m["mdbx_advised_all_nodes"]), cell(m["mdbx_advised_min_bytes"]),
                       cell(m["refault_per_min_median"]), cell(m["majfault_per_min_median"]),
                       cell(m["memcg_refault_per_min_median"]), cell(m["sealed_keep"]), cell(m["sealed_marked_peak"]),
                       cell(m["admission_refused"]), cell(m["gen_pool_full"]), cell(m["gen_dropped"]),
                       cell(m["grace_share_pct"]), cell(m["grace_wait_p50_ms"]), cell(m["grace_wait_p90_ms"]),
                       dict_cell(m["grace_outcomes"]), cell(m["grace_nodes_certified_min_pct"]),
                       cell(m["grace_nodes_committed_min_pct"]), dict_cell(m["exec_policy_pct"]),
                       cell(m["exec_lag_p50"]), cell(m["commit_interval_ms"]), " (pipelined)" if m["pipelined"] else ""))
        for k in ("storage_note", "recovery_pool_note"):
            if m.get(k):
                storage_notes.append("- %s: %s." % (r["row_id"], m[k]))
    out += ([""] + storage_notes if storage_notes else []) + [""]
    lmdb = doc.get("store_by_node")
    if lmdb:
        out += ["Store (%s): %s. Device writes per transaction count AND bytes; the store's growth is %s + %s; the "
                "validators' median." % (F["v_tn_lmdb"], dict_cell(lmdb), F["c_lmdb_used"], F["c_static_size"]), "",
                "| row | write ops / tx | write bytes / tx | KiB / op | flushes / output | commit ms / output | save_blocks "
                "ms / output | store growth bytes / tx |", "|---|" + "---:|" * 7]
        for r in rows:
            m = r["m"]
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["row_id"], cell(m["wr_ops_per_tx_median"]), cell(m["wr_bytes_per_tx_median"]),
                cell(m["wr_kib_per_op_median"]), cell(m["flush_ops_per_output_median"]), cell(m["commit_ms_output"]),
                cell(m["save_blocks_ms_output_median"]), cell(m["store_growth_bytes_per_tx_median"])))
        out.append("")
    vote_path = any(VOTE_PATH_KEYS[1] in r["m"] for r in rows)
    if vote_path:       # bench 7: the vote lines carry prelock_wait_ms
        out += [VOTE_LEGEND % dict((k, F[k]) for k in ("msg_vote", "f_prelock_ms", "f_total_ms", "f_lock_ms",
                                                       "v_behind", "v_superseded")), ""]
    for r in rows:
        m = r["m"]
        groups = m.get("by_disk_class") or []
        out += ["## %s: %s → %s (%d s; %s; blast index %s%s)" % (
            r["row_id"], iso(r["from"]), iso(r["to"]), int(r["to"] - r["from"]), r["basis"], r["blast_idx"],
            "; validators in %d groups: %s" % (len(groups), ", ".join(group_label(g) for g in groups)) if groups else ""),
            ""]
        out += ["| node | exec tx/s | execute | persist | commit | task us/tx | tx/output | commit ms/output | amp | "
                "rr/vma | certified % | committed % |", "|---|" + "---:|" * 11]
        for n, e in m["engine_by_node"].items():
            c = m["cert_by_validator"].get(n) or {}
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                n, cell(e["exec_txps"]), cell(e["execute_us_tx"]), cell(e["persist_us_tx"]), cell(e["commit_us_tx"]),
                cell(e["task_us_tx"]), cell(e["txs_per_output"]), cell(e["commit_ms_output"]), cell(e["amp"]),
                cell(e["rr_vma"]), cell(c.get("certified_pct")), cell(c.get("committed_pct"))))
        st = m["stages"]
        out += ["", "Per node: prefault ratio %s; refault/min %s; votes refused as behind %s%s." % (
            dict_cell(m["prefault_ratio_by_node"]), dict_cell(dict((n, e["refault_per_min"]) for n, e in
                                                                   m["engine_by_node"].items())),
            dict_cell(m["votes_refused_behind"]),
            "; as %s %s" % (F["v_superseded"], dict_cell(m["votes_refused_superseded"])) if vote_path else "")]
        if any(not is_na(e["wr_iops"]) for e in m["engine_by_node"].values()):
            out += ["", "| node | write ops / output | KiB / op | flushes / output | write IOPS (peak) | write MiB/s (peak) "
                    "| ms / write | ms / flush | % of IOPS cap | % of MiB/s cap | binds | cap floor ms / output |",
                    "|---|" + "---:|" * 9 + "---|---:|"]
            for n, e in m["engine_by_node"].items():
                out.append("| %s | %s | %s | %s | %s (%s) | %s (%s) | %s | %s | %s | %s | %s | %s |" % (
                    n, cell(e["wr_ops_per_output"]), cell(e["wr_kib_per_op"]), cell(e["flush_ops_per_output"]),
                    cell(e["wr_iops"]), cell(e["wr_iops_peak"]), cell(e["wr_mibps"]), cell(e["wr_mibps_peak"]),
                    cell(e["wr_ms_per_op"]), cell(e["flush_ms_per_op"]), cell(e["iops_pct_of_cap"]),
                    cell(e["mibps_pct_of_cap"]), cell(e["binds"]), cell(e["cap_floor_ms_per_output"])))
        if lmdb:
            out += ["", "| node | store | write ops / tx | write bytes / tx | KiB / op | flushes / output | commit ms / "
                    "output | save_blocks ms / output | store growth bytes / tx |", "|---|---|" + "---:|" * 7]
            for n, e in m["engine_by_node"].items():
                out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    n, e["store"] or "–", cell(e["wr_ops_per_tx"]), cell(e["wr_bytes_per_tx"]), cell(e["wr_kib_per_op"]),
                    cell(e["flush_ops_per_output"]), cell(e["commit_ms_output"]), cell(e["save_blocks_ms_output"]),
                    cell(e["store_growth_bytes_per_tx"])))
        out += ["", "Disk: %s." % m["disk_reading"]]
        if groups:
            # the byte ratio (amp) stands beside the commit time, the write and flush counts and the write size
            out += ["", "By disk class (the validators' median per disk class and machine type; the fleet medians above "
                    "are over all validators):", "",
                    "| disk class / machine type (validators) | exec tx/s | execute | persist | commit | task us/tx | "
                    "tx/output | commit ms/output | amp | write ops / output | flushes / output | KiB / op | write IOPS "
                    "(peak) | write MiB/s (peak) | ms / write | ms / flush | % of IOPS cap | % of MiB/s cap | cap floor "
                    "ms / output | refault / majfault / memcg refault per min |", "|---|" + "---:|" * 19]
            for g in groups:
                out.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s (%s) | %s (%s) | %s | %s | %s "
                           "| %s | %s | %s / %s / %s |" % (
                               group_label(g), cell(g["exec_txps"]), cell(g["execute_us_tx"]), cell(g["persist_us_tx"]),
                               cell(g["commit_us_tx"]), cell(g["task_us_tx"]), cell(g["txs_per_output"]),
                               cell(g["commit_ms_output"]), cell(g["amp"]), cell(g["wr_ops_per_output"]),
                               cell(g["flush_ops_per_output"]), cell(g["wr_kib_per_op"]), cell(g["wr_iops"]),
                               cell(g["wr_iops_peak"]), cell(g["wr_mibps"]), cell(g["wr_mibps_peak"]),
                               cell(g["wr_ms_per_op"]), cell(g["flush_ms_per_op"]), cell(g["iops_pct_of_cap"]),
                               cell(g["mibps_pct_of_cap"]), cell(g["cap_floor_ms_per_output"]), cell(g["refault_per_min"]),
                               cell(g["majfault_per_min"]), cell(g["memcg_refault_per_min"])))
        out += ["", "Stages (p50 ms): %s." % (st if is_na(st) else ", ".join(
            "%s %s" % (k, cell(v["median_ms"])) for k, v in st.items())),
            "Votes: %slock_ms p95 %s; behind refusals per header, max %s%s. Commit fit: %s." % (
                "%s p50 / p95 %s / %s (the gate); %s p95 %s; " % (
                    F["f_total_ms"], cell(m["vote_total_p50_ms"]), cell(m["vote_total_p95_ms"]), F["f_prelock_ms"],
                    cell(m["vote_prelock_p95_ms"])) if vote_path else "",
                cell(m["vote_lock_p95_ms"]), cell(m["behind_per_header_max"]),
                "; %s refusals %s" % (F["v_superseded"], cell(m["votes_superseded"])) if vote_path else "",
                m["commit_fit"] if is_na(m["commit_fit"]) else "a %.4f s + b %s s per 1k txs + c %.4f s/min, r2 %s, n %d" % (
                    m["commit_fit"]["a_s"], cell(m["commit_fit"]["b_s_per_1k_txs"]), m["commit_fit"]["c_s_per_min"],
                    m["commit_fit"]["r2"], m["commit_fit"]["n"])), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- driver

def run_cert(cr, files_by_node, validators, rows):
    nodes = []
    for n in validators:
        if not files_by_node.get(n):
            continue
        node = cr.Node(n)
        for p in files_by_node[n]:
            node.read(p)
        node.finish(None)
        nodes.append(node)
    if not nodes:
        return {}
    doc = cr.report(nodes, [(r["row_id"], r["from"], r["to"]) for r in rows], [])
    return dict((w[F["m_name"]], w[F["r_nodes"]]) for w in doc[F["r_windows"]])


def run_stages(sl, logs_dir, groups_dirs, manifest_path, rows, tmp):
    wins = [{F["m_name"]: r["row_id"], F["t_wstart"]: r["from"], F["t_wend"]: r["to"]} for r in rows if r["docs"]]
    if not wins:
        return {}
    wf, of = os.path.join(tmp, "windows.json"), os.path.join(tmp, "stages.json")
    with open(wf, "w") as fh:
        json.dump(wins, fh)
    argv = ["--logs", logs_dir, "--windows", wf, "--keep-boundaries", "--out-json", of]
    for d in groups_dirs:
        argv += ["--blasters", d]
    if manifest_path and os.path.isfile(manifest_path):
        argv += ["--manifest", manifest_path]
    if sl.main(argv) != 0 or not os.path.isfile(of):
        return {}
    doc = read_json(of)
    return dict((w, {"h": doc[F["t_headline"]].get(w) or {}, "p": doc[F["t_pooled"]].get(w) or {}})
                for w in doc[F["t_headline"]])


def summarize(a):
    run_dir = os.path.abspath(a.run_dir)
    run = os.path.basename(os.path.normpath(run_dir))
    manifest_path = os.path.join(run_dir, "manifest.json")
    manifest = read_json(manifest_path) if os.path.isfile(manifest_path) else {}
    run = manifest.get(F["m_run_id"]) or run
    notes = []
    list_name, evidence = run_switch_list(manifest)
    switches = switch_table(os.path.join(BENCH, "arms", list_name))
    arms = arm_list(manifest, switches)
    if not manifest.get(F["m_arms"]):
        notes.append("no param_arms[]: one implicit arm, %s, over the whole run (treated as a control)" % IMPLICIT_ARM)
    rows, skipped = build_rows(run_dir, manifest, arms, a.types)
    notes += ["not measured: %s" % s for s in skipped]
    if not rows:
        print("arms-summary: no row in %s" % run_dir, file=sys.stderr)
        return None, 2
    sl = load_tool(os.path.join(HERE, STAGE_LATENCY), "stage_latency_for_arms")
    cr = load_tool(os.path.join(HERE, CERT_RATE), "cert_rate_for_arms")
    lits = literals(sl, cr)
    logs_dir = os.path.join(run_dir, "logs")
    nodes = node_names(manifest, logs_dir)
    validators = [n for n in nodes if F["v_validator"] in n]
    prefiltered = a.prefiltered or os.path.join(BENCH, "work", "prefilter", run)
    why = prefilter_usable(prefiltered, lits)
    files_by_node = {}
    if why is None and all(sl.node_logs(prefiltered, n, None) for n in nodes):
        src_dir = prefiltered
        for n in nodes:
            files_by_node[n] = sl.node_logs(prefiltered, n, None)
        notes.append("logs: prefiltered %s" % prefiltered)
    else:
        src_dir = a.cache_dir or os.path.join(BENCH, "work", "arms-summary", run)
        os.makedirs(src_dir, exist_ok=True)
        jobs = []
        for n in nodes:
            for p in (sl.node_logs(logs_dir, n, None) if os.path.isdir(logs_dir) else []):
                base = os.path.basename(p)
                dst = os.path.join(src_dir, base if base.endswith(".gz") else base + ".gz")
                jobs.append((n, p, dst))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            futs = [(n, ex.submit(filter_one, p, dst, lits)) for n, p, dst in jobs]
            for n, fu in futs:
                files_by_node.setdefault(n, []).append(fu.result())
        notes.append("logs: %s streamed through a fixed-string filter into %s (%s)" % (
            logs_dir, src_dir, why or "prefiltered files incomplete"))
    windows = sorted((r["from"], r["to"]) for r in rows)
    nds = collections.OrderedDict()
    for n in nodes:
        if files_by_node.get(n):
            nd = NodeData(n, windows)
            for p in files_by_node[n]:
                nd.read(p, len(files_by_node[n]) > 1)
            nd.finish()
            nds[n] = nd
    missing_logs = [n for n in nodes if n not in nds]
    if missing_logs:
        notes.append("no log file for %s" % ", ".join(missing_logs))
    line_keys = sorted(set().union(*[nd.switch_keys for nd in nds.values()]))
    if evidence is None and line_keys:
        # param_arms[] records no switch state, so the keys the nodes logged tell the build; the arms are derived
        # again with that list (rows hold the same arm records)
        list_name, evidence = run_switch_list(manifest, line_keys)
        switches = switch_table(os.path.join(BENCH, "arms", list_name))
        for x, y in zip(arms, arm_list(manifest, switches)):
            x.update(y)
    if manifest.get(F["m_arms"]) and evidence != "manifest":    # a run without param_arms[] has no state to read
        notes.append(switch_list_note(list_name, evidence))
    cert_doc = run_cert(cr, files_by_node, validators, rows)
    groups = blast_groups(run_dir, manifest)
    stage_doc = {}
    if not a.no_stages:
        tmp = tempfile.mkdtemp(prefix="arms-stages-")
        try:
            stage_doc = run_stages(sl, src_dir, [g["dir"] for g in groups if g["docs"]], manifest_path, rows, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        notes.append("stages: skipped (--no-stages)")
    blocks = block_table([g["docs"] for g in groups])
    caps = disk_caps(manifest, a.disk_iops, a.disk_mibps)
    groups = node_groups(manifest, nodes)
    stores = measure(run_dir, manifest, rows, nds, validators, os.path.join(run_dir, "persist"), cert_doc, stage_doc,
                     blocks, a.drift_axis, caps, groups)
    drift = apply_drift(rows)
    apply_checks(rows)
    for x in arms:
        if switch_on(x, F["sw_sealed"]):
            notes.append("arm %s: %s on: pending_before and tn_batch_builder_pending_pool_transactions include the "
                         "in-flight sealed transactions; read them beside sealed_marked_peak" % (x["arm_name"], F["sw_sealed"]))
        if switch_on(x, F["sw_bound"]):
            notes.append("arm %s: %s on: judge landed tx/s together with admission_refused (else gen_pool_full), "
                         "gen_dropped and land p50 / p95 of what was admitted (D47)" % (x["arm_name"], F["sw_bound"]))
        if switch_on(x, F["sw_pipelined"]):
            notes.append("arm %s: %s on: task_ms runs from build start to commit, so compare commit_interval_ms with "
                         "commit_interval_ms, not task us/tx (D55); proc_written_bytes is an upper bound (D56)"
                         % (x["arm_name"], F["sw_pipelined"]))
    doc = collections.OrderedDict([
        ("tool", "arms-summary/v1"), ("run_name", run), ("generated_utc", iso(datetime.datetime.now(datetime.timezone.utc).timestamp())),
        ("drift_axis", a.drift_axis), ("notes", notes), ("drift", drift),
        ("arm_list", [collections.OrderedDict([("arm_name", x["arm_name"]), ("utc_from", None if x["from"] == float("-inf") else iso(x["from"])),
                                               ("utc_to", None if x["to"] == float("inf") else iso(x["to"])),
                                               ("roles", x["roles"]), ("control", x["control"]),
                                               ("switch_set", x["switch_set"])]) for x in arms]),
        ("summary_rows", [collections.OrderedDict([("row_id", r["row_id"]), ("arm_name", r["arm_rec"]["arm_name"]),
                                                   ("blast_type", r["blast_type"]), ("blast_idx", r["blast_idx"]),
                                                   ("utc_from", iso(r["from"])), ("utc_to", iso(r["to"])),
                                                   ("seconds", int(r["to"] - r["from"])), ("window_basis", r["basis"])]
                                                  + list(r["m"].items())) for r in rows]),
        ("log_files", dict((n, nd.files) for n, nd in nds.items())), ("disk_caps", caps)])
    if stores:
        doc["store_by_node"] = stores
    if any(c == F["v_lssd"] for c, _ in groups.values()):
        doc["disk_caps_by_node"] = collections.OrderedDict((n, node_caps(caps, groups, n)) for n in groups)
    return (doc, to_markdown(doc, rows, drift, a.drift_axis)), 0


def under(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def self_check(doc):
    """[(what, expected, got, ok)] against the I-3 recut and the bench-6-only columns."""
    out = []
    rows = dict((r["blast_type"], r) for r in doc["summary_rows"])
    for typ, a, b, txps in RECUT:
        r = rows.get(typ)
        if r is None:
            out.append(("%s row" % typ, "present", "absent", False))
            continue
        out.append(("%s window" % typ, "%s → %s" % (a, b), "%s → %s" % (r["utc_from"], r["utc_to"]),
                    (r["utc_from"], r["utc_to"]) == (a, b)))
        got = r["chain_txps"]
        out.append(("%s chain tx/s" % typ, txps, got, isinstance(got, float) and abs(got - txps) <= 0.05))
        for k in BENCH6_ONLY:
            out.append(("%s %s" % (typ, k), "n/a", r.get(k), is_na(r.get(k))))
    out.append(("row count", 2, len(doc["summary_rows"]), len(doc["summary_rows"]) == 2))
    return out


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.splitlines()[2:]))
    p.add_argument("--run-dir", help="results/<run>")
    p.add_argument("--self-check", action="store_true", help="run on bench 5 and compare with the I-3 recut")
    p.add_argument("--results-root", help="the results directory for --self-check (default benchmark/results)")
    p.add_argument("--out-dir", help="where arms.md and arms.json go (default <run-dir>/analysis)")
    p.add_argument("--prefiltered", help="the teardown's prefiltered logs (default benchmark/work/prefilter/<run>)")
    p.add_argument("--cache-dir", help="the filtered-log cache (default benchmark/work/arms-summary/<run>)")
    p.add_argument("--types", help="only these blast types, comma-separated (e.g. M16,L)")
    p.add_argument("--drift-axis", choices=("chain-mtx", "wall-min"), default="chain-mtx",
                   help="the drift coordinate: cumulative chain transactions in millions (default) or wall minutes")
    p.add_argument("--no-stages", action="store_true", help="skip the stage-latency pass")
    p.add_argument("--jobs", type=int, default=4, help="log files filtered at once (default 4)")
    p.add_argument("--disk-iops", type=float,
                   help="the boot disk's provisioned IOPS (default: manifest node_disk); never a local SSD's")
    p.add_argument("--disk-mibps", type=float,
                   help="the boot disk's provisioned MiB/s (default: manifest node_disk); never a local SSD's")
    a = p.parse_args(argv)
    for k in ("disk_iops", "disk_mibps"):
        if getattr(a, k) is not None and not getattr(a, k) > 0:
            p.error("--%s must be positive" % k.replace("_", "-"))
    if a.self_check:
        if a.run_dir:
            p.error("--self-check takes no --run-dir")
        a.run_dir = os.path.join(a.results_root or os.path.join(BENCH, "results"), SELF_CHECK_RUN)
        base = os.path.join(BENCH, "work", "bench6-scratch", "H7b", "self-check")
        a.out_dir = a.out_dir or base
        a.cache_dir = a.cache_dir or os.path.join(base, "logs")
        a.types = a.types or "M4,M16"
        results = os.path.dirname(os.path.abspath(a.run_dir))
        for d in (a.out_dir, a.cache_dir):
            if under(d, results):
                p.error("--self-check never writes under %s (%s)" % (results, d))
    elif not a.run_dir:
        p.error("give --run-dir or --self-check")
    if a.jobs < 1:
        p.error("--jobs must be positive")
    a.types = [t.strip() for t in a.types.split(",") if t.strip()] if a.types else None
    a.out_dir = a.out_dir or os.path.join(a.run_dir, "analysis")
    return a


def main(argv=None):
    a = parse_args(argv)
    if not os.path.isdir(a.run_dir):
        print("arms-summary: no run directory %s" % a.run_dir, file=sys.stderr)
        return 1
    try:
        res, rc = summarize(a)
    except (OSError, ValueError, KeyError) as e:
        print("arms-summary: %s" % e, file=sys.stderr)
        return 1
    if res is None:
        return rc
    doc, md = res
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "arms.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    with open(os.path.join(a.out_dir, "arms.md"), "w") as fh:
        fh.write(md + "\n")
    print("arms-summary: %d rows -> %s" % (len(doc["summary_rows"]), os.path.join(a.out_dir, "arms.{md,json}")))
    if a.self_check:
        checks = self_check(doc)
        for what, exp, got, ok in checks:
            print("%s  %s: expected %s, got %s" % ("ok  " if ok else "FAIL", what, exp, got))
        return 0 if all(c[3] for c in checks) else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
