from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Literal

from docker_agent.config import Settings

ConfigurationGroupKey = Literal[
    "model_settings",
    "retrieval_settings",
    "runtime_settings",
]
ConfigurationValueKind = Literal["string", "integer", "number"]
ConfigurationRuleKind = Literal["less_equal", "not_all_zero"]


class ConfigurationSchemaError(ValueError):
    """Raised when Agent configuration values violate their schema."""


@dataclass(frozen=True, slots=True)
class ConfigurationFieldDescriptor:
    key: str
    settings_name: str
    label: str
    description: str
    kind: ConfigurationValueKind
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationGroupDescriptor:
    key: ConfigurationGroupKey
    label: str
    fields: tuple[ConfigurationFieldDescriptor, ...]


@dataclass(frozen=True, slots=True)
class ConfigurationRuleDescriptor:
    kind: ConfigurationRuleKind
    group: ConfigurationGroupKey
    fields: tuple[str, ...]
    target_field: str
    message: str


def validate_configuration_schema(
    *,
    schema: tuple[ConfigurationGroupDescriptor, ...],
    rules: tuple[ConfigurationRuleDescriptor, ...],
) -> None:
    group_keys = [group.key for group in schema]
    if len(set(group_keys)) != len(group_keys):
        raise ConfigurationSchemaError(
            "configuration schema contains duplicate groups"
        )

    field_keys_by_group: dict[str, set[str]] = {}
    for group in schema:
        field_keys = [field.key for field in group.fields]
        if len(set(field_keys)) != len(field_keys):
            raise ConfigurationSchemaError(
                f"{group.key} contains duplicate fields"
            )
        field_keys_by_group[group.key] = set(field_keys)

    for rule in rules:
        if rule.group not in field_keys_by_group:
            raise ConfigurationSchemaError(
                f"configuration rule references unknown group "
                f"{rule.group!r}"
            )

        field_keys = field_keys_by_group[rule.group]
        missing = [
            field
            for field in (*rule.fields, rule.target_field)
            if field not in field_keys
        ]
        if missing:
            raise ConfigurationSchemaError(
                "configuration rule references unknown fields: "
                + ", ".join(sorted(set(missing)))
            )

        if rule.kind == "less_equal" and len(rule.fields) != 2:
            raise ConfigurationSchemaError(
                "less_equal rule requires exactly two fields"
            )
        if rule.kind == "not_all_zero" and not rule.fields:
            raise ConfigurationSchemaError(
                "not_all_zero rule requires at least one field"
            )

def resolve_settings_from_schema(
    base: Settings,
    *,
    schema: tuple[ConfigurationGroupDescriptor, ...],
    rules: tuple[ConfigurationRuleDescriptor, ...],
    model_settings: dict[str, object],
    retrieval_settings: dict[str, object],
    runtime_settings: dict[str, object],
) -> Settings:
    """Validate schema-owned preferences and overlay them on base settings."""

    sources = {
        "model_settings": model_settings,
        "retrieval_settings": retrieval_settings,
        "runtime_settings": runtime_settings,
    }
    updates: dict[str, object] = {}

    schema_by_group = {group.key: group for group in schema}
    for group_key, source in sources.items():
        group = schema_by_group.get(group_key)
        if group is None:
            if source:
                raise ConfigurationSchemaError(
                    f"{group_key} is not supported by this Agent"
                )
            continue

        fields = {field.key: field for field in group.fields}
        unknown = sorted(set(source) - set(fields))
        if unknown:
            labels = ", ".join(unknown)
            raise ConfigurationSchemaError(
                f"{group_key} contains unsupported fields: {labels}"
            )

        for key, value in source.items():
            field = fields[key]
            updates[field.settings_name] = _parse_value(
                value,
                field=field,
                qualified_name=f"{group_key}.{key}",
            )

    resolved = base.model_copy(update=updates, deep=True)
    _validate_rules(
        resolved,
        schema=schema,
        rules=rules,
    )
    return resolved


def _parse_value(
    value: object,
    *,
    field: ConfigurationFieldDescriptor,
    qualified_name: str,
) -> object:
    if field.kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationSchemaError(
                f"{qualified_name} must be a non-empty string"
            )
        return value.strip()

    if field.kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigurationSchemaError(
                f"{qualified_name} must be an integer"
            )
        number: int | float = value
    else:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ConfigurationSchemaError(
                f"{qualified_name} must be a number"
            )
        number = float(value)

    if field.minimum is not None and number < field.minimum:
        qualifier = _minimum_message(field.minimum)
        raise ConfigurationSchemaError(
            f"{qualified_name} must be {qualifier}"
        )
    if field.maximum is not None and number > field.maximum:
        raise ConfigurationSchemaError(
            f"{qualified_name} must not exceed {field.maximum:g}"
        )
    return number


def _minimum_message(minimum: float) -> str:
    if minimum == 0:
        return "non-negative"
    if minimum > 0:
        return "positive"
    return f"at least {minimum:g}"


def _validate_rules(
    settings: Settings,
    *,
    schema: tuple[ConfigurationGroupDescriptor, ...],
    rules: tuple[ConfigurationRuleDescriptor, ...],
) -> None:
    fields = {
        (group.key, field.key): field
        for group in schema
        for field in group.fields
    }

    for rule in rules:
        descriptors = [
            fields[(rule.group, field_key)]
            for field_key in rule.fields
        ]
        values = [
            getattr(settings, descriptor.settings_name)
            for descriptor in descriptors
        ]

        if rule.kind == "less_equal":
            if len(values) != 2:
                raise ConfigurationSchemaError(
                    "less_equal rule requires exactly two fields"
                )
            if values[0] > values[1]:
                raise ConfigurationSchemaError(rule.message)
            continue

        if rule.kind == "not_all_zero":
            if all(float(value) == 0 for value in values):
                raise ConfigurationSchemaError(rule.message)
            continue

        raise ConfigurationSchemaError(
            f"unsupported configuration rule kind: {rule.kind}"
        )
