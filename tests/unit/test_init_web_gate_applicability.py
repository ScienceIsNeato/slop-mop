"""Init/refit must enable web-only gates only when the repo has HTML.

The conflicting-metadata gate is cross-cutting (no language suffix), so it is
never pruned by the suffix-based language pass. Its enable/disable decision
rides entirely on its own ``is_applicable`` (>=1 committed HTML file), which
init consumes via ``_disable_non_applicable_by_applicability`` on every init
and re-init (refit refresh). These tests lock that wiring in.
"""

from __future__ import annotations

from pathlib import Path

from slopmop.cli.init import _disable_non_applicable_by_applicability
from slopmop.utils.generate_base_config import generate_base_config

GATE = "conflicting-metadata"


def _gate_cfg(config: dict) -> dict:
    return config["myopia"]["gates"][GATE]


def _config_after_init(project_root: Path) -> dict:
    # all_enabled mirrors init's everything-on starting point before the
    # applicability guard prunes what cannot run here.
    config = generate_base_config(all_enabled=True)
    _disable_non_applicable_by_applicability(config, project_root)
    return config


class TestConflictingMetadataInitDetection:
    def test_disabled_when_no_html(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("print('hi')\n")
        config = _config_after_init(tmp_path)
        assert _gate_cfg(config)["enabled"] is False

    def test_enabled_when_html_present(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(
            "<!doctype html><html><head>"
            '<link rel="canonical" href="https://x.test/">'
            "</head><body>hi</body></html>"
        )
        config = _config_after_init(tmp_path)
        assert _gate_cfg(config)["enabled"] is not False

    def test_reinit_flips_to_enabled_when_html_added(self, tmp_path: Path) -> None:
        # refit re-runs the guard, so adding HTML to a previously non-web repo
        # must flip the gate back on (and not stay stale-disabled)
        (tmp_path / "app.py").write_text("print('hi')\n")
        assert _config_after_init(tmp_path)["myopia"]["gates"][GATE]["enabled"] is False
        (tmp_path / "page.html").write_text("<html><body>x</body></html>")
        assert _gate_cfg(_config_after_init(tmp_path))["enabled"] is not False
