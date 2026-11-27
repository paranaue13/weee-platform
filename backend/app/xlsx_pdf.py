"""Μετατροπή αρχείου Excel (.xlsx) σε PDF με την ίδια εμφάνιση (χωρίς Excel/LibreOffice).

Σχεδιάζει κάθε φύλλο όπως είναι: πλάτη στηλών, ύψη γραμμών, συγχωνευμένα κελιά, χρώματα, γραμματοσειρά, στοίχιση, γραμμές πλαισίου.
Οι απλοί τύποι (SUM, +, -, *, /, &, αναφορές σε άλλα φύλλα) υπολογίζονται εδώ, γιατί τα αρχεία που φτιάχνει η εφαρμογή δεν έχουν αποθηκευμένα αποτελέσματα.
"""
from __future__ import annotations

import datetime as _dt
import os
import re

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

_THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"]
_FONT = None


def _fonts():
    global _FONT
    if _FONT:
        return _FONT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    reg, bold = "Helvetica", "Helvetica-Bold"
    for d in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/"):
        r, b = d + "arial.ttf", d + "arialbd.ttf"
        if not os.path.exists(r):
            r, b = d + "DejaVuSans.ttf", d + "DejaVuSans-Bold.ttf"
        if os.path.exists(r):
            try:
                pdfmetrics.registerFont(TTFont("XPReg", r))
                pdfmetrics.registerFont(TTFont("XPBold", b if os.path.exists(b) else r))
                reg, bold = "XPReg", "XPBold"
                break
            except Exception:
                pass
    _FONT = (reg, bold)
    return _FONT


