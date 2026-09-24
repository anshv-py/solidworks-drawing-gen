# Windows SolidWorks worker - architecture

## Why a separate worker
- SolidWorks runs only on Windows, is licence-bound, single-user, stateful and
  can hang or crash. It must be isolated from the API process.
- The API (Linux) never makes COM calls.

## Job protocol (pull-based)
1. Worker `POST /api/worker/leases` (auth: worker token) → receives job id,
   `DrawingOps` JSON, signed URLs for the model file.
2. Worker heartbeats `POST /api/worker/leases/{id}/heartbeat` with progress.
3. On finish: uploads artifacts (`.SLDDRW`, `.pdf`, `.dwg`, `.dxf`, preview PNG,
   `op_log.json`), then `POST .../complete` with per-artifact sha256 and
   `generator: SOLIDWORKS <version>`.
4. On failure: `POST .../fail` with structured error (op id, member, HRESULT).
Pull-based leasing avoids exposing the Windows machine and works through NAT.

## Process model
- Supervisor (Windows service) → spawns worker process → worker owns one
  SolidWorks instance (`/b` background or visible for debugging).
- Dedicated STA thread; all COM calls marshalled to it.
- Per-op watchdog; on timeout the supervisor kills `SLDWORKS.exe` owned by
  this worker (by PID, never by name).
- Recycle SolidWorks after N jobs (memory growth) and after any COM fault.

## Target framework decision (deferred to worker milestone)
- .NET Framework 4.8: the most common target for SolidWorks add-ins/interop,
  interop assemblies ship with SolidWorks (`api\redist`).
- .NET 8 (Windows): modern runtime; out-of-process COM automation generally
  works but must be proven with the installed SolidWorks version.
Choose after a spike on the target machine; record the result here.

## Mock mode
`MockDrawingExecutor` implements the same interface, validates ops, writes a
clearly watermarked placeholder PDF/DXF and `generator: MOCK`. It is used in
CI and on Linux dev machines.
