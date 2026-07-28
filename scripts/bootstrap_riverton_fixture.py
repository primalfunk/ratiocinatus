"""Extract the canonical Phase 0.5 corpus source files from the archived work order."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

FIXTURE_ID = "ratiocinatus-proof-riverton-evening-access-v1"
CONTRACT = "0.1.0"
ROOT = Path("tests/fixtures/riverton_evening_access_v1")
WORK_ORDER = Path("docs/work_orders/phase_00_5.txt")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(relative: str, value) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def annotation(identifier, category, lines, description, status, evidence=()):
    return {
        "annotation_id": identifier,
        "category": category,
        "contract_version": CONTRACT,
        "description": description,
        "evidence_ids": list(evidence),
        "line_ids": list(lines),
        "status": status,
    }


def main() -> None:
    text = WORK_ORDER.read_text(encoding="utf-8")
    section = text.split("10. CANONICAL SCRIPT", 1)[1].split(
        "11. AUTHORIZED VARIANT DIRECTIONS", 1
    )[0]
    pattern = re.compile(
        r"^L(\d{3}) (MODERATOR|PARTICIPANT_A|PARTICIPANT_B):\s*\n"
        r"(.*?)(?=^L\d{3} |^Reference intent:|^[A-Z][A-Z ]+\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    lines = []
    rendered = []
    for match in pattern.finditer(section):
        identifier = f"L{match.group(1)}"
        spoken = " ".join(part.strip() for part in match.group(3).strip().splitlines())
        lines.append({
            "contract_version": CONTRACT,
            "line_id": identifier,
            "order": int(match.group(1)),
            "speaker_id": match.group(2),
            "text": spoken,
            "text_sha256": digest(spoken),
        })
        rendered.append(f"{identifier} {match.group(2)}:\n{spoken}\n")
    if len(lines) != 68:
        raise RuntimeError(f"expected 68 lines, extracted {len(lines)}")
    (ROOT / "script").mkdir(parents=True, exist_ok=True)
    (ROOT / "script" / "canonical_script.txt").write_text(
        "\n".join(rendered), encoding="utf-8", newline="\n"
    )
    write_json("script/line_definitions.json", {
        "fixture_id": FIXTURE_ID, "line_count": 68, "lines": lines,
        "script_version": "1.0.0",
    })
    write_json("script/participants.json", {
        "fixture_id": FIXTURE_ID,
        "participants": [
            {"contract_version": CONTRACT, "display_name": "Elena Ward", "fictional": True, "role": "Moderator", "speaker_id": "MODERATOR"},
            {"contract_version": CONTRACT, "display_name": "Mara Chen", "fictional": True, "role": "Supports the conditional pilot", "speaker_id": "PARTICIPANT_A"},
            {"contract_version": CONTRACT, "display_name": "Daniel Price", "fictional": True, "role": "Opposes authorization in its current form", "speaker_id": "PARTICIPANT_B"},
        ],
    })
    evidence = [
        ("E-01", "Current hours", ["The center closes at 8:00 p.m. Monday through Friday."]),
        ("E-02", "Turn-away log", ["Month 1: 36 arrivals.", "Month 2: 41 arrivals.", "Month 3: 39 arrivals.", "Month 4: 44 arrivals.", "Month 5: 38 arrivals.", "Month 6: 42 arrivals.", "These are arrivals, not unique individuals."]),
        ("E-03", "Pilot survey", ["120 voluntary respondents.", "74 would use the center after 8:00 p.m. at least once per week.", "28 might.", "18 would not.", "Distributed through the center email list and front desk."]),
        ("E-04", "Staffing estimate", ["Two additional staff members.", "One additional security shift.", "$3,600 per month."]),
        ("E-05", "Pilot grant", ["Six-month grant approved for up to $21,600.", "Restricted to additional staffing and security costs of a weekday two-hour extension."]),
        ("E-06", "Security availability", ["Current contractor confirms Monday through Thursday.", "Friday is not confirmed."]),
        ("E-07", "Pilot limit", ["Six-month weekday pilot.", "Closing extends from 8:00 p.m. to 10:00 p.m.", "Not midnight, overnight, or permanent."]),
        ("E-08", "Decision date", ["The board must decide before the grant acceptance deadline."]),
    ]
    write_json("script/evidence_packet.json", {
        "contract_version": CONTRACT,
        "fixture_id": FIXTURE_ID,
        "items": [
            {"contract_version": CONTRACT, "evidence_id": identifier, "fictional": True, "statements": statements, "title": title}
            for identifier, title, statements in evidence
        ],
        "limitations": [
            "The packet does not claim that the pilot will succeed.",
            "Respondents are not guaranteed unique future users.",
            "Friday coverage is not confirmed.",
            "All evidence and entities are fictional.",
        ],
    })
    write_json("manifests/fixture.json", {
        "contract_version": CONTRACT,
        "discourse_format": "moderated_civic_policy_forum",
        "family_name": "Riverton Evening Access Forum",
        "fixture_id": FIXTURE_ID,
        "line_count": 68,
        "speaker_count": 3,
        "variants": ["clean", "naturalized", "adversarial"],
        "version": "1.0.0",
    })
    write_json("generation/generation_policy.json", {
        "channels": 2, "contract_version": CONTRACT, "fixture_format_version": "1.0.0",
        "fixture_id": FIXTURE_ID, "frames_per_second": 30, "height": 1080,
        "regeneration_class": "configuration_equivalent", "sample_rate_hz": 48000,
        "seed": 20260726, "target_duration_seconds_max": 840,
        "target_duration_seconds_min": 480, "width": 1920,
    })
    write_json("generation/voice_policy.json", {
        "fixture_id": FIXTURE_ID,
        "model_file": "kokoro-v1.0.fp16.onnx",
        "model_sha256": "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
        "voices_file": "voices-v1.0.bin",
        "voices_sha256": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        "assignments": [
            {"cloned_voice": False, "contract_version": CONTRACT, "engine": "kokoro-onnx", "engine_version": "0.4.9", "intentional_imitation": False, "language": "en-us", "model": "hexgrad/Kokoro-82M-v1.0", "speaker_id": "MODERATOR", "speed": 0.96, "voice_id": "am_adam"},
            {"cloned_voice": False, "contract_version": CONTRACT, "engine": "kokoro-onnx", "engine_version": "0.4.9", "intentional_imitation": False, "language": "en-us", "model": "hexgrad/Kokoro-82M-v1.0", "speaker_id": "PARTICIPANT_A", "speed": 1.00, "voice_id": "af_bella"},
            {"cloned_voice": False, "contract_version": CONTRACT, "engine": "kokoro-onnx", "engine_version": "0.4.9", "intentional_imitation": False, "language": "en-us", "model": "hexgrad/Kokoro-82M-v1.0", "speaker_id": "PARTICIPANT_B", "speed": 0.94, "voice_id": "af_sarah"},
        ],
        "deterministic_seed": None,
        "reproducibility_note": "Kokoro/ONNX inference is configuration-equivalent; frozen waveform hashes are canonical.",
    })
    write_json("generation/visual_policy.json", {
        "assets": "programmatically generated geometric panels and Pillow-rendered text",
        "background_rgb": [18, 24, 38],
        "frames_per_second": 30,
        "height": 1080,
        "panels": [
            {"avatar": "circle", "color_rgb": [66, 153, 225], "speaker_id": "MODERATOR"},
            {"avatar": "triangle", "color_rgb": [72, 187, 120], "speaker_id": "PARTICIPANT_A"},
            {"avatar": "square", "color_rgb": [237, 137, 54], "speaker_id": "PARTICIPANT_B"},
        ],
        "prohibited": ["logical labels", "referee calls", "scores", "fallacy names", "proposition identifiers", "argument arrows"],
        "subtitle": "Controlled proof fixture",
        "title": "Riverton Evening Access Forum",
        "width": 1920,
    })
    write_json("generation/perturbation_policy.json", {
        "adversarial": [
            {"id": "P-01", "kind": "gain", "line_id": "L037", "gain_db": -10},
            {"id": "P-02", "kind": "broadband_noise", "line_id": "L053", "snr_db": 22},
            {"id": "P-03", "kind": "initial_clip", "line_id": "L058", "clip_milliseconds": 120},
            {"id": "P-04", "kind": "voice_similarity", "line_id": "L001", "speakers": ["PARTICIPANT_A", "PARTICIPANT_B"], "note": "two distinct female stock voices"},
            {"id": "P-05", "kind": "visual_mismatch", "line_id": "L050", "wrong_speaker": "PARTICIPANT_A", "duration_seconds": 0.8},
        ],
        "naturalized": {
            "hesitations": ["pause before L039", "synthetic breath before L063"],
            "off_highlight": {"line_id": "L056", "duration_seconds": 0.75},
            "overlaps": [{"id": "O-01", "lines": ["L020", "L021"], "seconds": 0.55}, {"id": "O-02", "lines": ["L040", "L041"], "seconds": 0.4}],
        },
        "adversarial_overlaps": [{"id": "O-01", "lines": ["L020", "L021"], "seconds": 1.1}, {"id": "O-02", "lines": ["L040", "L041"], "seconds": 0.85}, {"id": "I-01", "lines": ["L037", "L038"], "seconds": 0.22}],
    })
    references = {
        "discourse_acts.json": [
            annotation("DA-001", "discourse_act", ("L006",), "Direct question about access exclusion.", "intended"),
            annotation("DA-002", "discourse_act", ("L007",), "Responsive concession.", "intended"),
            annotation("DA-003", "discourse_act", ("L013",), "Related but nonresponsive answer.", "intended"),
            annotation("DA-004", "discourse_act", ("L037",), "Nonresponsive answer to consequence question.", "intended"),
            annotation("DA-005", "discourse_act", ("L058",), "Nonresponsive answer to operational question.", "intended"),
        ],
        "propositions.json": [
            annotation("PR-001", "proposition", ("L009", "L011"), "Late arrivals form a recurring pattern, not a unique-person count.", "intended", ("E-02",)),
            annotation("PR-002", "proposition", ("L026",), "The grant equals the six-month projected cost.", "intended", ("E-04", "E-05")),
            annotation("PR-003", "proposition", ("L032",), "Friday security remains unconfirmed.", "intended", ("E-06",)),
            annotation("PR-004", "proposition", ("L065",), "Support is conditional on required coverage.", "intended", ("E-06", "E-07")),
        ],
        "argument_graph.json": [
            annotation("AR-001", "argument_relation", ("L026", "L027", "L028"), "Projected-cost conclusion, qualification, and narrowed conclusion.", "intended", ("E-04", "E-05")),
            annotation("AR-002", "argument_relation", ("L048", "L049", "L051"), "Candidate invalid inference and challenge.", "candidate"),
            annotation("AR-003", "argument_relation", ("L032", "L033", "L035"), "Security objection and conditional response.", "intended", ("E-06",)),
        ],
        "obligations.json": [
            annotation("OB-001", "obligation", ("L012", "L014", "L015"), "Staffing answer obligation opens and is satisfied.", "intended", ("E-04",)),
            annotation("OB-002", "obligation", ("L036", "L037", "L038", "L039"), "Consequence question is eventually answered with uncertainty.", "intended", ("E-06",)),
            annotation("OB-003", "obligation", ("L056", "L057", "L058", "L059", "L060"), "Operational question is answered by acknowledging missing packet information.", "intended"),
        ],
        "candidate_calls.json": [
            annotation("CC-001", "candidate_call", ("L021", "L022"), "Weaker, contestable candidate misrepresentation.", "candidate"),
            annotation("CC-002", "candidate_call", ("L040", "L041", "L042", "L043"), "Stronger candidate misrepresentation followed by correction.", "candidate", ("E-07",)),
            annotation("CC-003", "candidate_call", ("L053", "L016", "L055"), "Explicit contradiction followed by correction.", "candidate", ("E-04",)),
            annotation("CC-004", "candidate_call", ("L048", "L049", "L051"), "Candidate affirmation of the consequent and timing defect.", "candidate"),
        ],
        "expected_non_calls.json": [
            annotation("NC-001", "expected_non_call", ("L045", "L046", "L047"), "No contradiction call for corrected and withdrawn numbers.", "expected"),
            annotation("NC-002", "expected_non_call", ("L060",), "No penalty for acknowledging unknown information.", "expected"),
            annotation("NC-003", "expected_non_call", ("L061", "L062", "L063"), "No forced concession from the ambiguous exchange.", "expected"),
            annotation("NC-004", "expected_non_call", ("L001", "L068"), "No factual-verification call about the fictional packet.", "expected"),
        ],
        "ambiguities.json": [
            annotation("AM-001", "ambiguity", ("L061", "L062", "L063"), "Whether L061 is a conditional concession remains ambiguous.", "ambiguous"),
            annotation("AM-002", "ambiguity", ("L034", "L035"), "Whether conditional authorization changes the proposal may remain unresolved.", "ambiguous"),
            annotation("AM-003", "ambiguity", ("L021", "L022"), "The weaker misrepresentation may remain below adjudication threshold.", "ambiguous"),
        ],
    }
    for filename, annotations in references.items():
        write_json(f"reference/{filename}", {
            "fixture_id": FIXTURE_ID,
            "hidden_reference": True,
            "ordinary_analysis_must_not_consume": True,
            "annotations": annotations,
        })
    components = [
        ("script", "Riverton script and evidence", "1.0.0", "Apache-2.0", "repository", True, True, "Fictional project-authored text distributed under Apache-2.0."),
        ("kokoro-runtime", "kokoro-onnx", "0.4.9", "MIT", "https://pypi.org/project/kokoro-onnx/0.4.9/", True, False, "Generation prerequisite only."),
        ("kokoro-model", "Kokoro-82M model and stock voices", "1.0", "Apache-2.0", "https://huggingface.co/hexgrad/Kokoro-82M", True, False, "Model and stock voice files are not bundled."),
        ("espeak-ng", "eSpeak NG via espeakng-loader", "1.52+", "GPL-3.0-or-later", "https://github.com/espeak-ng/espeak-ng", True, False, "Phonemizer prerequisite only."),
        ("ffmpeg", "FFmpeg", "2024-09-26-git-f43916e217", "GPL-3.0-or-later build", "https://ffmpeg.org/legal.html", True, False, "Generation executable is not bundled."),
        ("pillow", "Pillow", "12.1.0", "MIT-CMU", "https://github.com/python-pillow/Pillow/blob/main/LICENSE", True, False, "Visual-generation prerequisite only."),
        ("graphics", "Geometric graphic assets", "1.0.0", "Apache-2.0", "programmatically generated", True, True, "No third-party image assets; project-authored graphics use Apache-2.0."),
    ]
    write_json("manifests/license_manifest.json", {
        "components": [
            {"component_id": i, "contract_version": CONTRACT, "license": lic, "name": n, "notice": notice, "redistributed": redist, "required": req, "source": source, "version": version}
            for i, n, version, lic, source, req, redist, notice in components
        ],
        "contract_version": CONTRACT,
        "distribution_status": "redistributable_with_notices",
        "fixture_id": FIXTURE_ID,
        "no_cloned_voices": True,
        "no_third_party_media": True,
    })
    (ROOT / "README.md").write_text(
        "# Riverton Evening Access Forum\n\n"
        "Fixture ID: `ratiocinatus-proof-riverton-evening-access-v1`.\n\n"
        "This is an entirely fictional, programmatically generated three-speaker "
        "controlled proof corpus. The source media contains no analytical labels. "
        "Files under `reference/` are hidden evaluation material and must never be "
        "provided to ordinary analysis. See `manifests/license_manifest.json` and "
        "`NOTICE.md` before redistribution.\n",
        encoding="utf-8", newline="\n",
    )
    (ROOT / "NOTICE.md").write_text(
        "# Fixture notices\n\n"
        "The script, evidence, names, setting, and geometric graphics are fictional "
        "and project-authored. Speech was generated with kokoro-onnx 0.4.9 (MIT) "
        "and Kokoro-82M v1.0 stock voices (Apache-2.0); model files are not bundled. "
        "Media was assembled with a GPL-enabled FFmpeg build; FFmpeg is not bundled. "
        "Visuals were generated with Pillow (MIT-CMU); Pillow is not bundled. "
        "No voice cloning, real-person imitation, third-party music, footage, or "
        "photographic likeness is used.\n",
        encoding="utf-8", newline="\n",
    )
    print(f"bootstrapped {len(lines)} canonical lines at {ROOT}")


if __name__ == "__main__":
    main()

