# Security checklist

- [ ] Upload: extension allowlist, content sniffing, max size enforced while streaming (not after)
- [ ] Storage: UUID names, root-confined paths, no user-controlled paths, 0600/0700 perms
- [ ] Parsing: subprocess, timeout, memory limit, no shell=True, argument list only
- [ ] Jobs: per-job working directory, deleted/retained by policy
- [ ] Secrets: env / secret store only; `.env` in .gitignore; `.env.example` has placeholders
- [ ] Logging: no file contents, no tokens, filenames sanitized
- [ ] API: Pydantic validation on all inputs; CORS allowlist from config
- [ ] Worker: authenticated with a scoped token; pull-based (no inbound ports)
- [ ] Dependencies: licences reviewed (docs/THIRD_PARTY.md), pinned via lockfiles
