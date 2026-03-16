"""Tests for plugin config schema validation."""

from velo.plugins.validation import validate_config


class TestValidateConfig:
    def test_empty_schema_accepts_anything(self):
        config, errors = validate_config({"foo": "bar"}, {}, "test")
        assert errors == []
        assert config == {"foo": "bar"}

    def test_required_field_present(self):
        schema = {"api_key": {"type": "string", "required": True}}
        config, errors = validate_config({"api_key": "abc"}, schema, "test")
        assert errors == []

    def test_required_field_missing(self):
        schema = {"api_key": {"type": "string", "required": True}}
        config, errors = validate_config({}, schema, "test")
        assert len(errors) == 1
        assert "api_key" in errors[0]

    def test_default_applied(self):
        schema = {"port": {"type": "integer", "default": 8080}}
        config, errors = validate_config({}, schema, "test")
        assert errors == []
        assert config["port"] == 8080

    def test_default_not_applied_when_present(self):
        schema = {"port": {"type": "integer", "default": 8080}}
        config, errors = validate_config({"port": 9090}, schema, "test")
        assert config["port"] == 9090

    def test_wrong_type_string(self):
        schema = {"count": {"type": "integer"}}
        config, errors = validate_config({"count": "not a number"}, schema, "test")
        assert len(errors) == 1
        assert "integer" in errors[0]

    def test_wrong_type_boolean(self):
        schema = {"enabled": {"type": "boolean"}}
        config, errors = validate_config({"enabled": "yes"}, schema, "test")
        assert len(errors) == 1

    def test_enum_valid(self):
        schema = {"mode": {"type": "string", "enum": ["fast", "slow"]}}
        config, errors = validate_config({"mode": "fast"}, schema, "test")
        assert errors == []

    def test_enum_invalid(self):
        schema = {"mode": {"type": "string", "enum": ["fast", "slow"]}}
        config, errors = validate_config({"mode": "medium"}, schema, "test")
        assert len(errors) == 1
        assert "fast" in errors[0]

    def test_unknown_fields_ignored(self):
        schema = {"known": {"type": "string"}}
        config, errors = validate_config({"known": "yes", "extra": 42}, schema, "test")
        assert errors == []
        assert config["extra"] == 42

    def test_no_config_no_required_fields(self):
        schema = {"opt": {"type": "string", "default": "hello"}}
        config, errors = validate_config({}, schema, "test")
        assert errors == []
        assert config["opt"] == "hello"

    def test_no_config_with_required_fields(self):
        schema = {"key": {"type": "string", "required": True}}
        config, errors = validate_config({}, schema, "test")
        assert len(errors) == 1

    def test_array_type(self):
        schema = {"tags": {"type": "array", "default": []}}
        config, errors = validate_config({"tags": ["a", "b"]}, schema, "test")
        assert errors == []

    def test_array_type_wrong(self):
        schema = {"tags": {"type": "array"}}
        config, errors = validate_config({"tags": "not-a-list"}, schema, "test")
        assert len(errors) == 1

    def test_bool_not_accepted_as_integer(self):
        schema = {"count": {"type": "integer"}}
        config, errors = validate_config({"count": True}, schema, "test")
        assert len(errors) == 1
        assert "boolean" in errors[0]
