"""Self-contained HTML article renderer for a released report.

Produces one standalone HTML document (inline CSS + inline SVG plots, no external assets) that can
be downloaded, emailed, archived, or printed to PDF via the browser. We deliberately avoid adding
a server-side PDF dependency (weasyprint/wkhtmltopdf want system libs); the `?print=1` variant
auto-triggers the browser's Print dialog so the user can "Save as PDF" in one click.

Everything shown here is derived from the same report dict that drives the Report panel in the UI;
the article does not re-compute any numbers or pull from the agents again, so the on-screen and
printed versions always agree.
"""
from __future__ import annotations

import html
import re
import time
from typing import Any


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _md(text: str) -> str:
    """Very small markdown subset: paragraphs on blank lines, `**bold**`, `*italic*`, `- ` bullets,
    and single newlines → <br>. Enough for the agent-drafted summary (which is already simple
    prose) without pulling in a markdown library."""
    if not text:
        return ""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if all(re.match(r"\s*[-*]\s+", ln) for ln in lines):
            items = "".join(f"<li>{_inline(re.sub(r'^\s*[-*]\s+', '', ln))}</li>" for ln in lines)
            out.append(f"<ul>{items}</ul>")
        else:
            out.append("<p>" + _inline("<br>".join(_esc(ln) for ln in lines)) + "</p>")
    return "".join(out)


def _inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", s)
    return s


def _hbars(items: list[tuple[str, float]], *, width: int = 460, bar_h: int = 18, gap: int = 8,
           label_w: int = 180, val_w: int = 48, accent_last: bool = False,
           colour: str = "#2c5d9e", accent: str = "#a8215f") -> str:
    """Horizontal bar chart as inline SVG. Pure data-in, SVG-out — no plotting library.

    `items` is [(label, value), ...]. The longest value fills the plot area; others scale linearly.
    `accent_last` highlights the final bar (used for the funnel's "analysed" step)."""
    if not items:
        return '<p class="muted">No data.</p>'
    values = [max(0.0, float(v)) for _, v in items]
    vmax = max(values) or 1.0
    plot_w = width - label_w - val_w - 16
    rows = len(items)
    height = rows * (bar_h + gap) - gap + 4
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for i, ((label, raw), v) in enumerate(zip(items, values)):
        y = i * (bar_h + gap)
        w = (v / vmax) * plot_w
        fill = accent if (accent_last and i == rows - 1) else colour
        svg.append(f'<text x="0" y="{y + bar_h * 0.72}" font-size="11" fill="#142133">{_esc(label)}</text>')
        svg.append(f'<rect x="{label_w}" y="{y}" width="{plot_w}" height="{bar_h}" rx="2" fill="#eef1f6"/>')
        svg.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="2" fill="{fill}"/>')
        shown = int(raw) if float(raw).is_integer() else raw
        svg.append(f'<text x="{label_w + plot_w + 8}" y="{y + bar_h * 0.72}" font-size="11" fill="#142133" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">{_esc(shown)}</text>')
    svg.append("</svg>")
    return "".join(svg)


def _drug_bars(rows: list[dict]) -> str:
    """Per-drug stacked bar: predicted resistant (pink) + uncertain/pending (amber) over total (grey)."""
    if not rows:
        return '<p class="muted">No drugs evaluated.</p>'
    width = 460
    label_w, val_w = 180, 110
    plot_w = width - label_w - val_w - 16
    bar_h, gap = 18, 10
    height = len(rows) * (bar_h + gap) - gap + 4
    svg = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">']
    for i, r in enumerate(rows):
        y = i * (bar_h + gap)
        n = max(1, r["n"])
        res_w = r["predicted_resistant"] / n * plot_w
        unc_w = r["uncertain_or_pending"] / n * plot_w
        svg.append(f'<text x="0" y="{y + bar_h * 0.72}" font-size="11" fill="#142133">{_esc(r["name"])}</text>')
        svg.append(f'<rect x="{label_w}" y="{y}" width="{plot_w}" height="{bar_h}" rx="2" fill="#eef1f6"/>')
        svg.append(f'<rect x="{label_w}" y="{y}" width="{res_w:.1f}" height="{bar_h}" rx="2" fill="#a8215f"/>')
        svg.append(f'<rect x="{label_w + res_w:.1f}" y="{y}" width="{unc_w:.1f}" height="{bar_h}" fill="#d58a2a"/>')
        label = f'{r["predicted_resistant"]} R · {r["uncertain_or_pending"]} ? / {r["n"]}'
        svg.append(f'<text x="{label_w + plot_w + 8}" y="{y + bar_h * 0.72}" font-size="11" fill="#142133" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">{_esc(label)}</text>')
    svg.append("</svg>")
    legend = ('<p class="legend"><span class="sw" style="background:#a8215f"></span>Predicted resistant '
              '<span class="sw" style="background:#d58a2a"></span>Uncertain / pending '
              '<span class="sw" style="background:#eef1f6;border:1px solid #cbd1dc"></span>Remainder of profiled cohort</p>')
    return "".join(svg) + legend