# ---------------------------------------------------------------- τύποι
class _Eval:
    def __init__(self, wb):
        self.wb = wb
        self.cache = {}
        self.busy = set()

    def value(self, ws, row, col):
        v = ws.cell(row, col).value
        if isinstance(v, str) and v.startswith("="):
            key = (ws.title, row, col)
            if key in self.cache:
                return self.cache[key]
            if key in self.busy:
                return 0
            self.busy.add(key)
            try:
                r = self._formula(ws, v[1:])
            except Exception:
                r = ""
            self.busy.discard(key)
            self.cache[key] = r
            return r
        return v

    # tokenizer + recursive descent
    _TOK = re.compile(r"""\s*(?:(?P<str>"(?:[^"]|"")*")|(?P<num>\d+(?:\.\d+)?)|(?P<ref>(?:(?:'(?:[^']|'')+'|[^\W\d][\w.]*)!)?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)|(?P<fn>[A-Za-z]+)\(|(?P<op>[-+*/&(),<>=]))""", re.U)

    def _formula(self, ws, f):
        toks, i = [], 0
        while i < len(f):
            m = self._TOK.match(f, i)
            if not m:
                if f[i:].strip() == "":
                    break
                raise ValueError("tok")
            i = m.end()
            k = m.lastgroup
            toks.append((k, m.group(k)))
        self._t, self._p, self._ws = toks, 0, ws
        r = self._concat()
        return r

    def _peek(self):
        return self._t[self._p] if self._p < len(self._t) else (None, None)

    def _next(self):
        t = self._peek()
        self._p += 1
        return t

    @staticmethod
    def _num(v):
        if v in (None, ""):
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return v
        return float(str(v).replace(",", "."))

    @staticmethod
    def _txt(v):
        if v is None:
            return ""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    def _concat(self):
        a = self._add()
        while self._peek() == ("op", "&"):
            self._next()
            b = self._add()
            a = self._txt(a) + self._txt(b)
        return a

    def _add(self):
        a = self._mul()
        while self._peek()[0] == "op" and self._peek()[1] in "+-":
            op = self._next()[1]
            b = self._mul()
            a = self._num(a) + self._num(b) if op == "+" else self._num(a) - self._num(b)
        return a

    def _mul(self):
        a = self._unary()
        while self._peek()[0] == "op" and self._peek()[1] in "*/":
            op = self._next()[1]
            b = self._unary()
            if op == "*":
                a = self._num(a) * self._num(b)
            else:
                a = self._num(a) / self._num(b) if self._num(b) else ""
        return a

    def _unary(self):
        if self._peek() == ("op", "-"):
            self._next()
            return -self._num(self._unary())
        if self._peek() == ("op", "+"):
            self._next()
            return self._unary()
        return self._atom()

    def _cells(self, ref):
        ws = self._ws
        if "!" in ref:
            sh, ref = ref.rsplit("!", 1)
            sh = sh[1:-1].replace("''", "'") if sh.startswith("'") else sh
            ws = self.wb[sh]
        ref = ref.replace("$", "").upper()
        a, _, b = ref.partition(":")
        ma, mb = re.match(r"([A-Z]+)(\d+)", a), re.match(r"([A-Z]+)(\d+)", b or a)
        c1, r1, c2, r2 = column_index_from_string(ma.group(1)), int(ma.group(2)), column_index_from_string(mb.group(1)), int(mb.group(2))
        return ws, [(r, c) for r in range(min(r1, r2), max(r1, r2) + 1) for c in range(min(c1, c2), max(c1, c2) + 1)]

    def _atom(self):
        k, v = self._next()
        if k == "num":
            return float(v) if "." in v else int(v)
        if k == "str":
            return v[1:-1].replace('""', '"')
        if k == "ref":
            ws, cells = self._cells(v)
            if len(cells) == 1:
                x = self.value(ws, *cells[0])
                return 0 if x is None else x
            return [self.value(ws, r, c) for r, c in cells]
        if k == "fn":
            args = []
            if self._peek() != ("op", ")"):
                args.append(self._concat())
                while self._peek() == ("op", ","):
                    self._next()
                    args.append(self._concat())
            self._next()
            name = v.upper()
            flat = [x for a in args for x in (a if isinstance(a, list) else [a])]
            nums = [x for x in flat if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if name == "SUM":
                return sum(nums)
            if name == "ROUND":
                return round(self._num(args[0]), int(self._num(args[1])) if len(args) > 1 else 0)
            if name in ("MAX", "MIN"):
                return (max if name == "MAX" else min)(nums) if nums else 0
            raise ValueError("fn")
        if (k, v) == ("op", "("):
            r = self._concat()
            self._next()
            return r
        raise ValueError("atom")


# ---------------------------------------------------------------- εμφάνιση
def _rgb(color, default=None):
    if color is None:
        return default
    try:
        if color.type == "rgb" and isinstance(color.rgb, str) and len(color.rgb) in (6, 8):
            return color.rgb[-6:]
        if color.type == "theme" and color.theme is not None and color.theme < len(_THEME):
            base = _THEME[color.theme]
            t = color.tint or 0
            rgb = [int(base[i:i + 2], 16) for i in (0, 2, 4)]
            rgb = [int(c + (255 - c) * t) if t > 0 else int(c * (1 + t)) for c in rgb]
            return "%02X%02X%02X" % tuple(max(0, min(255, c)) for c in rgb)
        if color.type == "indexed":
            return {8: "000000", 9: "FFFFFF", 22: "C0C0C0", 23: "808080"}.get(color.indexed, default)
    except Exception:
        pass
    return default


def _fmt(v, nf):
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "ΝΑΙ" if v else "ΌΧΙ"
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, (int, float)):
        nf = nf or "General"
        pct = "%" in nf
        if pct:
            v = v * 100
        dec = 0
        m = re.search(r"0\.(0+)", nf)
        if m:
            dec = len(m.group(1))
        elif nf == "General":
            if float(v) == int(v):
                return str(int(v))
            return ("%.4f" % v).rstrip("0").rstrip(".").replace(".", ",")
        s = f"{abs(v):,.{dec}f}"
        s = s.replace(",", "§").replace(".", ",").replace("§", ".") if ("#,##" in nf or dec) else s.replace(".", ",")
        if "," not in nf and "#,##" not in nf and dec == 0:
            s = f"{abs(v):.0f}"
        return ("-" if v < 0 and float(s.replace(".", "").replace(",", ".") or 0) != 0 else "") + s + ("%" if pct else "")
    return str(v)


def _px(w):
    return (w * 7 + 5) * 0.75


def _sheet_geom(ws):
    fmt = ws.sheet_format
    dcw = fmt.defaultColWidth or fmt.baseColWidth or 8.43
    drh = fmt.defaultRowHeight or 15
    widths, hidden_c = {}, set()
    for key, d in ws.column_dimensions.items():
        lo, hi = (d.min or column_index_from_string(key)), (d.max or column_index_from_string(key))
        for c in range(lo, min(hi, 400) + 1):
            if d.hidden:
                hidden_c.add(c)
            if d.width:
                widths[c] = d.width
    return dcw, drh, widths, hidden_c


