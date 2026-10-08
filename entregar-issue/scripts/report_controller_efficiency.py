#!/usr/bin/env python3
"""Report controller efficiency KPIs from telemetry and the deterministic execution plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from controller_contract_runtime import validate_controller_context


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object: {path}')
    return value


def ratio(n: int | float, d: int | float) -> float:
    return round(float(n) / max(1.0, float(d)), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    context = load(Path(args.context))
    validate_controller_context(context)
    plan = load(Path(args.plan))
    metrics = context['metrics']
    stages = plan.get('execution_order', [])
    reusable = plan.get('reusable_stages', [])
    applicable = plan.get('applicable_skills', [])
    required_gates = plan.get('required_gates', [])
    payload = {
        'schema_version': 1,
        'contract_version': context['contract_version'],
        'controller_context_id': context['controller_context_id'],
        'controller_cycle': context['controller_cycle'],
        'raw_metrics': metrics,
        'kpis': {
            'planning_amplification': ratio(metrics['planning_runs'], context['controller_cycle']),
            'validation_amplification': ratio(metrics['focused_checks'] + metrics['full_suites'], len(required_gates)),
            'delegation_amplification': ratio(metrics['subskill_calls'], len(applicable)),
            'publication_amplification': ratio(metrics['material_commits'] + metrics['handoff_commits'], metrics['material_commits']),
            'reuse_ratio': ratio(len(reusable), len(stages)),
            'remote_collections_per_material_commit': ratio(metrics['remote_collections'], metrics['material_commits']),
        },
        'plan_counts': {
            'stages': len(stages),
            'reused_stages': len(reusable),
            'required_gates': len(required_gates),
            'applicable_skills': len(applicable),
        },
    }
    out=Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(out)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
