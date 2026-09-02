from __future__ import annotations
import json
from pathlib import Path
from typing import Any
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

def validate_recruiter_package(root: Path) -> dict[str, Any]:
    cfg=json.loads((root/'config/recruiter/package.json').read_text())
    findings=[]
    readme=(root/'README.md').read_text(encoding='utf-8')
    if '0.86.0' not in readme:
        findings.append('root README is not current for release 0.86.0')
    for section in cfg['required_readme_sections']:
        if f'## {section}' not in readme: findings.append(f'README missing section: {section}')
    for rel in cfg['required_documents']:
        p=root/rel
        if not p.exists() or p.stat().st_size==0: findings.append(f'missing recruiter document: {rel}')
    captures=[]
    for item in cfg['screenshots']:
        img=root/item['path']; meta_path=root/item['metadata']
        if not img.exists() or img.read_bytes()[:8] != PNG_SIGNATURE:
            findings.append(f'missing/invalid PNG capture: {item["path"]}'); continue
        if not meta_path.exists(): findings.append(f'missing capture metadata: {item["metadata"]}'); continue
        meta=json.loads(meta_path.read_text())
        if meta.get('capture_kind')!='source_derived_static_capture': findings.append(f'capture not truthfully classified: {item["path"]}')
        if meta.get('live_runtime_screenshot') is not False: findings.append(f'static capture incorrectly claims live runtime: {item["path"]}')
        sources=meta.get('derived_from',[])
        if not sources or any(not (root/s).exists() for s in sources): findings.append(f'capture source evidence missing: {item["path"]}')
        captures.append(item['path'])
    for rel in ('docs/architecture/topology.mmd','docs/architecture/data-flow.mmd'):
        if rel not in readme: findings.append(f'README does not link canonical diagram: {rel}')
    resume_evidence=root/'evals/reports/resume-interview-evidence.json'
    if not resume_evidence.exists() or json.loads(resume_evidence.read_text()).get('gate')!='pass': findings.append('measured-evidence gate not passing')
    return {'release':'0.86.0','gate':'pass' if not findings else 'fail','readme_sections':len(cfg['required_readme_sections']),'documents':len(cfg['required_documents']),'screenshots':len(captures),'findings':findings}
