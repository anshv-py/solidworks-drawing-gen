# Redis

Reserved for the distributed job queue (RQ) and SSE fan-out in milestone 2+.
Milestone 1 uses the in-process `LocalProcessRunner` (thread pool + isolated
subprocess per analysis), so Redis is started by compose but not yet used.
