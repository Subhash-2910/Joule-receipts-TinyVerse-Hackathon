"""Joule Receipts deck (PS 04 template): Title + 6 slides. Dark 'control room' world from the dashboard; signature
move = a paper receipt on a dark desk. python-pptx only."""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.dml import MSO_LINE
from pptx.oxml.ns import qn
from lxml import etree

OUT = sys.argv[1]
IMG = sys.argv[2]
BG, CARD, CARD2, LINE = "0E0E0D", "181817", "1F1F1D", "2E2E2B"
INK, INK2, MUTED = "F0EFEC", "C9C8BE", "9A9993"
BLUE, BLUEHI, ORANGE, GREEN, GREENHI, AMBER, AMBERHI = "3987E5", "86B6EF", "D95926", "0CA30C", "7FDC7F", "FAB219", "FBC552"
PAPER, PAPERINK = "FBFAF5", "161615"
SANS, MONO = "Arial", "Courier New"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def rgb(h):
    return RGBColor.from_string(h)


def alpha(shape, pct):
    for clr in shape._element.spPr.iter(qn("a:srgbClr")):
        a = etree.SubElement(clr, qn("a:alpha")); a.set("val", str(int(pct * 1000)))


def box(s, x, y, w, h, fill=CARD, line=None, radius=None, shape=None, lw=1.0):
    shp = s.shapes.add_shape(shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE),
                             Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shp.adjustments[0] = radius
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid(); shp.fill.fore_color.rgb = rgb(fill)
    if line:
        shp.line.color.rgb = rgb(line); shp.line.width = Pt(lw)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    shp.text_frame.text = ""
    return shp