_CSS = """
:root { --ink: #142133; --muted: #5a6778; --rule: #cbd1dc; --panel: #ffffff; --bg: #f7f7fa;
        --accent: #a8215f; --blue: #2c5d9e; --amber: #d58a2a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.wrap { max-width: 820px; margin: 0 auto; padding: 48px 40px 80px; background: var(--panel); }
h1 { font-size: 1.9rem; margin: 0 0 .25rem; letter-spacing: -0.01em; }
h2 { font-size: 1.2rem; margin: 2rem 0 .5rem; padding-top: 1rem; border-top: 1px solid var(--rule); }
h3 { font-size: 1rem; margin: 1.25rem 0 .5rem; }
.eyebrow { color: var(--muted); font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; }
.chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .74rem;
        letter-spacing: .04em; text-transform: uppercase; font-weight: 600; border: 1px solid var(--rule); }
.chip.final { background: #ecf6ee; border-color: #4b9f5e; color: #255c33; }
.chip.draft { background: #fff5e5; border-color: #d58a2a; color: #8a4f00; }
.chip.superseded { background: #fde7eb; border-color: #a8215f; color: #6b0f36; }
.meta { color: var(--muted); font-size: .9rem; }
.meta b { color: var(--ink); font-weight: 600; }
.note { background: #f0f4fa; border-left: 3px solid var(--blue); padding: 10px 14px; margin: 1rem 0;
        font-size: .9rem; color: var(--ink); }
.limit { background: #fff8ef; border-left: 3px solid var(--amber); padding: 10px 14px; margin: 1rem 0; }
.prose p { margin: .55rem 0; }
.prose ul { margin: .4rem 0 .4rem 1.2rem; padding: 0; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; margin: .5rem 0; }
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--rule); }
th { font-weight: 600; background: #f3f5f9; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; }
ul.clean { list-style: none; margin: .25rem 0 0; padding: 0; }
ul.clean li { padding: 3px 0; border-bottom: 1px dashed var(--rule); }
.muted { color: var(--muted); }
.plot { margin: .5rem 0 1rem; }
.legend { font-size: .78rem; color: var(--muted); margin: .25rem 0 0; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: middle; margin: 0 4px 0 10px; }
.footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--rule);
          color: var(--muted); font-size: .8rem; }
.toolbar { position: sticky; top: 0; background: var(--bg); padding: 10px 0; display: flex; gap: 8px;
           justify-content: flex-end; border-bottom: 1px solid var(--rule); margin-bottom: 1rem; }
.btn { display: inline-block; padding: 6px 12px; border-radius: 4px; border: 1px solid var(--rule);
       background: #fff; color: var(--ink); font-size: .85rem; cursor: pointer; text-decoration: none; }
.btn:hover { border-color: var(--ink); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
@media print {
  body { background: #fff; }
  .wrap { max-width: none; padding: 0 .5in; }
  .toolbar { display: none; }
  h2 { page-break-after: avoid; }
  table, svg { page-break-inside: avoid; }
}
"""


