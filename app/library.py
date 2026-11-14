"""The offline survival library: Markdown pages in library/, searchable.

Includes a tiny Markdown-to-HTML converter (headings, lists, bold/italic,
tables, blockquotes, links between pages) so no extra packages are needed.
"""
import html
import os
import re


def _inline(text):
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    # pictures drawn by tools/make_signs.py:  ![Flag A](sign:flag-A.svg)
    t = re.sub(r"!\[([^\]]*)\]\(sign:([\w\-]+\.svg)\)", r'<img class="sign" src="/static/signs/\2" alt="\1">', t)
    # step pictures drawn by tools/make_figures.py, inside a list item or sentence
    t = re.sub(r"!\[([^\]]*)\]\(fig:([\w\-]+\.svg)\)", r'<img class="fig" src="/static/figs/\2" alt="\1">', t)
    # photos downloaded by tools/get_plant_photos.py: ![Nettle](photo:stinging-nettle.jpg); hidden if missing
    t = re.sub(r"!\[([^\]]*)\]\(photo:([\w\-]+\.jpg)\)",
               r'<img class="photo" src="/static/photos/\2" alt="\1" onerror="this.remove()">', t)
    # a cell that is only a country flag emoji: show it big
    t = re.sub(r"^([\U0001F1E6-\U0001F1FF]{2})$", r'<span class="flag">\1</span>', t)
    t = re.sub(r"\[(.+?)\]\(page:([\w\-/]+)\)", r'<a href="#" data-page="\2">\1</a>', t)
    return t


def md_to_html(md):
    out = []
    lines = md.splitlines()
    i = 0
    list_stack = []  # 'ul' / 'ol'

    def close_lists():
        while list_stack:
            out.append("</%s>" % list_stack.pop())

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            close_lists()
            i += 1
            continue
        # a picture on a line of its own: full width with its caption under it (tap to enlarge)
        m = re.match(r"^\s*!\[([^\]]*)\]\(fig:([\w\-]+\.svg)\)\s*$", line)
        if m:
            close_lists()
            cap = html.escape(m.group(1))
            out.append('<figure class="fig"><img src="/static/figs/%s" alt="%s"><figcaption>%s</figcaption></figure>'
                       % (m.group(2), cap, cap))
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, _inline(m.group(2)), lvl))
            i += 1
            continue
        if line.startswith("|"):
            close_lists()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-+:?$", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append("<table>")
            for n, r in enumerate(rows):
                tag = "th" if n == 0 else "td"
                out.append("<tr>%s</tr>" % "".join("<%s>%s</%s>" % (tag, _inline(c), tag) for c in r))
            out.append("</table>")
            continue
        if line.startswith(">"):
            close_lists()
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip())
                i += 1
            out.append('<div class="warn">%s</div>' % _inline(" ".join(buf)))
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
        if m:
            kind = "ol" if m.group(2)[0].isdigit() else "ul"
            depth = len(m.group(1)) // 2 + 1
            while len(list_stack) > depth:
                out.append("</%s>" % list_stack.pop())
            while len(list_stack) < depth:
                list_stack.append(kind)
                # a numbered list that continues after a picture keeps its numbers
                n = int(m.group(2)[:-1]) if kind == "ol" else 1
                out.append('<ol start="%d">' % n if kind == "ol" and n > 1 else "<%s>" % kind)
            out.append("<li>%s</li>" % _inline(m.group(3)))
            i += 1
            continue
        close_lists()
        buf = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|\s*([-*]|\d+\.)\s|\s*!\[[^\]]*\]\(fig:)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % _inline(" ".join(buf)))
    close_lists()
    return "\n".join(out)


class Library:
    def __init__(self, root):
        self.root = root
        self.pages = {}
        self.reload()

    def reload(self):
        self.pages = {}
        for dirpath, _, files in os.walk(self.root):
            for f in sorted(files):
                if not f.endswith(".md"):
                    continue
                path = os.path.join(dirpath, f)
                pid = os.path.relpath(path, self.root)[:-3].replace(os.sep, "/")
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                m = re.search(r"^#\s+(.*)", text, re.M)
                title = m.group(1).strip() if m else pid
                section = pid.split("/")[0] if "/" in pid else "general"
                self.pages[pid] = {"id": pid, "title": title, "section": section, "text": text}

    def index(self):
        sections = {}
        for p in sorted(self.pages.values(), key=lambda p: p["id"]):
            sections.setdefault(p["section"], []).append({"id": p["id"], "title": p["title"]})
        return sections

    def page(self, pid):
        p = self.pages.get(pid)
        if not p:
            return None
        return {"id": pid, "title": p["title"], "section": p["section"], "html": md_to_html(p["text"])}

    def search(self, q, limit=30):
        words = [w for w in re.findall(r"\w+", q.lower()) if len(w) > 1]
        if not words:
            return []
        hits = []
        for p in self.pages.values():
            title = p["title"].lower()
            body = p["text"].lower()
            score = 0
            for w in words:
                c = body.count(w)
                if c == 0:
                    score = 0
                    break
                score += c + (20 if w in title else 0)
            if score:
                idx = body.find(words[0])
                snippet = p["text"][max(0, idx - 60): idx + 100].replace("\n", " ")
                hits.append({"id": p["id"], "title": p["title"], "score": score,
                             "snippet": re.sub(r"[#*>|]", "", snippet).strip()})
        hits.sort(key=lambda h: -h["score"])
        return hits[:limit]
