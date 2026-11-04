#!/usr/bin/env python3
"""Reusable performance policy vocabulary, separate from large risk inference.

Avoid interpreting examples about the classifier's own controls as a request for
live performance measurements. The real production benchmark signals remain.
"""
from __future__ import annotations

import re

# A Git SHA "baseline" or a visual "candidate" is not a performance benchmark.
# Keep literal benchmark/production-path wording, or require a real performance
# metric when those otherwise generic comparison terms are used.
PERFORMANCE_BENCHMARK_RE = re.compile(
    r"\b(benchmark|mesmo caminho produtivo|same productive path|production path|caminho produtivo|entrypoint produtivo|production entrypoint)\b",
    re.IGNORECASE,
)
PERFORMANCE_COMPARISON_RE = re.compile(
    r"\b(before/after|antes/depois|baseline|candidate|candidato)\b",
    re.IGNORECASE,
)
PERFORMANCE_METRIC_RE = re.compile(
    r"\b(lat[eê]ncia|latency|p50|p90|p95|p99|percentil|percentile|throughput|tempo de execu[cç][aã]o|execution time|tempo m[eé]dio|average time|dura[cç][aã]o|duration|desempenho|performance|\d+(?:[.,]\d+)?\s*ms)\b",
    re.IGNORECASE,
)

PERFORMANCE_POLICY_ID_RE = re.compile(
    r"\b(?:requires_benchmark_path_fidelity|PERFORMANCE_BENCHMARK_RE|"
    r"performance_contract|benchmark-path-fidelity)\b", re.IGNORECASE,
)
PERFORMANCE_POLICY_FRAME_RE = re.compile(
    r"\b(?:classificador|classifier|classifica[cç][aã]o|inference|infer[eê]ncia|"
    r"gerador|validador|validator|requisitos? efetiv[oa]s?|restringir|preservar|"
    r"sinais?|impr[oó]prios?|artificial|n[aã]o criar|apesar de n[aã]o haver)\b",
    re.IGNORECASE,
)
PERFORMANCE_POLICY_TEST_RE = re.compile(
    r"^(?:controle positivo|positive control|(?:adicionar|add|escrever|write)\s+"
    r"testes?\s+(?:positivos|negativos))\b", re.IGNORECASE,
)


def is_performance_policy_meta(text: str) -> bool:
    """Risk taxonomy examples are not a request to execute a product benchmark.

    The exception requires an explicit self-referential classifier identifier
    with policy framing, or a literal positive/negative *test* example. A real
    performance mandate still triggers every quantitative and path-fidelity gate.
    """
    text = text.strip()
    return bool(
        PERFORMANCE_POLICY_TEST_RE.search(text)
        or (PERFORMANCE_POLICY_ID_RE.search(text)
            and PERFORMANCE_POLICY_FRAME_RE.search(text))
    )
