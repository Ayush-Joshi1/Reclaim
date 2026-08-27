# Workflows

Task 5B adds [`reclaim-recovery-orchestration.json`](reclaim-recovery-orchestration.json), an importable n8n Cloud workflow for authenticated recovery-event orchestration.

The workflow validates the incoming event, calls `POST /api/workflows/recovery`, routes on the backend's validated action, and returns a dry-run result. It does not retry, capture, refund, create payment links, send notifications, or independently evaluate policy. Setup and safe testing are documented in [`docs/n8n-recovery-workflow.md`](../docs/n8n-recovery-workflow.md).
