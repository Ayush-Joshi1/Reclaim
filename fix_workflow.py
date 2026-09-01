import json
from pathlib import Path

# Fix the workflow
workflow_path = Path('workflows/reclaim-recovery-orchestration.json')
workflow = json.loads(workflow_path.read_text(encoding='utf-8-sig'))

# Find and fix the HTTP node
for node in workflow['nodes']:
    if node.get('name') == 'Reclaim Recovery Evaluation' and node.get('type') == 'n8n-nodes-base.httpRequest':
        # Fix URL
        node['parameters']['url'] = '={{ $vars.RECLAIM_BACKEND_URL }}/api/workflows/recovery'
        # Fix secret
        for param in node['parameters']['headerParameters']['parameters']:
            if param['name'] == 'X-Reclaim-Workflow-Secret':
                param['value'] = '={{ $vars.RECLAIM_WORKFLOW_SECRET }}'
        print('Fixed HTTP node URL and secret')
        break

for node in workflow['nodes']:
    if node.get('name') == 'Prepare Recovery Payload' and node.get('type') == 'n8n-nodes-base.code':
        node['parameters']['jsCode'] = node['parameters']['jsCode'].replace(
            'RECLAIM_WORKFLOW_SECRET: "reclaim-demo-secret-2026"',
            'RECLAIM_WORKFLOW_SECRET: "={{ $vars.RECLAIM_WORKFLOW_SECRET }}"',
        )
        print('Removed literal workflow secret from payload preparation')
        break

# Write back
workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Verify
text = workflow_path.read_text(encoding='utf-8')
assert 'reclaim-demo-secret-2026' not in text, "Literal secret still in workflow!"
assert 'early-excellence-telephone-honey' not in text, "Hardcoded URL still in workflow!"
assert 'RECLAIM_WORKFLOW_SECRET' in text, "Missing RECLAIM_WORKFLOW_SECRET variable!"
assert 'RECLAIM_BACKEND_URL' in text, "Missing RECLAIM_BACKEND_URL variable!"
print('Verified: No literal secrets or URLs')
print('Verified: Environment variables in place')
