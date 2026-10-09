import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts" / "validate_delivery_obligations.py"
spec = importlib.util.spec_from_file_location("delivery_obligations", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def ready():
    return {"status":"aprovado-internamente-pendente-auditoria-independente",
            "material_head_sha":"abc",
            "obligations":[{"id":f"M0{i}","state":"passed"} for i in range(1,8)],
            "ci":{"state":"success","subject_sha":"abc"},
            "completion_gate":"READY",
            "checkpoint":{"work_item_fingerprint":"pr703","observed_head":"abc"}}

def test_ready():
    assert module.validate(ready()) == []

def test_pr703_partial_and_pending_ci_block():
    case = ready()
    for i in [0,2,4]:
        case["obligations"][i]["state"] = "pending"
    case["ci"]["state"] = "pending"
    errors = module.validate(case)
    assert len([x for x in errors if "open obligation" in x]) == 3
    assert any("DELIVERY-CI-002" in x for x in errors)

def test_stale_handoff_and_checkpoint_block():
    case = ready()
    case["completion_gate"] = "BLOCK"
    case["checkpoint"]["observed_head"] = "old"
    errors = module.validate(case)
    assert any("DELIVERY-HANDOFF-005" in x for x in errors)
    assert any("DELIVERY-REENTRY-003" in x for x in errors)

def test_blocker_requires_evidence():
    case = ready()
    case["status"] = "bloqueado-por-impedimento-real"
    assert any("DELIVERY-BLOCKER-004" in x for x in module.validate(case))
    case["blocker"] = {"operation":"checkout","failure":"DNS","evidence":"stderr","recovery":"connector-only"}
    assert module.validate(case) == []
