"""Aspen Plus V14 automation facts observed from a live model, not guessed.

Every constant here was read back from `NH3_H2_SOFC_ICE_ORC_v3_ClosedORC_Working.bkp`
running under Aspen Plus 40.0 OLE Services on 2026-09-04, and each is covered by
the round-trip check in `scripts/` that produced it.

The decisive finding is that **COM cannot create flowsheet blocks**. Every form
of `Blocks.Elements.Add(...)` returns "Invalid Block/Model/Library Specification",
so a case generator cannot assemble a flowsheet through the object model. What it
can do is emit Aspen input language: `Document.Export(4, path)` writes a complete
`.inp`, `Document.InitFromFile2(path)` reads one back, and the imported model runs
and saves as `.bkp` normally. A 533-case sweep is therefore text generation plus a
run, not COM flowsheet surgery.
"""

from __future__ import annotations

from typing import Final

PROGID: Final = "Apwn.Document.40.0"

#: Aspen fails on non-ASCII paths, and this project lives under a Korean directory.
ASCII_WORKDIR: Final = r"C:\Temp\AspenMCP"

#: `Document.Export(code, path)`. Codes 4, 5 and 7 all wrote the same input
#: summary; 4 is used because it is the lowest that works. 0-3, 6 and 8 wrote
#: nothing. `SaveAs` with an `.inp` suffix corrupts the document instead.
EXPORT_INPUT_FILE: Final = 4

#: Verified tree paths. The trailing element is a component **index**, not a
#: name: this model's component ids are "1".."6" in `COMPONENTS` order
#: (H3N, H2, N2, O2, H2O, C3H3F5-D1), so H2 is "2".
BLOCKS: Final = r"\Data\Blocks"
STREAMS: Final = r"\Data\Streams"
COMPONENT_NAMES: Final = r"\Data\Components\Specifications\Input\DBNAME1"
PROPERTY_METHOD: Final = r"\Data\Properties\Specifications\Input\GOPSETNAME"
RUN_STATUS: Final = r"\Data\Results Summary\Run-Status\Output"


def block_status(block: str) -> str:
    """Per-block convergence; 0 means a clean solve."""
    return rf"\Data\Blocks\{block}\Output\BLKSTAT"


def stream_mole_flows(stream: str) -> str:
    """Node whose elements are component index -> kmol/h."""
    return rf"\Data\Streams\{stream}\Output\MOLEFLOW\MIXED"


def block_attribute(index: int) -> str:
    """`Elements(name).AttributeValue(i)`: 0 is the icon, 6 is the model name."""
    return {0: "icon", 6: "model"}.get(index, f"attribute {index}")


#: Model names seen in the baseline, with the icon each carries. Neither value
#: is accepted by `Elements.Add`, so they document the model rather than build it.
BASELINE_MODELS: Final = {
    "COND": ("Heater", "HEATER"),
    "CRACKER": ("RStoic", "ICON1"),
    "ENGINE": ("RStoic", "ICON1"),
    "MIXICE": ("Mixer", "TRIANGLE"),
    "MIXSOFC": ("Mixer", "TRIANGLE"),
    "PUMP": ("Pump", "ICON1"),
    "RECUP": ("HeatX", "GEN-HS"),
    "SFCREC": ("HeatX", "GEN-HS"),
    "SOFC": ("RStoic", "ICON1"),
    "TURBINE": ("Compr", "ICON2"),
}

#: Round-trip evidence: editing `MOLE-FLOW 1 100.` to `120.` in the exported
#: `.inp`, re-importing and running moved CRKOUT hydrogen from 147.0 to
#: 176.4 kmol/h - exactly the 1.2 ratio, against a documented baseline of 147.0.
ROUNDTRIP_CHECK: Final = {
    "stream": "CRKOUT",
    "component": "2",
    "nh3_feed_kmol_h": {100.0: 147.0, 120.0: 176.4},
}


#: A closed working-fluid loop conserves mass, so no equation fixes how much
#: fluid circulates and zero is a valid solution. Connecting the ORC condenser
#: to the pump and deleting the makeup stream made Aspen build its own tear
#: (`$OLVER01`) and then converge to 0 kmol/h with 6 of 10 blocks solved.
#: Seeding the torn stream selects the intended inventory: the same flowsheet
#: then gives 10/10 and 10.0 kmol/h consistently around the loop.
#:
#: The makeup stream in the original model was therefore not makeup at all - it
#: was the inventory specification. Aspen tears recycles automatically; what a
#: closed cycle needs from the author is the missing specification, and that is
#: true of an equation-oriented simulator as well.
CLOSED_LOOP_TEAR: Final = {
    "auto_tear_block": "$OLVER01",
    "without_seed": {"converged_blocks": 6, "circulating_kmol_h": 0.0},
    "with_seed": {"converged_blocks": 10, "circulating_kmol_h": 10.0,
                  "turbine_work": -8.2028},
    "seed_form": "a STREAM block for the torn stream acts as an estimate, not a specification",
}


#: Writing a specification through COM works, unlike creating a block:
#: `\Data\Blocks\BFPUMP\Input\PRES` moved 10.0 -> 12.0, the flowsheet re-ran
#: 10/10 and the steam left at 12.0 bar. This is what lets one hand-drawn
#: template serve a whole family of cases.
#:
#: An imported `.inp` carries no drawing at all - block icon attributes come back
#: empty and Aspen auto-places everything, which is why generated flowsheets have
#: colliding stream labels. The drawing lives in a proprietary `GRAPHICS_BACKUP /
#: PFS V 5.00` section of the `.bkp`, and no COM layout or auto-arrange call was
#: found. Lay each template out once in the GUI and inherit it, rather than
#: trying to tidy generated files afterwards.
SPEC_WRITE_CHECK: Final = {
    "node": r"\Data\Blocks\BFPUMP\Input\PRES",
    "before": 10.0, "after": 12.0,
    "rerun": "10/10 converged, STEAM at 12.0 bar",
}
LAYOUT: Final = {
    "inp_carries_drawing": False,
    "bkp_drawing_section": "GRAPHICS_BACKUP / PFS V 5.00",
    "com_autoarrange": None,
    "strategy": "lay out each template once in the GUI; generate cases by COM spec writes",
}
