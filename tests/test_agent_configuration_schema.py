import pytest

from docker_agent.agent.configuration_schema import (
    ConfigurationFieldDescriptor,
    ConfigurationGroupDescriptor,
    ConfigurationRuleDescriptor,
    ConfigurationSchemaError,
    resolve_settings_from_schema,
    validate_configuration_schema,
)
from docker_agent.config import Settings


def _schema() -> tuple[
    tuple[ConfigurationGroupDescriptor, ...],
    tuple[ConfigurationRuleDescriptor, ...],
]:
    schema = (
        ConfigurationGroupDescriptor(
            key="model_settings",
            label="Model",
            fields=(
                ConfigurationFieldDescriptor(
                    key="temperature",
                    settings_name="model_temperature",
                    label="Temperature",
                    description="Sampling temperature.",
                    kind="number",
                    minimum=0,
                    maximum=2,
                ),
            ),
        ),
        ConfigurationGroupDescriptor(
            key="retrieval_settings",
            label="Retrieval",
            fields=(
                ConfigurationFieldDescriptor(
                    key="top_k",
                    settings_name="retrieval_candidate_k",
                    label="Top K",
                    description="Candidate count.",
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="rerank_top_k",
                    settings_name="rerank_top_k",
                    label="Rerank top K",
                    description="Reranked result count.",
                    kind="integer",
                    minimum=1,
                ),
                ConfigurationFieldDescriptor(
                    key="dense_weight",
                    settings_name="retrieval_dense_weight",
                    label="Dense weight",
                    description="Dense retrieval weight.",
                    kind="number",
                    minimum=0,
                ),
                ConfigurationFieldDescriptor(
                    key="keyword_weight",
                    settings_name="retrieval_keyword_weight",
                    label="Keyword weight",
                    description="Keyword retrieval weight.",
                    kind="number",
                    minimum=0,
                ),
            ),
        ),
    )
    rules = (
        ConfigurationRuleDescriptor(
            kind="less_equal",
            group="retrieval_settings",
            fields=("rerank_top_k", "top_k"),
            target_field="rerank_top_k",
            message="rerank_top_k must not exceed top_k",
        ),
        ConfigurationRuleDescriptor(
            kind="not_all_zero",
            group="retrieval_settings",
            fields=("dense_weight", "keyword_weight"),
            target_field="keyword_weight",
            message="retrieval weights cannot both be zero",
        ),
    )
    return schema, rules


def test_schema_maps_product_fields_to_settings_fields() -> None:
    schema, rules = _schema()

    resolved = resolve_settings_from_schema(
        Settings(),
        schema=schema,
        rules=rules,
        model_settings={"temperature": 0.4},
        retrieval_settings={
            "top_k": 12,
            "rerank_top_k": 4,
            "dense_weight": 1.5,
            "keyword_weight": 0.5,
        },
        runtime_settings={},
    )

    assert resolved.model_temperature == 0.4
    assert resolved.retrieval_candidate_k == 12
    assert resolved.rerank_top_k == 4
    assert resolved.retrieval_dense_weight == 1.5
    assert resolved.retrieval_keyword_weight == 0.5


def test_schema_rejects_fields_not_declared_by_agent() -> None:
    schema, rules = _schema()

    with pytest.raises(
        ConfigurationSchemaError,
        match="unsupported fields: token_budget",
    ):
        resolve_settings_from_schema(
            Settings(),
            schema=schema,
            rules=rules,
            model_settings={"token_budget": 12000},
            retrieval_settings={},
            runtime_settings={},
        )


def test_schema_rejects_nonempty_group_not_supported_by_agent() -> None:
    schema, rules = _schema()

    with pytest.raises(
        ConfigurationSchemaError,
        match="runtime_settings is not supported",
    ):
        resolve_settings_from_schema(
            Settings(),
            schema=schema,
            rules=rules,
            model_settings={},
            retrieval_settings={},
            runtime_settings={"max_steps": 4},
        )


def test_schema_enforces_field_bounds() -> None:
    schema, rules = _schema()

    with pytest.raises(
        ConfigurationSchemaError,
        match="model_settings.temperature must not exceed 2",
    ):
        resolve_settings_from_schema(
            Settings(),
            schema=schema,
            rules=rules,
            model_settings={"temperature": 2.5},
            retrieval_settings={},
            runtime_settings={},
        )


def test_schema_enforces_cross_field_rules() -> None:
    schema, rules = _schema()

    with pytest.raises(
        ConfigurationSchemaError,
        match="rerank_top_k must not exceed top_k",
    ):
        resolve_settings_from_schema(
            Settings(),
            schema=schema,
            rules=rules,
            model_settings={},
            retrieval_settings={
                "top_k": 3,
                "rerank_top_k": 5,
            },
            runtime_settings={},
        )

    with pytest.raises(
        ConfigurationSchemaError,
        match="retrieval weights cannot both be zero",
    ):
        resolve_settings_from_schema(
            Settings(),
            schema=schema,
            rules=rules,
            model_settings={},
            retrieval_settings={
                "dense_weight": 0,
                "keyword_weight": 0,
            },
            runtime_settings={},
        )



def test_schema_integrity_rejects_duplicate_groups() -> None:
    duplicate = ConfigurationGroupDescriptor(
        key="model_settings",
        label="Model",
        fields=(),
    )

    with pytest.raises(
        ConfigurationSchemaError,
        match="duplicate groups",
    ):
        validate_configuration_schema(
            schema=(duplicate, duplicate),
            rules=(),
        )


def test_schema_integrity_rejects_rules_for_unknown_fields() -> None:
    schema = (
        ConfigurationGroupDescriptor(
            key="model_settings",
            label="Model",
            fields=(
                ConfigurationFieldDescriptor(
                    key="temperature",
                    settings_name="model_temperature",
                    label="Temperature",
                    description="Sampling temperature.",
                    kind="number",
                    minimum=0,
                    maximum=2,
                ),
            ),
        ),
    )

    with pytest.raises(
        ConfigurationSchemaError,
        match="unknown fields: missing",
    ):
        validate_configuration_schema(
            schema=schema,
            rules=(
                ConfigurationRuleDescriptor(
                    kind="not_all_zero",
                    group="model_settings",
                    fields=("missing",),
                    target_field="temperature",
                    message="invalid",
                ),
            ),
        )
