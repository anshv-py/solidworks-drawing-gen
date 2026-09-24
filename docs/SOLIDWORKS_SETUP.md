# SolidWorks worker setup (planned - milestone 6)

Nothing in this repository has been executed against SolidWorks yet.

## Host requirements (to be validated on the target machine)
- Windows with a licensed SolidWorks installation (version to be fixed; API interop assemblies in
  `<install>\api\redist\`).
- Dedicated service account, interactive-session considerations for COM automation of a desktop
  application, no other SolidWorks users on the host.
- Outbound HTTPS to the API only (pull-based job leasing; no inbound ports).

## Before implementation
1. Verify every API member in `.claude/skills/solidworks-api-automation/references/api-verification.md`
   against the official help for the installed version.
2. Spike: .NET Framework 4.8 vs .NET 8 out-of-process COM with the installed version.
3. Decide view-orientation mapping (GeometryIR Z-up vs SolidWorks Y-up `*Front`).
4. Configure DWG/DXF export options explicitly per job.

Worker contract draft: `apps/solidworks-worker/README.md`.
