from __future__ import annotations

from jsonschema.exceptions import ValidationError

# Keywords whose schema-side value is safe and useful to show. The instance value never is:
# jsonschema's own messages embed the offending argument, which may be a secret.
_SHOW_SCHEMA_VALUE = frozenset(
    {
        "type",
        "enum",
        "const",
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "multipleOf",
    }
)


def describe_error(err: ValidationError) -> str:
    """Summarize a validation failure by location and keyword without echoing the argument value."""
    location = ".".join(str(p) for p in err.absolute_path) or "arguments"
    keyword = str(err.validator)
    if keyword == "required":
        missing = err.message.split("'")[1] if err.message.count("'") >= 2 else "a field"
        return f"{location}: missing required property '{missing}'"
    if keyword in {"additionalProperties", "unevaluatedProperties"}:
        return f"{location}: unexpected properties are not allowed"
    if keyword in _SHOW_SCHEMA_VALUE:
        return f"{location}: must satisfy {keyword}={err.validator_value!r}"
    return f"{location}: failed the '{keyword}' constraint"
