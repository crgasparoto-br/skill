"""Pure contract for planning M2 ruleset migration without remote mutations."""

from __future__ import annotations

import copy
import re

APP_ID = 15368
LEGACY = "Verify independent audit (exact SHA)"
SESSION = "Verify session review (exact SHA)"
REQUIRED = {
    "develop": (
        "Structure and tests",
        "Offline authorization tests",
        "collect / Require certified semantic handoff (exact SHA)",
        SESSION,
    ),
    "main": (
        "Structure and tests",
        "Offline authorization tests",
        "collect / Require certified semantic handoff (exact SHA)",
        SESSION,
    ),
}


def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)



def _matches_ref(pattern: str, ref: str, default_ref: str) -> bool:
    """Match GitHub FNM_PATHNAME branch patterns; reject ambiguous syntax."""
    if pattern == "~ALL":
        return True
    if pattern == "~DEFAULT_BRANCH":
        return ref == default_ref
    require(isinstance(pattern, str) and "\\" not in pattern
            and not any(ch in pattern for ch in "[]{}"),
            "unsupported GitHub ruleset ref pattern; read-back cannot prove applicability")
    parts = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.fullmatch("".join(parts), ref) is not None


def ruleset_applies_to_branch(ruleset: dict, branch: str, default_branch: str) -> bool:
    """Conservatively identify every active ruleset capable of affecting a branch."""
    target = ruleset.get("target")
    if target == "push":
        # Push rulesets are repository-wide: there are no branch selectors.
        return True
    if target == "tag":
        return False
    require(target == "branch", "unknown ruleset target")
    ref = f"refs/heads/{branch}"
    default_ref = f"refs/heads/{default_branch}"
    ref_name = (ruleset.get("conditions") or {}).get("ref_name")
    require(isinstance(ref_name, dict), "active ruleset ref conditions unavailable")
    include = ref_name.get("include")
    exclude = ref_name.get("exclude")
    require(isinstance(include, list) and isinstance(exclude, list),
            "active ruleset ref conditions malformed")
    require(all(isinstance(item, str) for item in include + exclude),
            "active ruleset ref pattern malformed")
    return (any(_matches_ref(pattern, ref, default_ref) for pattern in include)
            and not any(_matches_ref(pattern, ref, default_ref) for pattern in exclude))

def exactly_one(rules: list[dict], kind: str) -> dict:
    found = [r for r in rules if r.get("type") == kind]
    require(len(found) == 1, f"exactly one {kind} rule is required")
    return found[0]


def plan_m2(current: dict, branch: str, ruleset_id: int) -> dict:
    """Produce an administrative proposal, refusing hidden or weaker rules."""
    require(branch in REQUIRED, "unsupported protected branch")
    require(current.get("id") == ruleset_id and current.get("target") == "branch",
            "ruleset identity mismatch")
    require(current.get("enforcement") in {"active", "disabled"},
            "unknown ruleset enforcement")
    require(current.get("conditions", {}).get("ref_name") == {
        "include": [f"refs/heads/{branch}"], "exclude": []},
        "ruleset does not target only the requested branch")
    require(isinstance(current.get("bypass_actors"), list),
            "bypass actors are not visible: authenticated admin read required")
    require(current["bypass_actors"] == [],
            "nonempty bypass actors require administrative exception review")
    original = current.get("rules")
    require(isinstance(original, list), "ruleset rules unavailable")
    rules = copy.deepcopy(original)
    exactly_one(rules, "deletion")
    exactly_one(rules, "non_fast_forward")
    approvals = exactly_one(rules, "pull_request").get("parameters")
    require(isinstance(approvals, dict), "PR protection parameters unavailable")
    old_count = approvals.get("required_approving_review_count")
    require(type(old_count) is int and 0 <= old_count <= 10, "invalid previous review count")
    require(isinstance(approvals.get("required_reviewers"), list),
            "required team reviewer inventory unavailable")
    require(approvals["required_reviewers"] == [],
            "required team reviewers still configured")
    require(approvals.get("require_code_owner_review") is False,
            "code-owner review requirement must be evaluated separately")
    require(approvals.get("require_last_push_approval") is False,
            "last-push review requirement must be evaluated separately")
    approvals["required_approving_review_count"] = 0

    statuses = exactly_one(rules, "required_status_checks").get("parameters")
    require(isinstance(statuses, dict) and statuses.get("strict_required_status_checks_policy") is True,
            "strict required checks missing")
    require(statuses.get("do_not_enforce_on_create") is False,
            "required checks must apply to branch creation")
    checks = statuses.get("required_status_checks")
    require(isinstance(checks, list), "required check inventory missing")
    indexed = {}
    for item in checks:
        require(isinstance(item, dict) and isinstance(item.get("context"), str),
                "malformed required check")
        name = item["context"]
        require(name not in indexed, f"duplicate required check: {name}")
        indexed[name] = copy.deepcopy(item)
    for name in REQUIRED[branch]:
        if name in indexed:
            require(indexed[name].get("integration_id") == APP_ID,
                    f"unexpected app origin for {name}")
        else:
            indexed[name] = {"context": name, "integration_id": APP_ID}
    require("Structure and tests" in indexed, "technical check was lost")
    if LEGACY in indexed:
        require(indexed[LEGACY].get("integration_id") == APP_ID,
                "legacy check has unexpected app origin")
        indexed.pop(LEGACY)
    else:
        require(old_count == 0 and SESSION in indexed,
                "legacy audit gate absent before migration")
    statuses["required_status_checks"] = list(indexed.values())
    planned = {
        "name": current["name"], "target": "branch", "enforcement": "active",
        "conditions": copy.deepcopy(current["conditions"]),
        "bypass_actors": copy.deepcopy(current["bypass_actors"]),
        "rules": rules,
    }
    original_unrelated = [r for r in original
                          if r.get("type") not in {"pull_request", "required_status_checks"}]
    proposed_unrelated = [r for r in rules
                          if r.get("type") not in {"pull_request", "required_status_checks"}]
    require(original_unrelated == proposed_unrelated, "unrelated rules changed")
    return planned
