"""Markdown -> semantic HTML for the VESPER design artifacts. Stdlib only."""
from __future__ import annotations
import html, re

STATUS = {
    "FRONTEND": "frontend", "READY": "ready", "BLOCKED": "blocked",
    "SUPERSEDED": "superseded", "LIVE": "ready", "UNAVAILABLE": "blocked",
    "PARTIAL": "partial",
}

def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', t)
    t = re.sub(r'&lt;(https?://[^&\s]+)&gt;', r'<a href="\1">\1</a>', t)
    # status words become pills, but only when they stand alone as a token
    def pill(m):
        w = m.group(1)
        return f'<span class="pill p-{STATUS[w]}">{w}</span>'
    t = re.sub(r'(?<![\w>/-])(' + '|'.join(STATUS) + r')(?![\w<-])', pill, t)
    return t

def convert(md: str) -> str:
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        L = lines[i]
        if L.startswith("```"):
            j = i + 1; buf = []
            while j < n and not lines[j].startswith("```"):
                buf.append(lines[j]); j += 1
            out.append('<pre><code>' + html.escape("\n".join(buf)) + '</code></pre>')
            i = j + 1; continue
        if re.match(r'^\s*\|', L) and i + 1 < n and re.match(r'^\s*\|[\s:|-]+\|\s*$', lines[i+1]):
            cells = [c.strip() for c in L.strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < n and re.match(r'^\s*\|', lines[j]):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")]); j += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in cells)
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')
            i = j; continue
        m = re.match(r'^(#{1,4})\s+(.*)$', L)
        if m:
            lv = len(m.group(1)); txt = m.group(2)
            num = re.match(r'^((?:\d+[a-z]?\.)?\d*[a-z]?)\.?\s+(.*)$', txt)
            sid = re.sub(r'[^a-z0-9]+', '-', txt.lower()).strip('-')[:48]
            eyebrow = ""
            m2 = re.match(r'^(\d+(?:\.\d+)?)\.\s+(.*)$', txt)
            if m2 and lv in (2, 3):
                eyebrow = f'<span class="num">{m2.group(1)}</span>'
                txt = m2.group(2)
            out.append(f'<h{lv} id="{sid}">{eyebrow}<span>{inline(txt)}</span></h{lv}>')
            i += 1; continue
        if L.startswith("> "):
            buf = []
            while i < n and lines[i].startswith("> "):
                buf.append(lines[i][2:]); i += 1
            out.append(f'<blockquote><p>{inline(" ".join(buf))}</p></blockquote>')
            continue
        if re.match(r'^-{3,}\s*$', L):
            out.append('<hr>'); i += 1; continue
        if re.match(r'^\s*[-*]\s+', L) or re.match(r'^\s*\d+\.\s+', L):
            ordered = bool(re.match(r'^\s*\d+\.\s+', L))
            items, cur = [], None
            while i < n and (re.match(r'^\s*[-*]\s+', lines[i]) or re.match(r'^\s*\d+\.\s+', lines[i]) or (cur is not None and lines[i].startswith("  ") and lines[i].strip())):
                mm = re.match(r'^\s*(?:[-*]|\d+\.)\s+(.*)$', lines[i])
                if mm:
                    if cur is not None: items.append(cur)
                    cur = mm.group(1)
                else:
                    cur += " " + lines[i].strip()
                i += 1
            if cur is not None: items.append(cur)
            tag = "ol" if ordered else "ul"
            out.append(f'<{tag}>' + "".join(f'<li>{inline(x)}</li>' for x in items) + f'</{tag}>')
            continue
        if L.strip() == "":
            i += 1; continue
        buf = []
        while i < n and lines[i].strip() and not re.match(r'^(#{1,4}\s|>\s|\s*[-*]\s|\s*\d+\.\s|\s*\||```|-{3,}\s*$)', lines[i]):
            buf.append(lines[i].strip()); i += 1
        para = " ".join(buf)
        cls = ' class="lede"' if para.startswith("**") and para.count("**") == 2 and len(para) < 300 else ""
        out.append(f'<p{cls}>{inline(para)}</p>')
    return "\n".join(out)
