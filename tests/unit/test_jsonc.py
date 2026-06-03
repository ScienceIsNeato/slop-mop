"""Tests for the shared string-aware JSONC parser."""

from slopmop.utils.jsonc import loads_jsonc, strip_jsonc


class TestStripJsonc:
    def test_strips_line_comments(self):
        assert loads_jsonc('{"a": 1} // trailing\n') == {"a": 1}

    def test_strips_block_comments(self):
        assert loads_jsonc('{/* c */ "a": 1}') == {"a": 1}

    def test_strips_multiline_block_comments(self):
        assert loads_jsonc('{\n/* one\n two */\n"a": 1}') == {"a": 1}

    def test_strips_trailing_comma_in_object(self):
        assert loads_jsonc('{"a": 1,}') == {"a": 1}

    def test_strips_trailing_comma_in_array(self):
        assert loads_jsonc('{"a": [1, 2,]}') == {"a": [1, 2]}

    def test_strips_trailing_comma_with_whitespace_and_comment(self):
        assert loads_jsonc('{"a": 1, // note\n}') == {"a": 1}

    def test_preserves_slashes_inside_strings(self):
        # // and /* */ inside string values must NOT be treated as comments.
        cfg = loads_jsonc(
            '{"url": "http://example.com", "glob": "src/**", "p": "packages/*/dist"}'
        )
        assert cfg["url"] == "http://example.com"
        assert cfg["glob"] == "src/**"
        assert cfg["p"] == "packages/*/dist"

    def test_does_not_strip_comma_inside_string(self):
        assert loads_jsonc('{"a": "x, ]"}') == {"a": "x, ]"}

    def test_preserves_escaped_quote_in_string(self):
        assert loads_jsonc('{"a": "she said \\"hi\\""}') == {"a": 'she said "hi"'}

    def test_plain_json_is_unchanged(self):
        assert strip_jsonc('{"a": 1}') == '{"a": 1}'

    def test_glob_pair_does_not_swallow_keys_between_them(self):
        # Regression: a regex stripper would match from the /* in "src/**" to
        # the */ in "packages/*/dist" and eat the key between them.
        text = (
            '{\n  "include": ["src/**"],\n'
            '  "secret": "kept",\n'
            '  "exclude": ["packages/*/dist"]\n}'
        )
        assert loads_jsonc(text)["secret"] == "kept"
