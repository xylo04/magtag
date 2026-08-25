# satellites.py — list of satellites to track
# Each entry: (NORAD_ID, short_label, mode)
# mode: "radio" uses N2YO radiopasses endpoint (filters for >0° horizon contact)
#        "visual" uses visualpasses (ISS naked-eye)
SATELLITES = [
    (25544, "ISS",   "radio"),
    (27607, "SO-50", "radio"),   # SaudiSat 1C — FM
    (43017, "AO-91", "radio"),   # RadFxSat — FM
    (43137, "AO-92", "radio"),   # Fox-1D — FM
    (24278, "FO-29", "radio"),   # Fuji-OSCAR 29 — linear
    (40967, "AO-85", "radio"),   # Fox-1A — FM
]