def text(s, x, y, w, h, runs, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, font=SANS, anchor=MSO_ANCHOR.TOP,
         spacing=None, name=None):
    """runs: str, or list of paragraphs; a paragraph is a str or a list of (text, {opts})."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        parts = para if isinstance(para, list) else [(para, {})]
        for t, o in parts:
            r = p.add_run(); r.text = t
            f = r.font
            f.name = o.get("font", font); f.size = Pt(o.get("size", size)); f.bold = o.get("bold", bold)
            f.italic = o.get("italic", False); f.color.rgb = rgb(o.get("color", color))
    return tb


def icon(s, name, x, y, size=0.42):
    return s.shapes.add_picture(f"{IMG}/i-{name}.png", Inches(x), Inches(y), Inches(size), Inches(size))


def icon_tile(s, name, x, y, size=0.62, fill="22221F", line=LINE):
    box(s, x, y, size, size, fill=fill, line=line, radius=0.22)
    pad = size * 0.2
    icon(s, name, x + pad, y + pad, size - 2 * pad)


def picture(s, name, x, y, w=None, h=None, frame=True):
    if frame:
        pass
    pic = s.shapes.add_picture(f"{IMG}/{name}.png", Inches(x), Inches(y), Inches(w) if w else None,
                               Inches(h) if h else None)
    pic.line.color.rgb = rgb(LINE); pic.line.width = Pt(1)
    return pic


def bg(s):
    f = s.background.fill; f.solid(); f.fore_color.rgb = rgb(BG)
    glow = box(s, -2.2, -3.2, 7.5, 6.0, fill=BLUE, shape=MSO_SHAPE.OVAL); alpha(glow, 9)
    glow2 = box(s, 10.2, -2.8, 5.5, 4.5, fill=ORANGE, shape=MSO_SHAPE.OVAL); alpha(glow2, 5)


def title(s, t, sub=None):
    text(s, 0.6, 0.42, 12.1, 0.7, t, size=32, bold=True, name="Title")
    if sub:
        text(s, 0.6, 1.08, 12.1, 0.4, sub, size=15, color=INK2)


def footer(s, n):
    text(s, 0.6, 7.02, 8, 0.3, "Joule Receipts  ·  PS 04  ·  Subhash Kashyap K H  ·  1MS24CI128", size=10, color=MUTED)
    text(s, 11.7, 7.02, 1.03, 0.3, f"{n} / 6", size=10, color=MUTED, align=PP_ALIGN.RIGHT)


import os
def notes(s, t):
    if not os.environ.get("NO_NOTES"):          # Quick Look cannot preview python-pptx notes; QA builds skip them
        s.notes_slide.notes_text_frame.text = t


def caption(s, x, y, w, t):
    text(s, x, y, w, 0.3, [[("Result screenshot  ·  ", {"bold": True, "color": AMBERHI}), (t, {})]], size=10.5, color=MUTED)


def table(s, x, y, w, col_w, rows, size=12, row_h=0.42, header_fill="232320", stripe=("181817", "1D1D1B"),
          first_col_color=INK, col_colors=None):
    shp = s.shapes.add_table(len(rows), len(col_w), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    tbl = shp.table
    tblPr = tbl._tbl.tblPr
    for attr in ("firstRow", "bandRow"):
        tblPr.set(attr, "0")
    style = tblPr.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"          # 'No Style, No Grid'
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = Inches(cw)
    for r, row in enumerate(rows):
        tbl.rows[r].height = Inches(row_h)
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.fill.solid(); cell.fill.fore_color.rgb = rgb(header_fill if r == 0 else stripe[r % 2])
            cell.margin_left = cell.margin_right = Inches(0.1); cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame; tf.word_wrap = True
            parts = val if isinstance(val, list) else [(val, {})]
            p = tf.paragraphs[0]
            for t, o in parts:
                run = p.add_run(); run.text = t
                f = run.font; f.name = o.get("font", SANS); f.size = Pt(o.get("size", size))
                f.bold = o.get("bold", r == 0 or (c == 0))
                default = MUTED if r == 0 else (first_col_color if c == 0 else (col_colors[c] if col_colors else INK2))
                f.color.rgb = rgb(o.get("color", default))
    return shp


def arrow(s, x, y, w=0.32, h=0.24, color=MUTED, down=False):
    a = box(s, x, y, w, h, fill=color, shape=MSO_SHAPE.DOWN_ARROW if down else MSO_SHAPE.RIGHT_ARROW)
    return a


def receipt(s, x, y, w, rows, stamp=True):
    """Signature move: a printed paper receipt with a torn zig-zag edge."""
    h = 0.62 + 0.36 * len(rows) + 1.35
    box(s, x, y, w, h, fill=PAPER)
    text(s, x, y + 0.2, w, 0.3, "JOULE RECEIPTS  ·  PROOF", size=11, bold=True, color="555555", font=MONO,
         align=PP_ALIGN.CENTER)
    def dash(yy):
        ln = s.shapes.add_connector(1, Inches(x + 0.25), Inches(yy), Inches(x + w - 0.25), Inches(yy))
        ln.line.color.rgb = rgb("BDBCB4"); ln.line.width = Pt(1); ln.line.dash_style = MSO_LINE.DASH
    dash(y + 0.58)
    yy = y + 0.72
    for label, value, color in rows:
        text(s, x + 0.3, yy, w - 1.7, 0.32, label, size=14, color="444444", font=MONO)
        text(s, x + w - 1.5, yy, 1.2, 0.32, value, size=16, bold=True, color=color, font=MONO, align=PP_ALIGN.RIGHT)
        yy += 0.36
    dash(yy + 0.08)
    text(s, x + 0.3, yy + 0.2, w - 0.6, 0.3, [[("ALL MEASURED  ·  p < 0.01", {"bold": True})]], size=12,
         color=PAPERINK, font=MONO)
    text(s, x + 0.3, yy + 0.46, w - 0.6, 0.25, "THANK YOU FOR SAVING ENERGY", size=10, color="777777", font=MONO)
    n = int(w / 0.2)
    tw = w / n
    for i in range(n):                                   # torn edge
        t = box(s, x + i * tw, y + h - 0.005, tw, 0.11, fill=PAPER, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
        t.rotation = 180
    if stamp:
        st = box(s, x + w - 1.8, y + h - 0.72, 1.45, 0.46, fill=None, line="1D7A1D", lw=2.25, radius=0.15)
        st.rotation = -12
        tf = st.text_frame; tf.margin_left = tf.margin_right = 0
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = "PROVEN"; r.font.size = Pt(16); r.font.bold = True; r.font.name = MONO
        r.font.color.rgb = rgb("1D7A1D")
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return h


# ------------------------------------------------------------------ TITLE
s = prs.slides.add_slide(BLANK); bg(s)
text(s, 0.75, 1.3, 7.6, 1.3, "Joule Receipts", size=66, bold=True)
text(s, 0.75, 2.6, 7.2, 1.2, "The offline energy copilot that proves every saving: for your laptop, your code, "
     "and even its own AI.", size=22, color=INK2)
chips = [("Local SLMs: Qwen2.5 0.5B → 1.5B", BLUEHI), ("100% offline", GREENHI), ("4 results certified", AMBERHI)]
cx = 0.75
for t, c in chips:
    wdt = 0.16 + 0.105 * len(t)
    b = box(s, cx, 4.35, wdt, 0.44, fill="1C1C1A", line=LINE, radius=0.5)
    text(s, cx, 4.35, wdt, 0.44, t, size=13, bold=True, color=c, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    cx += wdt + 0.15
meta = [("MEMBER", "Subhash Kashyap K H", 3.25), ("USN", "1MS24CI128", 2.05), ("BRANCH", "CSE (AI & ML)", 2.35),
        ("PROBLEM STATEMENT", "PS 04 · Energy-Aware AI", 4.0)]
mx = 0.75
for k, v, wd in meta:
    text(s, mx, 5.65, wd, 0.3, k, size=11, color=MUTED, bold=True)
    text(s, mx, 5.95, wd, 0.45, v, size=18, bold=True)
    mx += wd
receipt(s, 8.85, 1.0, 3.75, [("IDLE POLLING", "−71%", "1D7A1D"), ("BATCHING", "−94%", "1D7A1D"),
                             ("OWN AI 0.5B→1.5B", "−56%", "1D7A1D"), ("YOUR CODE", "−99%", "1D7A1D"),
                             ("CHAIN VERIFIED", "9/9", PAPERINK)])
notes(s, "Joule Receipts is an energy copilot that runs fully on my laptop. It measures real power with Apple's "
         "sensor, explains it with a small local AI, and proves every saving with a receipt: a before-and-after "
         "experiment with a statistical test. Four savings are measured and certified: idle polling minus 71 percent, "
         "batching minus 94, its own AI minus 56, and a developer's program minus 99.")

# ------------------------------------------------------------------ 1. PROBLEM + EXISTING
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Problem: energy nobody sees, advice nobody proves",
      "Computers waste power in background apps and oversized AI runs, and today's tools cannot show it, fix it, or prove a fix worked.")
cards = [("alert-y", "What the problem is", "Tools show CPU % and vague “energy impact” scores: no watts, no ₹, no next step, and no proof that advice worked."),
         ("users-b", "Who it affects", "Students, campus labs, small offices and developers running AI and code on laptops."),
         ("zap-y", "Why it matters", "Hidden waste costs money and CO₂. Cloud AI assistants need internet, send data out, and can invent numbers.")]
for i, (ic, h, b) in enumerate(cards):
    x = 0.6 + i * 4.1
    box(s, x, 1.65, 3.93, 1.35, fill=CARD, line=LINE, radius=0.1)
    icon_tile(s, ic, x + 0.22, 1.85, 0.56)
    text(s, x + 0.95, 1.83, 2.85, 0.35, h, size=15, bold=True)
    text(s, x + 0.95, 2.17, 2.85, 0.8, b, size=12, color=INK2)
rows = [["Existing solution", "What it does", "Limitation"],
        ["Activity Monitor · powertop", "Show readings", "Usability: relative scores, no ₹, no advice, no proof"],
        ["CodeCarbon · Scaphandre · CarbonLint", "Estimate software energy / CO₂", "Accuracy: mostly estimates; never check whether a fix worked"],
        ["Green Metrics Tool", "Measures software in containers", "Usability: Linux/server setup; no advice; results not tamper-proof"],
        ["Cactus Compute · RunAnywhere (YC)", "Small AI running on-device", "Gap: never measure their own AI's energy"],
        ["DeepAware AI · Edviro (YC)", "AI that saves data-centre energy", "Scale/accuracy: data centres only; 15% claim is from simulation"],
        ["Unravel Carbon · SINAI (YC)", "Company carbon accounting", "Accuracy: from spending data, not device watts"],
        ["Cloud AI assistants", "Chat-based energy tips", "Privacy/offline: need internet, send data out, can invent numbers"]]
table(s, 0.6, 3.25, 12.13, [3.55, 3.15, 5.43], rows, size=12, row_h=0.37, col_colors=[INK, INK2, INK2])
b = box(s, 0.6, 6.33, 12.13, 0.5, fill="102338", line="27507F", radius=0.18)
text(s, 0.85, 6.33, 11.7, 0.5, [[("The gap:  ", {"bold": True, "color": BLUEHI}),
                                 ("no tool closes the loop measure → recommend → prove, offline, with evidence you can trust.", {})]],
     size=15, anchor=MSO_ANCHOR.MIDDLE)
footer(s, 1)
notes(s, "Computers use electricity that costs money and causes emissions, but people can't see it. Activity Monitor "
         "gives unitless scores. CodeCarbon, Scaphandre and CarbonLint estimate software energy but never prove a fix "
         "worked. Y Combinator startups each solve one piece: Cactus and RunAnywhere run small AI on-device but don't "
         "measure its energy; DeepAware and Edviro save data-centre energy, and DeepAware's 15 percent is simulated; "
         "Unravel and SINAI count carbon from spending data. Cloud assistants need internet and can make up numbers. "
         "Nobody closes the loop from measuring to recommending to proving, offline.")

# ------------------------------------------------------------------ 2. PROPOSED SOLUTION
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Solution: measure, explain, then prove it",
      "An offline copilot: it measures every app, a local AI explains what to change, and a receipt proves the saving.")
steps = [("activity-b", "Measure", "Real watts from the Mac's power sensor, split per app"),
         ("search-b", "Find", "Markov states, Apriori patterns, anomaly alerts, what-if"),
         ("cpu-b", "Explain", "Local Qwen 0.5B → 1.5B, every number fact-checked"),
         ("receipt-b", "Prove", "A/B runs ×5, exact test, receipt + A–G label"),
         ("cloud-b", "Sync", "Offline outbox; syncs on reconnect, no duplicates")]
for i, (ic, h, d) in enumerate(steps):
    x = 0.6 + i * 2.47
    box(s, x, 1.62, 2.2, 1.45, fill=CARD, line=LINE, radius=0.1)
    icon_tile(s, ic, x + 0.18, 1.78, 0.5)
    text(s, x + 0.8, 1.86, 1.35, 0.35, h, size=15, bold=True)
    text(s, x + 0.18, 2.36, 1.9, 0.7, d, size=11, color=INK2)
    if i < 4:
        arrow(s, x + 2.22, 2.22, 0.22, 0.22)
diffs = [("receipt-b", "Energy receipts", "Every saving is an experiment: interleaved runs, medians, exact Mann–Whitney test."),
         ("shield-g", "A trust label on every number", "MEASURED · ATTRIBUTED · ESTIMATED · SIMULATED, in the UI and reports."),
         ("cpu-b", "An AI that can't invent numbers, and meters itself", "Small model first; 1.5B only if the fact check fails: −56% energy, measured."),
         ("badge-g", "Certify your own software", "Old vs new version → A–G label and a SHA-256-chained certificate the cloud verifies.")]
text(s, 0.6, 3.3, 6.6, 0.35, "What makes it better than existing tools", size=15, bold=True, color=AMBERHI)
for i, (ic, h, d) in enumerate(diffs):
    x = 0.6 + (i % 2) * 3.35; y = 3.75 + (i // 2) * 1.55
    box(s, x, y, 3.2, 1.42, fill=CARD, line=LINE, radius=0.1)
    icon(s, ic, x + 0.2, y + 0.2, 0.38)
    text(s, x + 0.7, y + 0.16, 2.4, 0.55, h, size=13, bold=True)
    text(s, x + 0.2, y + 0.72, 2.85, 0.68, d, size=11, color=INK2)
picture(s, "ov-hero", 7.35, 3.75, w=5.38)
caption(s, 7.35, 3.75 + 5.38 * 430 / 1164 + 0.08, 5.38, "Dashboard Overview: three proven savings, all MEASURED, plus live pipeline status.")
footer(s, 2)
notes(s, "From the user's side: open the dashboard and see live watts per app. The copilot finds patterns and "
         "anomalies, the local model explains what to change in plain English, and one click runs a fair "
         "before-and-after test and prints a receipt. Decisions go into an offline queue that syncs by itself. "
         "What's different: receipts with real statistics, an honesty label on every number, an AI that can't "
         "invent numbers and measures its own energy, and developers can certify their own code.")

# ------------------------------------------------------------------ 3. TECH STACK
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Tech stack: small, local and reproducible",
      "One language, no cloud dependency, every result reproducible with one command.")
rows = [["Layer", "Choice", "Why"],
        ["Language", "Python 3.12 (core uses only the standard library)", "One language for sensing, AI and UI"],
        ["Local AI model", "Qwen2.5 0.5B → 1.5B cascade, Ollama, 4-bit", "Under 4B, offline, fact-checked"],
        ["Measurement", "macOS powermetrics (1 s) · battery gauge · psutil", "Real watts, no extra hardware"],
        ["Analytics", "Markov chain · Apriori · exact Mann–Whitney", "Light and explainable"],
        ["Database", "SQLite (WAL) · transactional outbox · SHA-256 chain", "Crash-safe, tamper-evident"],
        ["Backend / sync", "Python HTTP server in Docker · idempotency keys", "Safe retries, no duplicates"],
        ["Frontend", "Streamlit · Plotly · HTML certificates", "Readable, fast to build"],
        ["Quality / deploy", "57 tests · GitHub Actions (Ubuntu + macOS) · Docker Compose", "One command reproduces it"]]
table(s, 0.6, 1.65, 8.35, [1.75, 4.15, 2.45], rows, size=12, row_h=0.5, col_colors=[INK, INK, INK2])
box(s, 9.2, 1.65, 3.53, 2.55, fill="2A2209", line="6B5212", radius=0.08)
icon(s, "lock-y", 9.42, 1.85, 0.4)
text(s, 9.95, 1.87, 2.7, 0.4, "Why a small local model?", size=15, bold=True, color=AMBERHI)
text(s, 9.42, 2.4, 3.15, 1.75, ["Private: data never leaves the laptop.", "Works with no internet at all.",
                                 "Cheaper: 0.5B answered 6/6 checks with 56% less energy than 1.5B (MEASURED)."],
     size=12, color=INK, spacing=6)
box(s, 9.2, 4.4, 3.53, 2.25, fill=CARD, line=LINE, radius=0.08)
text(s, 9.42, 4.57, 3.1, 0.35, "Models, data and APIs", size=15, bold=True)
text(s, 9.42, 5.0, 3.15, 1.6, [[("Models: ", {"bold": True, "color": INK}), ("Qwen2.5-0.5B (0.49B) and 1.5B (1.54B), Apache-2.0", {})],
                                [("Data: ", {"bold": True, "color": INK}), ("no external dataset; every number is measured on the device", {})],
                                [("APIs: ", {"bold": True, "color": INK}), ("only Ollama's local HTTP API", {})]],
     size=12, color=INK2, spacing=5)
footer(s, 3)
notes(s, "Python everywhere; the core uses only the standard library. Qwen 2.5 0.5B and 1.5B run through Ollama at "
         "4-bit and need no internet after download; the small one answers first and the fact check decides if the "
         "larger one is needed. Power comes from Apple's powermetrics in 1-second windows. SQLite in WAL mode with a "
         "transactional outbox makes storage crash-safe, and receipts are chained with SHA-256. The sync server runs "
         "in Docker. 57 automated tests run on Ubuntu and macOS.")

# ------------------------------------------------------------------ 4. ARCHITECTURE
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Architecture: from sensor reading to certified receipt")
lanes = [("Sense & store", [("Mac sensors", "powermetrics · battery · psutil"), ("Collector", "1 s windows, trust tags"),
                            ("SQLite (WAL)", "readings, receipts, outbox")]),
         ("Understand & explain", [("Analytics", "Markov · Apriori · power model"), ("Facts JSON", "Wh · ₹ · gCO₂e, computed"),
                                   ("Local SLM", "Qwen 0.5B → 1.5B on Ollama"), ("Grounding check", "numbers must match facts")]),
         ("Act, prove & sync", [("Dashboard", "8 pages: advice, receipts…"), ("User / developer", "accept · certify code"),
                                ("A/B runner", "×5 runs → receipt"), ("Chain + outbox", "SHA-256 · idempotent"),
                                ("Cloud (Docker)", "dedupe · verifies chain")])]
ly = 1.35
for li, (lane, nodes) in enumerate(lanes):
    y = ly + li * 1.62
    text(s, 0.6, y + 0.25, 1.55, 0.7, lane, size=14, bold=True, color=AMBERHI)
    n = len(nodes)
    gap = 0.34
    bw = (12.73 - 2.25 - gap * (n - 1)) / n
    for ni, (h, d) in enumerate(nodes):
        x = 2.25 + ni * (bw + gap)
        hot = h == "Local SLM"
        box(s, x, y, bw, 1.05, fill=AMBER if hot else CARD2, line=None if hot else LINE, radius=0.1)
        text(s, x + 0.15, y + 0.15, bw - 0.3, 0.35, h, size=14, bold=True, color=PAPERINK if hot else INK)
        text(s, x + 0.15, y + 0.5, bw - 0.3, 0.5, d, size=11, color="3A2A00" if hot else INK2)
        if ni < n - 1:
            arrow(s, x + bw + 0.06, y + 0.42, 0.22, 0.22, color=AMBER)
    if li < 2:
        arrow(s, 2.25 + (12.73 - 2.25) / 2 - 0.12, y + 1.13, 0.24, 0.36, color=AMBER, down=True)
icon(s, "refresh-y", 0.6, 6.32, 0.36)
text(s, 1.08, 6.3, 5.6, 0.62, [[("Feedback loop: ", {"bold": True, "color": AMBERHI}),
                                ("measured receipts feed predictions; every AI answer meters its own energy.", {})]], size=12, color=INK2)
icon(s, "lock-y", 6.85, 6.32, 0.36)
text(s, 7.33, 6.3, 5.4, 0.62, [[("Security: ", {"bold": True, "color": AMBERHI}),
                                ("AI and raw readings stay on the laptop; receipts are tamper-evident, verified by the cloud.", {})]],
     size=12, color=INK2)
footer(s, 4)
notes(s, "Row one: a collector reads Apple's power sensor in 1-second windows and stores readings in SQLite with a "
         "trust tag. Row two: the analytics engine computes facts and predictions; the local model only writes the "
         "explanation, small model first, and the grounding check rejects any number not in the facts. Row three: the "
         "user accepts advice or a developer certifies code; the experiment runner proves it and writes a receipt "
         "into a SHA-256 hash chain and the outbox in one transaction; the sync worker sends it to the cloud in Docker, "
         "which ignores duplicates and re-verifies the chain.")

# ------------------------------------------------------------------ 5. IMPACT
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Impact: lower bills and CO₂, with proof")
cols = [("users-b", "Social", "100%", "offline and private", BLUEHI,
         ["Plain-language advice anyone can act on", "Works in labs and towns with patchy internet",
          "Readings and AI stay on the device"]),
        ("rupee-g", "Economic", "−56 to −99%", "energy per task, measured", GREENHI,
         ["Every saving in ₹ (BESCOM ₹5.80/kWh) and gCO₂e, with its formula",
          "Chrome alone was ~25% of chip power in a real 15-min session",
          "No subscription; savings scale with devices in a lab"]),
        ("rocket-b", "Technical", "4 certified", "results, tamper-evident", AMBERHI,
         ["A <4B model giving fact-checked advice offline", "AI that measures and cuts its own energy",
          "An energy label for any developer's code"])]
for i, (ic, h, big, sub, c, items) in enumerate(cols):
    x = 0.6 + i * 4.1
    box(s, x, 1.35, 3.93, 3.25, fill=CARD, line=LINE, radius=0.07)
    icon_tile(s, ic, x + 0.22, 1.55, 0.56)
    text(s, x + 0.95, 1.68, 2.8, 0.35, h, size=17, bold=True)
    text(s, x + 0.22, 2.3, 3.6, 0.6, big, size=30, bold=True, color=c)
    text(s, x + 0.22, 2.85, 3.6, 0.3, sub, size=12, color=MUTED)
    text(s, x + 0.22, 3.25, 3.55, 1.35, [[("•  ", {"color": c, "bold": True}), (t, {})] for t in items],
         size=12, color=INK2, spacing=4)
picture(s, "adv-ai", 0.6, 4.78, h=1.8)
w_adv = 1.8 * 1164 / 390
caption(s, 0.6, 4.78 + 1.8 + 0.06, w_adv, "Advice page: real numbers, fact-checked AI, 6.8 J per answer.")
text(s, 0.6 + w_adv + 0.3, 4.95, 12.73 - (0.6 + w_adv + 0.3), 1.8,
     [[("Real advice, real numbers. ", {"bold": True, "color": INK})],
      "Chrome used 0.247 W while idle (sensor-based). Putting tabs to sleep saves 1.98 Wh/day, ₹0.34 and 42.5 g CO₂e a month.",
      "The local AI wrote it offline, every number passed the fact check, and the answer itself cost 6.8 J."],
     size=12, color=INK2, spacing=6)
footer(s, 5)
notes(s, "Social: anyone can understand the advice, it works without internet, and data stays private. Economic: "
         "savings of 56 to 99 percent per task, measured, every rupee figure uses the BESCOM tariff with its formula, "
         "and a real 15-minute session showed Chrome alone was about a quarter of chip power. Technical: a model under "
         "4B can give fact-checked advice offline, the AI cuts its own energy, and developers get an energy label for "
         "their code.")

# ------------------------------------------------------------------ 6. EXTRAS: RESULTS
s = prs.slides.add_slide(BLANK); bg(s)
title(s, "Results: four savings, measured and certified")
G = GREENHI
rows = [["Test", "Before → after", "Saving", "Evidence", "Label"],
        ["Idle polling: 0.1 s → 2 s", "2.09 → 0.62 mWh/min", [("−71%", {"bold": True, "color": G})], "p < 0.001 · 10+10 runs", [("B ✓", {"bold": True, "color": G})]],
        ["Batching: 200 → 10 launches", "3.49 → 0.21 mWh", [("−94%", {"bold": True, "color": G})], "p = 0.008 · pilot within 0.3%", [("A ✓", {"bold": True, "color": G})]],
        ["Own AI: 1.5B → 0.5B first", "20.4 → 8.91 mWh", [("−56%", {"bold": True, "color": G})], "p = 0.008 · 6/6 fact-checked", [("C ✓", {"bold": True, "color": G})]],
        ["Your code: prime counter v1 → v2", "3.12 → 0.02 mWh/run", [("−99%", {"bold": True, "color": G})], "p = 0.008 · identical output", [("A ✓", {"bold": True, "color": G})]]]
table(s, 0.6, 1.3, 7.15, [2.35, 1.65, 0.75, 1.55, 0.85], rows, size=11, row_h=0.46, col_colors=[INK, INK, INK, INK2, INK])
text(s, 0.6, 3.68, 7.15, 0.55, "All MEASURED with powermetrics on an Apple M3 · medians of interleaved runs · exact "
     "Mann–Whitney test · sync: 55 delivered, 0 lost, 0 duplicates · cloud verified 9/9 receipts", size=10.5, color=MUTED)
box(s, 0.6, 4.35, 3.5, 2.45, fill=CARD, line=LINE, radius=0.08)
text(s, 0.8, 4.5, 3.2, 0.35, "Roadmap", size=15, bold=True)
text(s, 0.8, 4.92, 3.2, 1.85, [[("•  ", {"color": BLUEHI, "bold": True}), (t, {})] for t in
                               ["Linux (Intel RAPL) and Windows sensors", "Lab fleet view: many machines",
                                "joule certify as a GitHub Action on every pull request", "Live grid-carbon data when online"]],
     size=11, color=INK2, spacing=4)
box(s, 4.25, 4.35, 3.5, 2.45, fill=CARD, line=LINE, radius=0.08)
text(s, 4.45, 4.5, 3.2, 0.35, "References", size=15, bold=True)
text(s, 4.45, 4.92, 3.2, 1.85, [[("•  ", {"color": BLUEHI, "bold": True}), (t, {})] for t in
                                ["Apple powermetrics(1) manual", "Ollama; Qwen2.5 (Apache-2.0)",
                                 "CEA CO₂ Baseline Database, Indian grid", "BESCOM LT-1 tariff, FY 2026–27",
                                 "Mann–Whitney U test (exact)"]], size=11, color=INK2, spacing=4)
cw = 4.73
picture(s, "cf-label", 8.0, 1.3, w=cw)
ch = cw * 449 / 604
caption(s, 8.0, 1.3 + ch + 0.06, cw, "Certify page: grade A, CERTIFIED, 1% of the old version's energy.")
sy = 1.3 + ch + 0.62
dh = min(6.55 - sy, 1.75)
picture(s, "rc-dots2", 8.0, sy, h=dh)
dw = dh * 604 / 292
caption(s, 8.0, sy + dh + 0.06, 4.73, "Receipts page: own-AI runs, 25/25 pairs lower.")
text(s, 8.0 + dw + 0.15, sy + 0.02, 12.73 - (8.0 + dw + 0.15), dh,
     [[("Own AI receipt", {"bold": True, "color": INK2})], "Every 0.5B-first run (blue) used less energy than every 1.5B run (orange): 25/25 pairs."],
     size=10.5, color=MUTED, spacing=3)
footer(s, 6)
notes(s, "All four results were measured with Apple's powermetrics on my M3. Idle polling every 2 seconds instead "
         "of every 0.1: 71 percent less, all 10 optimized runs beat all 10 baseline runs. Batching 200 jobs into 10 "
         "launches: 94 percent less, and a pilot predicted it within 0.3 percent. The copilot's own AI, small model "
         "first: 56 percent less, every answer fact-checked. And a developer's program, version 2 versus version 1 "
         "with identical output: 99 percent less, grade A, certified. Sync delivered everything with zero duplicates, "
         "and the cloud verified all nine receipts. Next: Linux and Windows sensors, a lab fleet view, and joule "
         "certify as a GitHub Action.")

prs.save(OUT)
print("saved", OUT)
