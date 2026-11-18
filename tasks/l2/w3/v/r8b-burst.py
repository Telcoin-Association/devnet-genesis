#!/usr/bin/env python3
"""Row 8, second try: one client, persistent HTTPS connections, as fast as it can.
Usage: r8b-burst.py <host> <threads> <requests per thread>. Prints status counts per second."""
import http.client, json, sys, threading, time, collections
host, threads, per = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []})
lock = threading.Lock(); buckets = collections.defaultdict(collections.Counter); t0 = time.time()
def work():
    c = http.client.HTTPSConnection(host, timeout=10)
    for _ in range(per):
        try:
            c.request("POST", "/", body, {"Content-Type": "application/json"})
            r = c.getresponse(); r.read(); code = r.status
        except Exception as e:
            code = type(e).__name__
            try: c.close()
            except Exception: pass
            c = http.client.HTTPSConnection(host, timeout=10)
        with lock: buckets[int(time.time() - t0)][code] += 1
ts = [threading.Thread(target=work) for _ in range(threads)]
[t.start() for t in ts]; [t.join() for t in ts]
total = collections.Counter()
for s in sorted(buckets):
    print("second %2d: %s" % (s, dict(buckets[s]))); total.update(buckets[s])
print("total %s in %.2f s" % (dict(total), time.time() - t0))
