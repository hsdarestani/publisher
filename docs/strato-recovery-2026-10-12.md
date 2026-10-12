# STRATO publisher recovery — 2026-10-12

Target server: `82.165.187.14`

This is a non-secret deployment checkpoint for the new STRATO VPS.

Deployment checklist:
- [ ] Confirm SSH key-based GitHub Actions authentication.
- [ ] Verify first-boot deployment without deleting PostgreSQL Docker volumes.
- [ ] Verify the publisher HTTPS health endpoint.
- [ ] Restore store credentials and signing material before queuing any builds.
- [ ] Confirm offsite backups and resource isolation before hosting additional applications.

No store submissions or release jobs should be started by this checkpoint.
