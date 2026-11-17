status: done
updated: 2026-11-17T20:35:14Z
completed sections:
- read: rules, contract 1/3.2/8/10/11/12/A-1/A-5/A-7, units Z2 + DG gates, facts gateway-binary 2/3/6, node-side 3, dg-core 2, ckpt-l2-E5; lib helpers; finalize _tn_probe/_ro/assert_* style
- design: one parallel probe per host (declare -f _pc_remote over tn_iap_ssh_stdin, key=value lines, __tn_probe_done sentinel, one retry on rc 255); JSON judged locally with python3 -I
- identity discriminator (decisive for node 5 too): tn_info .bls_public_key (rpc_ext.rs:133-134, lib.rs:19-33, base58 string) self vs public URL, plus tn_nodeMode
- consensus progress: tn_latestConsensusHeader .number (u64, types/src/primary/block.rs:52), two samples POSTCHECK_ROUND_GAP_SECS apart in the same probe
- wrote dg-l2/devnet-postcheck.sh (736 lines, new, untracked)
- gates: bash -n 0; shellcheck -x 0 (0 findings, new file); tasks/check-bash-portability.sh 0 (0 WARN, 0 ERROR)
- stub tests (scratch Z2/test.sh, test-remote.sh): healthy exit 0 64/64 ok; notready / rpcbind / identity / reach each exit 1 with exactly 1 FAIL (the expected line); noredirect (403/-32011) exit 0 64/64; --only bogus exit 2; unknown target exit 2; --no-public exit 0 37 lines, no public lines; target node4 exit 0 17 lines; --only gateway exit 0 15 lines, 5 hosts probed; real _pc_remote executed locally with fake ss/curl/sleep/setup-gateway.sh: sentinel + all keys, rc 0