def _bbox(ws):
    if ws.print_area:
        try:
            a = ws.print_area if isinstance(ws.print_area, str) else str(ws.print_area)
            a = a.split(",")[0].split("!")[-1].replace("$", "")
            p, _, q = a.partition(":")
            m1, m2 = re.match(r"([A-Z]+)(\d+)", p), re.match(r"([A-Z]+)(\d+)", q or p)
            return int(m1.group(2)), column_index_from_string(m1.group(1)), int(m2.group(2)), column_index_from_string(m2.group(1))
        except Exception:
            pass
    r1 = c1 = 10 ** 9
    r2 = c2 = 0
    for (r, c), cell in ws._cells.items():
        b = cell.border
        used = cell.value is not None or (cell.fill is not None and cell.fill.fill_type == "solid") or any(getattr(b, s) is not None and getattr(b, s).style for s in ("left", "right", "top", "bottom"))
        if used:
            r1, c1, r2, c2 = min(r1, r), min(c1, c), max(r2, r), max(c2, c)
    for mr in ws.merged_cells.ranges:
        r2, c2 = max(r2, mr.max_row), max(c2, mr.max_col)
    if r2 == 0:
        return None
    return 1, 1, r2, c2


def xlsx_to_pdf(xlsx_path: str, pdf_path: str) -> None:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import simpleSplit
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    reg, bold = _fonts()
    wb = load_workbook(xlsx_path)
    ev = _Eval(wb)
    cv = canvas.Canvas(pdf_path)
    pages = 0
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        bb = _bbox(ws)
        if not bb:
            continue
        r1, c1, r2, c2 = bb
        dcw, drh, widths, hidden_c = _sheet_geom(ws)
        cols = [c for c in range(c1, c2 + 1) if c not in hidden_c]
        rows = [r for r in range(r1, r2 + 1) if not (ws.row_dimensions[r].hidden)]
        cw = {c: _px(widths.get(c, dcw)) for c in cols}
        rh = {r: (ws.row_dimensions[r].height or drh) for r in rows}
        total_w = sum(cw.values()) or 1
        landscape_ = (ws.page_setup.orientation or "portrait") == "landscape"
        pw, ph = landscape(A4) if landscape_ else A4
        mg = 22
        s = min((pw - 2 * mg) / total_w, 1.6)
        pr = ws.sheet_properties.pageSetUpPr
        if pr is not None and pr.fitToPage and ws.page_setup.fitToHeight in (None, 1):      # «Προσαρμογή σε 1 σελίδα» (όπως στο Excel)
            s = min(s, 0.995 * (ph - 2 * mg) / (sum(rh.values()) or 1))
        avail_h = (ph - 2 * mg) / s
        x0 = {}
        acc = 0
        for c in cols:
            x0[c] = acc
            acc += cw[c]
        # σελιδοποίηση γραμμών
        chunks, cur, h = [], [], 0
        for r in rows:
            if cur and h + rh[r] > avail_h:
                chunks.append(cur)
                cur, h = [], 0
            cur.append(r)
            h += rh[r]
        if cur:
            chunks.append(cur)
        colset = set(cols)
        for chunk in chunks:
            cv.setPageSize((pw, ph))
            # συγχωνευμένα κελιά: ο «άγκυρας» είναι το πρώτο ορατό κελί (αν η πάνω-αριστερή στήλη/γραμμή είναι κρυφή, το κείμενο φαίνεται στο ορατό κομμάτι)
            cset = set(chunk)
            merged, covered = {}, set()
            for mr in ws.merged_cells.ranges:
                vr = [x for x in range(mr.min_row, mr.max_row + 1) if x in cset]
                vc = [x for x in range(mr.min_col, mr.max_col + 1) if x in colset]
                for rr in range(mr.min_row, mr.max_row + 1):
                    for cc in range(mr.min_col, mr.max_col + 1):
                        covered.add((rr, cc))
                if vr and vc:
                    covered.discard((vr[0], vc[0]))
                    merged[(vr[0], vc[0])] = (mr, vr, vc)
            y0 = {}
            acc = 0
            for r in chunk:
                y0[r] = acc
                acc += rh[r]
            cv.saveState()
            cv.translate(mg, ph - mg)
            cv.scale(s, -s)      # y προς τα κάτω όπως στο Excel· το κείμενο ξανα-αντιστρέφεται όταν σχεδιάζεται
            rowset = set(chunk)

            def rect_of(r, c):
                m = merged.get((r, c))
                if m:
                    return x0[c], y0[r], sum(cw[x] for x in m[2]), sum(rh[y] for y in m[1])
                return x0[c], y0[r], cw[c], rh[r]

            def src(r, c):      # κελί από το οποίο διαβάζεται η τιμή/μορφή
                m = merged.get((r, c))
                return (m[0].min_row, m[0].min_col) if m else (r, c)

            def edges(r, c):
                m = merged.get((r, c))
                if not m:
                    b = ws.cell(r, c).border
                    return b.left, b.right, b.top, b.bottom
                mr = m[0]
                return ws.cell(mr.min_row, mr.min_col).border.left, ws.cell(mr.min_row, mr.max_col).border.right, ws.cell(mr.min_row, mr.min_col).border.top, ws.cell(mr.max_row, mr.min_col).border.bottom

            # 1) φόντα
            for r in chunk:
                for c in cols:
                    if (r, c) in covered:
                        continue
                    cell = ws.cell(*src(r, c))
                    if cell.fill is not None and cell.fill.fill_type == "solid":
                        col = _rgb(cell.fill.fgColor)
                        if col:
                            x, y, w, hh = rect_of(r, c)
                            cv.setFillColor(HexColor("#" + col))
                            cv.rect(x, y, w, hh, stroke=0, fill=1)
            # 2) κείμενο
            for r in chunk:
                for c in cols:
                    if (r, c) in covered:
                        continue
                    sr, sc = src(r, c)
                    cell = ws.cell(sr, sc)
                    v = ev.value(ws, sr, sc)
                    txt = _fmt(v, cell.number_format)
                    if not txt:
                        continue
                    x, y, w, hh = rect_of(r, c)
                    f = cell.font
                    size = float(f.sz or 11) * 0.78
                    fname = bold if f.b else reg
                    fcol = _rgb(f.color, "000000") or "000000"
                    al = cell.alignment
                    horiz = al.horizontal or ("right" if isinstance(v, (int, float)) and not isinstance(v, bool) else "left")
                    vert = al.vertical or "bottom"
                    wrap = bool(al.wrap_text) or "\n" in txt
                    pad = 2
                    if wrap:
                        lines = []
                        for part in txt.split("\n"):
                            lines += simpleSplit(part, fname, size, max(4, w - 2 * pad)) or [""]
                    else:
                        lines = [txt]
                    lh = size * 1.18
                    th = lh * len(lines)
                    ty = y + (pad if vert == "top" else (hh - th - pad if vert == "bottom" else (hh - th) / 2))
                    # ελεύθερος χώρος δεξιά για μη τυλιγμένο κείμενο αριστερής στοίχισης
                    ext = w
                    if not wrap and horiz in ("left", "general"):
                        cc = c + 1
                        while cc in colset and (r, cc) not in covered and ev.value(ws, r, cc) in (None, "") and (r, cc) not in merged and c + 1 <= cc and ext < 3 * pw:
                            ext += cw[cc]
                            cc += 1
                    cv.saveState()
                    p = cv.beginPath()
                    p.rect(x, y, ext if horiz == "left" else w, hh)
                    cv.clipPath(p, stroke=0, fill=0)
                    cv.setFillColor(HexColor("#" + fcol))
                    cv.setFont(fname, size)
                    for i, ln in enumerate(lines):
                        by = ty + lh * i + size * 0.95
                        tw = cv.stringWidth(ln, fname, size)
                        tx = x + pad if horiz in ("left", "general", "fill") else (x + w - pad - tw if horiz == "right" else x + (w - tw) / 2)
                        cv.saveState()
                        cv.translate(tx, by)
                        cv.scale(1, -1)
                        cv.drawString(0, 0, ln)
                        cv.restoreState()
                    cv.restoreState()
            # 3) γραμμές πλαισίου
            for r in chunk:
                for c in cols:
                    if (r, c) in covered:
                        continue
                    x, y, w, hh = rect_of(r, c)
                    bl, br_, bt, bb_ = edges(r, c)
                    for side, sd, (xa, ya, xb, yb) in (("left", bl, (x, y, x, y + hh)), ("right", br_, (x + w, y, x + w, y + hh)), ("top", bt, (x, y, x + w, y)), ("bottom", bb_, (x, y + hh, x + w, y + hh))):
                        if sd is not None and sd.style:
                            cv.setStrokeColor(HexColor("#" + (_rgb(sd.color, "000000") or "000000")))
                            cv.setLineWidth({"thin": 0.5, "hair": 0.3, "medium": 1.1, "thick": 1.6, "double": 1.2}.get(sd.style, 0.5))
                            cv.line(xa, ya, xb, yb)
            cv.restoreState()
            cv.showPage()
            pages += 1
    if not pages:
        cv.setPageSize(A4)
        cv.showPage()
    cv.save()
