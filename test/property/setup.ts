import fc from 'fast-check';

// Deterministic by default so CI failures reproduce locally; override with FC_SEED / FC_RUNS to explore.
const seed = process.env.FC_SEED !== undefined ? Number(process.env.FC_SEED) : 20260904;
fc.configureGlobal({ seed, numRuns: Number(process.env.FC_RUNS ?? 100) });
