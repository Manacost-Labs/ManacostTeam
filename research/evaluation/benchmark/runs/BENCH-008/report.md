# Research Report

Research ID: `RES-20260828T072709Z-38BF3F0A`

Rust cannot be called universally faster than Go for backend services. Different service workloads exercise serialization, database access, allocation, scheduling, networking, and application logic differently; implementation quality and configuration may dominate a language label.

A defensible decision requires equivalent candidate services on the same hardware and load, with throughput, latency distribution, memory, errors, toolchain versions, and configuration reported. Go's official documentation adds material counterevidence to simplistic rankings: representative PGO has produced 2-14% gains on its program set, and microbenchmarks are usually poor guides to whole-program production behavior. This result is ready with warnings because no target service was measured.
