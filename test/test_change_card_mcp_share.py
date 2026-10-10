"""The ``mcp.share`` change card: one press shares a server, through the switch's path."""

from __future__ import annotations

import pytest

from kiro_crew import change_card_catalog as catalog


def _snap(**over):
    base = {"exists": True, "can_share": True, "shared": False, "share_blocked": None}
    base.update(over)
    return base


def _preview(params, snapshot):
    p = catalog.validate_params(catalog.KIND_MCP_SHARE, params)
    return catalog.build_preview(catalog.KIND_MCP_SHARE, p, snapshot, {})


def test_the_kind_is_listed_for_the_guide():
    kinds = {k["id"]: k for k in catalog.list_kinds()}
    assert "mcp.share" in kinds
    assert set(kinds["mcp.share"]["params_schema"]["required"]) == {"server", "shared"}


def test_one_press_goes_through_the_same_endpoint_the_switch_uses():
    preview = _preview({"server": "slack-mcp", "shared": True}, _snap())

    assert preview["apply"] == [
        {
            "method": "POST",
            "path": "/api/mcp-gateway/servers/stub",
            "body": {"name": "slack-mcp", "stub": True},
        }
    ]
    assert ("POST", "/api/mcp-gateway/servers/stub") in catalog.HOOKED_ROUTES
    assert preview["changes"][0] == {
        "label": "slack-mcp",
        "before": "One per chat",
        "after": "Shared",
    }


@pytest.mark.parametrize(
    ("code", "line"),
    [
        ("credential_vending", "Can't share: gives each chat its own credentials"),
        ("needs_tenant_nonce", "Can't share: each chat needs its own copy"),
        ("computer_use", "Can't share: it controls this computer"),
    ],
)
def test_each_leakage_class_is_refused_with_one_line(code, line):
    with pytest.raises(catalog.CardCatalogError) as exc:
        _preview({"server": "creds-agent", "shared": True}, _snap(share_blocked=code))

    assert exc.value.code == "share_refused"
    assert str(exc.value) == line


def test_turning_a_refused_class_off_is_allowed():
    preview = _preview(
        {"server": "creds-agent", "shared": False},
        _snap(shared=True, share_blocked="credential_vending"),
    )
    assert preview["apply"][0]["body"] == {"name": "creds-agent", "stub": False}


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (_snap(exists=False), "not_found"),
        (_snap(can_share=False), "not_shareable"),
        (_snap(shared=True), "no_change"),
    ],
)
def test_a_card_that_changes_nothing_is_refused(snapshot, code):
    with pytest.raises(catalog.CardCatalogError) as exc:
        _preview({"server": "slack-mcp", "shared": True}, snapshot)
    assert exc.value.code == code


def test_the_saving_row_is_the_measured_number():
    preview = _preview({"server": "slack-mcp", "shared": True}, _snap(saves_bytes=240_000_000))

    assert {"label": "Saves", "after": "240 MB"} in preview["changes"]


def test_no_saving_row_without_a_measurement():
    preview = _preview({"server": "slack-mcp", "shared": True}, _snap())

    assert all(row["label"] != "Saves" for row in preview["changes"])


def test_undo_restores_the_state_before_the_press():
    p = catalog.validate_params(catalog.KIND_MCP_SHARE, {"server": "slack-mcp", "shared": True})
    plan, reason = catalog.build_undo(catalog.KIND_MCP_SHARE, p, {"shared": False}, [{}], 1)

    assert reason is None
    assert plan == [
        {
            "method": "POST",
            "path": "/api/mcp-gateway/servers/stub",
            "body": {"name": "slack-mcp", "stub": False},
        }
    ]


def test_the_manual_toggle_is_remembered_by_name_only():
    line = catalog.describe_manual_change(
        ("POST", "/api/mcp-gateway/servers/stub"), {}, {"name": "slack-mcp", "stub": True}
    )
    assert line == "shared MCP server slack-mcp across chats"


def test_params_are_validated():
    with pytest.raises(catalog.CardCatalogError):
        catalog.validate_params(catalog.KIND_MCP_SHARE, {"server": "slack-mcp"})
    with pytest.raises(catalog.CardCatalogError):
        catalog.validate_params(
            catalog.KIND_MCP_SHARE, {"server": "slack-mcp", "shared": True, "extra": 1}
        )


def test_the_snapshot_reads_the_same_sources_as_the_page(monkeypatch):
    from kiro_crew.dashboard import change_cards
    from kiro_crew.dashboard.handlers import mcp as mcp_mod
    from kiro_crew.mcp_gateway import direct_copies

    monkeypatch.setattr(
        mcp_mod,
        "_collect_server_rows",
        lambda: {"slack-mcp": {"transport": "stdio", "commands": {("/opt/slack",)}}},
    )
    monkeypatch.setattr(
        direct_copies,
        "measure",
        lambda commands: {"slack-mcp": direct_copies.DirectCopies(2, 200_000_000)},
    )

    snap = change_cards._mcp_share_snapshot("slack-mcp")

    assert snap["exists"] and snap["can_share"]
    assert snap["share_blocked"] is None
    assert snap["saves_bytes"] == 100_000_000
    assert change_cards._mcp_share_snapshot("missing-mcp") == {"exists": False}
