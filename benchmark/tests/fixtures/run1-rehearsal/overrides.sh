# Sourced by the rehearsal's sandbox copy of benchmark-blast.sh just before its dispatch (the line
# `blast_run_begin`), after every function and setting of the real script is defined. It replaces only
# the leaves that reach something the sandbox cannot fake (the registry and secrets in preflight, the
# bench-obs VM and its forwards, the load VMs' disk relabels, the nodes' log-rate sessions); none of
# them writes a manifest key a reader of run 1 uses. Everything else runs as the real driver.
preflight() { echo ">>> preflight (rehearsal: image, bucket and secrets taken as present)"; }
bench_obs_require() { echo "    bench-obs (rehearsal): Prometheus answers through the fake curl"; }
assert_load_vm() { :; }
assert_load_vms() { :; }
log_rate_check() { echo "    LOG_RATE (rehearsal: not measured)"; }
