# Load-generator OOM diagnosis - 23 October 2026

Read-only investigation; no load-generator or load-balancer changes were made.

## Confirmed Runtime Facts

- All 13 Robot Shop pods were Ready, but load pod
  `load-cfcc6fb84-hw4bg` had 127 restarts. Its last recorded termination was
  `OOMKilled`, exit 137, at `2026-10-23T06:19:58Z`.
- The container memory limit remained 256 Mi. Node memory usage was about 25%;
  this was not node-wide pressure. Voting and observability remained healthy.
- The local corrected script, ConfigMap, and mounted script matched exactly.
  The entrypoint did not replace the grouped-route script.
- Process RSS tracked its working set. Only seven file descriptors, two
  sockets and two threads were observed; connection/thread growth was not seen.
- Recent memory intervals varied: some OOM cycles were about 11-15 minutes,
  while one interval survived about 91 minutes. Initial five-minute readiness
  therefore did not establish sustained stability.

## Follow-Up Measurements

The cities endpoint returns a whole country array. The script then calls
`.json()` on that response before selecting just one city. The 25-country
selection includes a US response of 18,239,043 bytes; Brazil is 5,639,854 bytes
and India 4,779,586 bytes. City objects have seven fields, including Unicode
names, numeric coordinates and an integer UUID. These byte counts describe
measured response bodies, not a claim about compressed network transfer size.

An isolated workstation test used the exact pinned image, real Locust HTTP
client, corrected script, two accelerated users, 0.2 CPU and 256 MiB memory.
Both cases ran for 20 seconds with 16 grouped request entries, zero errors,
three history records and garbage collection enabled:

- An 84-byte cities response produced 2,873 requests and a 34,828,288-byte
  cgroup memory peak.
- A 15,120,000-byte array of unique city objects produced 528 requests and a
  152,150,016-byte peak, 4.37 times larger, without OOM from its fresh baseline.

Large JSON materialization is therefore a measured transient memory amplifier,
not merely a hypothesized statistics leak. The real US response is larger and
has richer objects; overlapping users and an elevated process baseline can
exceed the container limit. A representative seven-field regression fixture
and live soak were required before claiming the replacement fixes OOM; those
gates subsequently passed as recorded in `load-oom-fix.md`.

Earlier working hypotheses are corrected here:

- Lifetime statistics may accumulate slowly, but do not explain this measured
  large-response amplification. Periodic statistics resets are not the primary
  proposed fix.
- A raw `StatsError` test bypassed the real HTTP client and overstated an error
  cardinality problem. Locust 2.1 substitutes grouped names before normal HTTP
  error recording. That synthetic result is not evidence of a leak in the
  deployed grouped client. The recent all-200 sample also did not support an
  HTTP-error trigger.

All isolated diagnostic containers and their temporary network were removed.

## Fix and Validation

Stream the cities response through an incremental JSON parser and uniformly
sample one city without materializing the complete array. Preserve all
countries, URLs, payloads, waits and two-user concurrency. Count consumed bytes,
measure the entire stream duration, close the response on every path, and
record bounded failure messages. No new package, memory-limit increase,
additional replica or load balancer is required.

After any reviewed change, soak for at least three hours, approximately twice
the longest observed 91-minute interval. A further readiness check after
185 minutes of pod uptime exceeds twice that interval. Require unchanged restart count,
bounded memory, comparable request rate and continued purchase-counter growth.

An application load balancer cannot correct memory retained by a traffic
generator. Additional generator replicas would each have their own state.

The reviewed V3 implementation passed the representative two-client fixture
at the original CPU/memory limits, then the full three-hour live soak with
zero restarts, 340 healthy samples, 2,497 additional purchases, and comparable
traffic. An independent recheck after more than six hours found no kernel OOM
events. See `load-oom-fix.md` for identities, hashes, measurements, and the
superseded V2 performance result.