def render_article_html(state, report: dict[str, Any], *, print_mode: bool = False,
                        download_url: str | None = None) -> str:
    """Render the released report as a standalone, publishable HTML article.

    `state` is the PipelineState (used for scope context: question, country, target drugs).
    `report` is the report dict built by ReportingOrchestrator.build().
    `print_mode=True` injects an onload Print dialog so "Download PDF" is one click → Save as PDF.
    `download_url` is a convenience "Save PDF" button in the on-screen toolbar."""
    rel = (report.get("gates") or {}).get("release") or (getattr(state, "gates", {}) or {}).get("release")
    kind = (rel or {}).get("kind")
    superseded = bool(report.get("superseded"))
    if superseded:
        status_chip = '<span class="chip superseded">Superseded</span>'
    elif kind == "final":
        status_chip = '<span class="chip final">Released · final</span>'
    elif kind == "draft":
        status_chip = '<span class="chip draft">Exploratory draft</span>'
    else:
        status_chip = '<span class="chip">Not yet released</span>'

    generated = time.strftime("%Y-%m-%d %H:%M", time.gmtime(report.get("generated_at") or time.time()))
    c = report.get("counts", {})

    funnel = _hbars([
        ("Total candidates", c.get("candidates", 0)),
        ("Verified eligible", c.get("verified", 0)),
        ("Quality-Control passed", c.get("qc_passed", 0)),
        ("Profiled & evaluated", c.get("analysed", 0)),
    ], accent_last=True)

    drug_rows = report.get("drugs", [])
    drug_chart = _drug_bars(drug_rows)
    drug_table = ""
    if drug_rows:
        def _drow(d: dict) -> str:
            conc = f'{d["concordant"]} / {d["dst_n"]}' if d["dst_n"] else "n/a"
            return (f'<tr><td>{_esc(d["name"])}</td>'
                    f'<td class="num">{d["predicted_resistant"]} / {d["n"]}</td>'
                    f'<td class="num">{d["uncertain_or_pending"]}</td>'
                    f'<td class="num">{d["reviewed"]}</td>'
                    f'<td class="num">{d["dst_n"]} / {d["n"]}</td>'
                    f'<td class="num">{_esc(conc)}</td></tr>')
        body = "".join(_drow(d) for d in drug_rows)
        drug_table = (
            '<table><thead><tr><th>Drug</th><th class="num">Predicted resistant</th>'
            '<th class="num">Uncertain / pending</th><th class="num">Reviewed</th>'
            '<th class="num">Matched DST</th><th class="num">Concordance</th></tr></thead>'
            f'<tbody>{body}</tbody></table>'
        )

    muts = report.get("top_mutations", [])
    mut_chart = _hbars([(k, v) for k, v in muts], colour="#2c5d9e") if muts else ""
    lineages = report.get("lineages", [])
    lin_chart = _hbars([(k, v) for k, v in lineages], colour="#2c5d9e") if lineages else ""

    limits_html = "".join(f"<li>{_esc(l)}</li>" for l in report.get("limitations", []))

    unresolved = report.get("unresolved", [])
    unresolved_html = ("<ul class='clean'>" + "".join(
        f'<li><span class="mono">{_esc(u["run"])}</span> · {_esc(u["variant"])} ({_esc(u["drug"])}) — {_esc(u["reason"])}</li>'
        for u in unresolved
    ) + "</ul>") if unresolved else '<p class="muted">None.</p>'

    exclusions = report.get("exclusions", [])
    excl_html = ""
    if exclusions:
        body = "".join(
            f'<tr><td class="mono">{_esc(x["run"])}</td><td>{_esc(x.get("status") or "—")}</td>'
            f'<td>{_esc(x.get("reason") or "")}</td></tr>' for x in exclusions
        )
        excl_html = f'<table><thead><tr><th>Run</th><th>Status</th><th>Reason</th></tr></thead><tbody>{body}</tbody></table>'
    else:
        excl_html = '<p class="muted">None.</p>'

    provenance = report.get("provenance", {})
    tools = ", ".join(provenance.get("tools") or []) or "—"
    dbs = ", ".join(provenance.get("databases") or []) or "—"
    rules = " · ".join(str(v) for v in (provenance.get("rules") or {}).values()) or "—"

    question = _esc(getattr(state, "question", "") or "—")
    country = _esc(getattr(state, "country", "") or "—")
    drugs_scope = ", ".join(_esc(d) for d in (getattr(state, "target_drugs", []) or [])) or "—"
    summary = report.get("summary_draft") or ""
    summary_html = _md(summary) if summary else '<p class="muted">No plain-language summary was drafted for this version.</p>'

    toolbar_html = ""
    if not print_mode:
        buttons = ['<a class="btn" href="#" onclick="window.print();return false">Save as PDF</a>']
        if download_url:
            buttons.insert(0, f'<a class="btn primary" href="{_esc(download_url)}" download>Download HTML</a>')
        toolbar_html = f'<div class="toolbar">{"".join(buttons)}</div>'

    onload = ' onload="window.print()"' if print_mode else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TB-AMR evidence report v{_esc(report.get("version"))} — {country}</title>
<style>{_CSS}</style>
</head>
<body{onload}>
<div class="wrap">
{toolbar_html}
<span class="eyebrow">Report v{_esc(report.get("version"))} · {_esc(report.get("rule_version"))}</span>
<h1>Genomic resistance evidence · {country}</h1>
<p class="meta">{status_chip} &nbsp; <b>Generated</b> {_esc(generated)} UTC</p>
<p class="meta"><b>Question:</b> {question}<br/><b>Target drugs:</b> {drugs_scope}</p>

<div class="note">Computational predictions from public genomes. Not laboratory-confirmed susceptibility; not a national prevalence estimate.</div>

<h2>Plain-language summary</h2>
<div class="prose">{summary_html}</div>

<h2>Sample counts</h2>
<div class="plot">{funnel}</div>

<h2>Resistance evidence by drug <span class="muted">(n = {_esc(c.get("analysed", 0))})</span></h2>
<div class="plot">{drug_chart}</div>
{drug_table}

<h2>Most frequent mutations</h2>
{('<div class="plot">' + mut_chart + '</div>') if mut_chart else '<p class="muted">None yet.</p>'}

<h2>Lineages</h2>
{('<div class="plot">' + lin_chart + '</div>') if lin_chart else '<p class="muted">None yet.</p>'}

<h2>Limitations</h2>
<div class="limit"><ul>{limits_html}</ul></div>

<h2>Unresolved findings</h2>
{unresolved_html}

<h2>Exclusions and holds</h2>
{excl_html}

<h2>Provenance</h2>
<p class="meta"><b>Tools:</b> {_esc(tools)}<br/>
<b>Databases:</b> {_esc(dbs)}<br/>
<b>Rules:</b> <span class="mono">{_esc(rules)}</span></p>

<div class="footer">TB-AMR Agent Team · each number here is derived by rule from the pipeline's decision records, which can be audited through the agent trace in the web UI.</div>
</div>
</body>
</html>"""
