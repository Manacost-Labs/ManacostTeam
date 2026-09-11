# Research Report

Research ID: `RES-20260828T072709Z-6762A748`

As of 2026-08-28, use React 19.2 (the official page's newest listed patch is 19.2.7) with Next.js 16.3.3 Active LTS for a new production baseline. Next.js 16 officially aligns with React 19.2, and its upgrade guide tells manual upgraders to install the latest Next.js, React, and React DOM packages.

Before production, verify the concrete lockfile and build. Major constraints include Node.js 20.9+ and TypeScript 5.1+, Turbopack as the default bundler, and removal of synchronous request API access. The result is therefore ready with warnings rather than a claim that every existing dependency is compatible.
