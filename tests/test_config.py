from pathlib import Path

import pytest

from raffle_listener.config import Config, load_config, missing_settings, require_settings

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_loads():
    cfg = load_config(ROOT / "config.example.toml")
    assert cfg.stream.channel == "<canal>"
    assert cfg.trigger.site_url.startswith("https://sitio.example/")


def test_unknown_key_is_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[stream]\nchanel = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="chanel"):
        load_config(p)


def test_discord_is_off_unless_configured():
    cfg = load_config(ROOT / "config.example.toml")
    assert cfg.output.discord_webhook == ""
    assert cfg.output.discord_message == "Contraseña del sorteo: "


def test_defaults_have_no_channel_or_site():
    cfg = Config()
    assert cfg.stream.channel == "" and cfg.trigger.site_url == "" and cfg.autojoin.page_url == ""


def test_example_placeholders_are_reported():
    cfg = load_config(ROOT / "config.example.toml")
    missing = " ".join(missing_settings(cfg))
    assert "[stream].channel" in missing and "[trigger].site_url" in missing
    with pytest.raises(SystemExit, match="Faltan valores"):
        require_settings(cfg)


def test_autojoin_needs_page_widget_and_join_path():
    cfg = load_config(ROOT / "config.example.toml")
    cfg.autojoin.enabled = True
    missing = " ".join(missing_settings(cfg))
    assert all(k in missing for k in ("[autojoin].page_url", "[autojoin].widget_text", "[autojoin].join_path"))
    assert [m.split(":")[0] for m in missing_settings(cfg, login=True)] == ["[autojoin].page_url"]


def test_filled_config_is_accepted(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[stream]\nchannel = "canal_ejemplo"\n[trigger]\nsite_url = "https://sorteos.test/api/estado"\n'
                 '[autojoin]\nenabled = true\npage_url = "https://sorteos.test/directo"\n'
                 'widget_text = "Sorteo de ejemplo"\njoin_path = "/api/sorteo/join"\n', encoding="utf-8")
    assert missing_settings(load_config(p)) == []


def test_site_url_can_be_disabled(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[stream]\nchannel = "canal_ejemplo"\n[trigger]\nsite_url = ""\n', encoding="utf-8")
    assert missing_settings(load_config(p)) == []
