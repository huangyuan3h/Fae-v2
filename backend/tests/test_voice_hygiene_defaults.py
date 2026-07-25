"""Voice hygiene defaults — persona prompt must forbid voice-mode hazards.

Belt-and-suspenders: even if the speakable stripper is bypassed (e.g. an
upstream call site forgets to wire it), the system prompt itself asks the
model not to emit emoji / kaomoji / English laughs / sing-song cadence.
"""

from __future__ import annotations

from fae.memory.defaults import DEFAULT_PERSONA, PERSONA_PRESETS, persona_presets_payload


def test_default_persona_mentions_voice_constraints() -> None:
    lowered = DEFAULT_PERSONA.lower()
    for needle in ("emoji", "kaomoji", "lol", "sing", "markdown", "filler"):
        assert needle in lowered, f"DEFAULT_PERSONA must forbid {needle!r}"


def test_default_persona_is_a_single_string() -> None:
    # Construction-time sanity: make sure embedding the helper string did not
    # accidentally turn DEFAULT_PERSONA into a tuple / list.
    assert isinstance(DEFAULT_PERSONA, str)


def test_every_preset_carries_voice_rules() -> None:
    for preset in PERSONA_PRESETS:
        text = preset["text"].lower()
        assert "emoji" in text, f"preset {preset['id']} must forbid emoji"
        assert "lol" in text or "laugh" in text, (
            f"preset {preset['id']} must forbid fillers"
        )


def test_persona_presets_payload_includes_voice_rules() -> None:
    # Frontend Settings page reads through persona_presets_payload; the rules
    # must survive serialization so the user can see what each preset promises.
    payload = persona_presets_payload()
    assert len(payload) == len(PERSONA_PRESETS)
    for preset in payload:
        assert "emoji" in preset["text"].lower()
        assert "lol" in preset["text"].lower() or "laugh" in preset["text"].lower()


def test_default_persona_is_long_enough_to_influence_models() -> None:
    # Sanity floor: persona + voice rules combined should be a few sentences;
    # shorter would suggest a regression in a future refactor.
    assert len(DEFAULT_PERSONA) >= 400
