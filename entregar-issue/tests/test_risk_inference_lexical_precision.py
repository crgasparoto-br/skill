from risk_inference import derive_families_from_text, requires_quantitative_evidence


def test_css_custom_properties_do_not_trigger_quantitative_evidence() -> None:
    source = "CSS custom properties publish semantic values from one canonical source."
    assert requires_quantitative_evidence([source]) is False


def test_real_cost_requirement_still_triggers_quantitative_evidence() -> None:
    assert requires_quantitative_evidence(["O custo médio deve permanecer abaixo do limite."]) is True


def test_competing_semantic_values_do_not_imply_transaction_concurrency() -> None:
    families = derive_families_from_text(
        "Não manter valores semânticos concorrentes em uma segunda fonte canônica."
    )
    assert "concurrency-atomicity" not in families
    assert "structural-contract" in families


def test_concurrent_requests_still_imply_concurrency() -> None:
    families = derive_families_from_text(
        "Duas requisições concorrentes devem permanecer serializadas."
    )
    assert "concurrency-atomicity" in families