## healthy stub run (full stdout)
```
POSTCHECK validator-1-devnet gateway-status ok installed=true active=true ready=true issues=0 mode=same-host (/ready 200 after 10s)
POSTCHECK validator-1-devnet gateway-listeners ok loopback only: 8655=[127.0.0.1:8655] 8656=[127.0.0.1:8656] 9655=[127.0.0.1:9655]
POSTCHECK validator-1-devnet gateway-metrics ok tn_worker_gateway_upstream_ready = 1 (1 series on 127.0.0.1:9655)
POSTCHECK validator-1-devnet rpc-bind ok port 8545 on 127.0.0.1:8545 (loopback only, same-host gateway)
POSTCHECK validator-1-devnet health-bind ok port 43174 on 127.0.0.1:43174 (loopback only, same-host gateway)
POSTCHECK validator-1-devnet public-chainid ok https://node1.devnet.telcoin.network eth_chainId=0x7e1d (32285)
POSTCHECK validator-1-devnet public-tls ok certificate for node1.devnet.telcoin.network verified by curl (CA chain and host name), GET /health HTTP 200
POSTCHECK validator-1-devnet public-ws ok WebSocket upgrade to wss://node1.devnet.telcoin.network refused: HTTP 405
POSTCHECK validator-1-devnet public-ready-any ok GET https://node1.devnet.telcoin.network/ready/any 200 {"ready":true,"submissions":true,"queries":true}
POSTCHECK validator-1-devnet public-identity ok answered by another node: tn_nodeMode Observer via node1.devnet.telcoin.network (own CvvActive); tn_info bls_public_key xgKcKhCnbe… (own Keyvalidat…) = the rpc node's key (query node)
POSTCHECK validator-1-devnet admission ok primary effective=Closed fallback=null connected=3 epoch=0; rpc node matched by BLS key (genesis/observers)
POSTCHECK validator-2-devnet gateway-status ok installed=true active=true ready=true issues=0 mode=same-host (/ready 200 after 10s)
POSTCHECK validator-2-devnet gateway-listeners ok loopback only: 8655=[127.0.0.1:8655] 8656=[127.0.0.1:8656] 9655=[127.0.0.1:9655]
POSTCHECK validator-2-devnet gateway-metrics ok tn_worker_gateway_upstream_ready = 1 (1 series on 127.0.0.1:9655)
POSTCHECK validator-2-devnet rpc-bind ok port 8545 on 127.0.0.1:8545 (loopback only, same-host gateway)
POSTCHECK validator-2-devnet health-bind ok port 43174 on 127.0.0.1:43174 (loopback only, same-host gateway)
POSTCHECK validator-2-devnet public-chainid ok https://node2.devnet.telcoin.network eth_chainId=0x7e1d (32285)
POSTCHECK validator-2-devnet public-tls ok certificate for node2.devnet.telcoin.network verified by curl (CA chain and host name), GET /health HTTP 200
POSTCHECK validator-2-devnet public-ws ok WebSocket upgrade to wss://node2.devnet.telcoin.network refused: HTTP 405
POSTCHECK validator-2-devnet public-ready-any ok GET https://node2.devnet.telcoin.network/ready/any 200 {"ready":true,"submissions":true,"queries":true}
POSTCHECK validator-2-devnet public-identity ok answered by another node: tn_nodeMode Observer via node2.devnet.telcoin.network (own CvvActive); tn_info bls_public_key xgKcKhCnbe… (own Keyvalidat…) = the rpc node's key (query node)
POSTCHECK validator-2-devnet admission ok primary effective=Closed fallback=null connected=3 epoch=0; rpc node matched by BLS key (genesis/observers)
POSTCHECK validator-3-devnet gateway-status ok installed=true active=true ready=true issues=0 mode=same-host (/ready 200 after 10s)
POSTCHECK validator-3-devnet gateway-listeners ok loopback only: 8655=[127.0.0.1:8655] 8656=[127.0.0.1:8656] 9655=[127.0.0.1:9655]
POSTCHECK validator-3-devnet gateway-metrics ok tn_worker_gateway_upstream_ready = 1 (1 series on 127.0.0.1:9655)
POSTCHECK validator-3-devnet rpc-bind ok port 8545 on 127.0.0.1:8545 (loopback only, same-host gateway)
POSTCHECK validator-3-devnet health-bind ok port 43174 on 127.0.0.1:43174 (loopback only, same-host gateway)
POSTCHECK validator-3-devnet public-chainid ok https://node3.devnet.telcoin.network eth_chainId=0x7e1d (32285)
POSTCHECK validator-3-devnet public-tls ok certificate for node3.devnet.telcoin.network verified by curl (CA chain and host name), GET /health HTTP 200
POSTCHECK validator-3-devnet public-ws ok WebSocket upgrade to wss://node3.devnet.telcoin.network refused: HTTP 405
POSTCHECK validator-3-devnet public-ready-any ok GET https://node3.devnet.telcoin.network/ready/any 200 {"ready":true,"submissions":true,"queries":true}
POSTCHECK validator-3-devnet public-identity ok answered by another node: tn_nodeMode Observer via node3.devnet.telcoin.network (own CvvActive); tn_info bls_public_key xgKcKhCnbe… (own Keyvalidat…) = the rpc node's key (query node)
POSTCHECK validator-3-devnet admission ok primary effective=Closed fallback=null connected=3 epoch=0; rpc node matched by BLS key (genesis/observers)
POSTCHECK validator-4-devnet rpc-bind ok port 8545 on 0.0.0.0:8545 (all interfaces, standalone gateway upstream)
POSTCHECK validator-4-devnet health-bind ok port 43174 on 0.0.0.0:43174 (all interfaces, standalone gateway upstream)
POSTCHECK validator-4-devnet upstream-from-gateway ok gateway-4-devnet -> 10.0.0.13:8545 eth_chainId=0x7e1d
POSTCHECK validator-4-devnet upstream-from-other ok validator-1-devnet -> 10.0.0.13:8545 got no answer in 3s (curl rc 28)
POSTCHECK validator-4-devnet gateway-meta ok GATEWAY_ALLOW_FROM=10.0.0.16 GATEWAY_UPSTREAM=10.0.0.16 (gateway internal IP 10.0.0.16)
POSTCHECK validator-4-devnet public-chainid ok https://node4.devnet.telcoin.network eth_chainId=0x7e1d (32285)
POSTCHECK validator-4-devnet public-tls ok certificate for node4.devnet.telcoin.network verified by curl (CA chain and host name), GET /health HTTP 200
POSTCHECK validator-4-devnet public-ws ok WebSocket upgrade to wss://node4.devnet.telcoin.network refused: HTTP 405
POSTCHECK validator-4-devnet public-ready-any ok GET https://node4.devnet.telcoin.network/ready/any 200 {"ready":true,"submissions":true,"queries":true}
POSTCHECK validator-4-devnet public-identity ok answered by another node: tn_nodeMode Observer via node4.devnet.telcoin.network (own CvvActive); tn_info bls_public_key xgKcKhCnbe… (own Keyvalidat…) = the rpc node's key (query node)
POSTCHECK validator-4-devnet admission ok primary effective=Closed fallback=null connected=3 epoch=0; rpc node matched by BLS key (genesis/observers)
POSTCHECK observer-5-devnet gateway-status ok installed=true active=true ready=true issues=0 mode=same-host (/ready 200 after 10s)
POSTCHECK observer-5-devnet gateway-listeners ok loopback only: 8655=[127.0.0.1:8655] 8656=[127.0.0.1:8656] 9655=[127.0.0.1:9655]
POSTCHECK observer-5-devnet gateway-metrics ok tn_worker_gateway_upstream_ready = 1 (1 series on 127.0.0.1:9655)
POSTCHECK observer-5-devnet rpc-bind ok port 8545 on 127.0.0.1:8545 (loopback only, same-host gateway)
POSTCHECK observer-5-devnet health-bind ok port 43174 on 127.0.0.1:43174 (loopback only, same-host gateway)
POSTCHECK observer-5-devnet public-chainid ok https://node5.devnet.telcoin.network eth_chainId=0x7e1d (32285)
POSTCHECK observer-5-devnet public-tls ok certificate for node5.devnet.telcoin.network verified by curl (CA chain and host name), GET /health HTTP 200
POSTCHECK observer-5-devnet public-ws ok WebSocket upgrade to wss://node5.devnet.telcoin.network refused: HTTP 405
POSTCHECK observer-5-devnet public-ready-any ok GET https://node5.devnet.telcoin.network/ready/any 200 {"ready":true,"submissions":true,"queries":true}
POSTCHECK observer-5-devnet public-identity ok answered by another node: tn_nodeMode Observer via node5.devnet.telcoin.network (own Observer); tn_info bls_public_key xgKcKhCnbe… (own Node5Keyob…) = the rpc node's key (query node)
POSTCHECK observer-5-devnet admission ok primary effective=Closed fallback=null connected=0 epoch=0; rpc node matched by BLS key (genesis/observers)
POSTCHECK rpc-6-devnet rpc-https ok https://rpc.devnet.telcoin.network eth_chainId=0x7e1d, certificate verified
POSTCHECK rpc-6-devnet rpc-wss ok WebSocket upgrade to wss://rpc.devnet.telcoin.network: HTTP 101
POSTCHECK rpc-6-devnet rpc-admission ok primary effective=Open fallback=null connected=4 epoch=0
POSTCHECK gateway-4-devnet gateway-status ok installed=true active=true ready=true issues=0 mode=standalone (/ready 200 after 10s)
POSTCHECK gateway-4-devnet gateway-listeners ok loopback only: 8655=[127.0.0.1:8655] 8656=[127.0.0.1:8656] 9655=[127.0.0.1:9655]
POSTCHECK gateway-4-devnet gateway-metrics ok tn_worker_gateway_upstream_ready = 1 (1 series on 127.0.0.1:9655)
POSTCHECK chain validators-active ok 4/4 genesis validators report CvvActive
POSTCHECK chain heads ok spread 0 <= 5 blocks (eth_blockNumber, sampled in parallel): node1=101 node2=101 node3=101 node4=101 node5=101 node6=101
POSTCHECK chain consensus-progress ok tn_latestConsensusHeader .number rose over 15s on every validator: node1=500->504 node2=500->504 node3=500->504 node4=500->504
```
