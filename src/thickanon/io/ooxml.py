"""Read and write the text of an Office Open XML file (docx, xlsx, pptx) part by part.

python-docx, python-pptx and openpyxl each expose only the main body of a
document. Headers, footers, comments, notes, text boxes, tracked changes,
charts, link targets and the document properties stayed in the file
unchanged, so personal data in them leaked. openpyxl also drops content it
does not model when it saves.

This module works on the XML parts in the zip instead. It collects every place
that holds text as a slot, in a fixed order, and returns the slot texts as the
fragments. Writing parses the same file again, collects the same slots and
changes only the slots whose text changed; every other byte of every other part
is copied as it is. Office files embedded in the file (a chart's workbook, an
OLE object) are handled the same way, recursively.

Some fields identify a person by definition and no detector would reliably
find them: author names, initials, user IDs and the document properties. They
are cleared on every write instead of being offered as fragments.
"""
import bisect
import difflib
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
EXT = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
XLSX_THREADED = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_EMBEDDED_PACKAGES = (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm")
_MAX_DEPTH = 3

# Excel forbids [ and ] in sheet names, so a token in a sheet name is stored
# with these look-alike brackets and turned back into [ ] when it is read.
_SHEET_BRACKETS = str.maketrans("[]", "⟦⟧")
_SHEET_BRACKETS_BACK = str.maketrans("⟦⟧", "[]")
_SHEET_NAME_MAX = 31

# [ and ] are reserved in a URI, so a token in a link target is stored
# percent-encoded and decoded again when it is read.
_URI_BRACKETS = {ord("["): "%5B", ord("]"): "%5D"}


def _uri_brackets_back(value):
    return re.sub(r"%5[Bb]", "[", re.sub(r"%5[Dd]", "]", value))

# Elements whose whole text is cleared on write. Values are kept empty rather
# than removed so the part stays valid against its schema.
_CLEARED_TEXT = {
    f"{{{DC}}}creator", f"{{{CP}}}lastModifiedBy", f"{{{DC}}}title",
    f"{{{DC}}}subject", f"{{{CP}}}keywords", f"{{{DC}}}description",
    f"{{{CP}}}category", f"{{{CP}}}contentStatus",
    f"{{{EXT}}}Company", f"{{{EXT}}}Manager", f"{{{EXT}}}HyperlinkBase",
}
# (attribute, replacement) cleared wherever they occur in these namespaces.
_CLEARED_ATTRS = {
    f"{{{W}}}author": "Author", f"{{{W}}}initials": "A",
    f"{{{W15}}}author": "Author", f"{{{W15}}}userId": "", f"{{{W15}}}providerId": "None",
}

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True,
                          remove_blank_text=False)


# --------------------------------------------------------------------------- slots

class _Part:
    def __init__(self, name, root):
        self.name, self.root, self.dirty = name, root, False


class _GroupSlot:
    """Text spread over several elements, such as the runs of one paragraph.

    Writing keeps every element and changes only the characters that changed,
    so the formatting of untouched runs survives. Inserted text goes to the
    element that held the first replaced character.
    """
    _MIN_EQUAL = 4   # shorter matches inside a change are not worth splitting it

    def __init__(self, part, elements, preserve_space):
        self.part, self.elements, self.preserve_space = part, elements, preserve_space

    def get(self):
        return "".join(e.text or "" for e in self.elements)

    def set(self, new):
        old = self.get()
        if new == old:
            return
        texts = [e.text or "" for e in self.elements]
        if len(self.elements) == 1:
            pieces = [new]
        else:
            pieces = _distribute(old, new, texts, self._MIN_EQUAL)
        for element, before, after in zip(self.elements, texts, pieces):
            if before != after:
                element.text = after
                if self.preserve_space:
                    element.set(XML_SPACE, "preserve")
        self.part.dirty = True


class _AttrSlot:
    def __init__(self, part, element, attr, encode=None, decode=None):
        self.part, self.element, self.attr = part, element, attr
        self.encode, self.decode = encode, decode

    def get(self):
        value = self.element.get(self.attr) or ""
        return self.decode(value) if self.decode else value

    def set(self, new):
        if new == self.get():
            return
        self.element.set(self.attr, self.encode(new) if self.encode else new)
        self.part.dirty = True


class _Segments:
    """An element whose text is split into pieces, some of them slots.

    Used where only parts of a text may change: the string literals of a
    formula, or the text between the &-codes of a sheet header.
    """

    def __init__(self, part, element, pieces, render=None):
        self.part, self.element, self.pieces = part, element, pieces  # [(is_slot, text)]
        self.render = render or (lambda text: text)

    def flush(self):
        new = "".join(self.render(text) if is_slot else text for is_slot, text in self.pieces)
        if new != (self.element.text or ""):
            self.element.text = new
            self.part.dirty = True


class _SegmentSlot:
    def __init__(self, segments, index):
        self.segments, self.index = segments, index

    def get(self):
        return self.segments.pieces[self.index][1]

    def set(self, new):
        self.segments.pieces[self.index] = (True, new)


def _distribute(old, new, texts, min_equal):
    """Split new over the elements whose texts concatenate to old."""
    starts, pos = [], 0
    for text in texts:
        starts.append(pos)
        pos += len(text)

    def owner(i):
        return max(0, bisect.bisect_right(starts, min(i, max(0, len(old) - 1))) - 1)

    ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    # Merge short equal runs inside a change, so a token is not cut into
    # pieces just because it shares a letter with the text it replaces.
    merged = []
    for tag, i1, i2, j1, j2 in ops:
        short_equal = tag == "equal" and (i2 - i1) < min_equal and merged and merged[-1][0] != "equal"
        if tag != "equal" or short_equal:
            if merged and merged[-1][0] == "change":
                _, a1, _, b1, _ = merged[-1]
                merged[-1] = ("change", a1, i2, b1, j2)
            else:
                merged.append(("change", i1, i2, j1, j2))
        else:
            merged.append(("equal", i1, i2, j1, j2))

    out = [[] for _ in texts]
    for tag, i1, i2, j1, j2 in merged:
        if tag == "equal":
            k = i1
            while k < i2:
                o = owner(k)
                end = min(i2, starts[o] + len(texts[o]))
                if end <= k:          # empty element at k: move to the next one
                    end = k + 1
                out[o].append(old[k:end])
                k = end
        elif j2 > j1:
            out[owner(i1)].append(new[j1:j2])
    pieces = ["".join(p) for p in out]
    if "".join(pieces) != new:
        raise RuntimeError("internal error: the new text was not split over its runs exactly")
    return pieces


# ------------------------------------------------------------------- formula text

_FORMULA_STRING = re.compile(r'"((?:[^"]|"")*)"')


def _formula_pieces(text):
    pieces, pos = [], 0
    for m in _FORMULA_STRING.finditer(text):
        pieces.append((False, text[pos:m.start()]))
        pieces.append((True, m.group(1).replace('""', '"')))
        pos = m.end()
    pieces.append((False, text[pos:]))
    return pieces


def _quote(literal):
    return '"' + literal.replace('"', '""') + '"'


# &L &C &R, fonts &"Arial,Bold", sizes &12, colours &K..., fields &P &N &D &T &F &A &Z &G
_HEADER_CODE = re.compile(r'&(?:"[^"]*"|K[0-9A-Fa-f]{6}|K\d\d[+-]\d{3}|\d+|.)', re.S)


def _header_pieces(text):
    pieces, pos = [], 0
    for m in _HEADER_CODE.finditer(text):
        if m.start() > pos:
            pieces.append((True, text[pos:m.start()]))
        pieces.append((False, m.group()))
        pos = m.end()
    if pos < len(text):
        pieces.append((True, text[pos:]))
    return pieces


def _rename_sheet_references(text, renames):
    for old, new in renames.items():
        quoted_new = "'" + new.replace("'", "''") + "'"
        quoted_old = "'" + old.replace("'", "''") + "'"
        text = text.replace(quoted_old + "!", quoted_new + "!")
        text = re.sub(r"(?<![\w.'\]])" + re.escape(old) + "!", lambda _m: quoted_new + "!", text)
    return text


# --------------------------------------------------------------------- collecting

def _nearest(element, tag):
    parent = element.getparent()
    while parent is not None and parent.tag != tag:
        parent = parent.getparent()
    return parent


def _paragraph_groups(part, paragraph_tag, text_tags, preserve_space):
    """One slot per paragraph and text kind, for text whose nearest paragraph it is.

    A text box sits inside a run of its anchor paragraph, so a paragraph can
    contain other paragraphs. Their text belongs to them, not to the outer one.
    """
    slots = []
    for paragraph in part.root.iter(paragraph_tag):
        if _is_prompt_text(part, paragraph):
            continue
        for tag in text_tags:
            elements = [t for t in paragraph.iter(tag)
                        if _nearest(t, paragraph_tag) is paragraph and not _is_generated_field_text(t)]
            if elements:
                slots.append(_GroupSlot(part, elements, preserve_space))
    return slots


# Masters and layouts of a presentation carry prompt text such as "Click to
# edit Master title style" in their placeholders. It is the same in every file
# and only adds noise to the review. Footer and date placeholders and free text
# boxes on a master hold real content (a company name), so they stay.
_TEMPLATE_PART = re.compile(r"ppt/(slideMasters|slideLayouts|notesMasters|handoutMasters)/[^/]+\.xml$")
_TEMPLATE_CONTENT_PLACEHOLDERS = {"ftr", "dt"}


def _is_generated_field_text(t):
    """Text of a date or slide-number field, which PowerPoint regenerates."""
    parent = t.getparent()
    return (parent is not None and parent.tag == f"{{{A}}}fld"
            and (parent.get("type") or "").startswith(("datetime", "slidenum")))


def _is_prompt_text(part, paragraph):
    if not _TEMPLATE_PART.match(part.name):
        return False
    shape = _nearest(paragraph, f"{{{P}}}sp")
    if shape is None:
        return False
    placeholder = shape.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
    return placeholder is not None and placeholder.get("type") not in _TEMPLATE_CONTENT_PLACEHOLDERS


def _text_group(part, container, preserve_space=True):
    """The t elements of a shared string, inline string or comment, without phonetics."""
    elements = [t for t in container.iter(f"{{{S}}}t") if _nearest(t, f"{{{S}}}rPh") is None]
    return [_GroupSlot(part, elements, preserve_space)] if elements else []


class _Package:
    def __init__(self, data: bytes, depth=0):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.infos = z.infolist()
            self.raw = {i.filename: z.read(i.filename) for i in self.infos}
        self.parts: dict[str, _Part] = {}
        self.children: dict[str, _Package] = {}
        self.slots = []
        self.segments: list[_Segments] = []
        self.sheet_slots = []
        self.renames: dict[str, str] = {}
        for info in self.infos:
            name = info.filename
            lower = name.lower()
            if lower.endswith((".xml", ".rels")) and name != "[Content_Types].xml":
                try:
                    root = etree.fromstring(self.raw[name], _PARSER)
                except etree.XMLSyntaxError:
                    continue
                part = _Part(name, root)
                self.parts[name] = part
                self._collect(part)
            elif lower.endswith(_EMBEDDED_PACKAGES) and depth < _MAX_DEPTH:
                try:
                    child = _Package(self.raw[name], depth + 1)
                except zipfile.BadZipFile:
                    continue
                self.children[name] = child
                self.slots.extend(child.slots)

    # One fixed order: parts in zip order, slots in document order within a part.
    def _collect(self, part):
        root = part.root
        slots = self.slots
        slots += _paragraph_groups(part, f"{{{W}}}p",
                                   [f"{{{W}}}t", f"{{{W}}}delText", f"{{{W}}}instrText"], True)
        slots += _paragraph_groups(part, f"{{{A}}}p", [f"{{{A}}}t"], False)
        for el in root.iter(f"{{{W}}}fldSimple"):
            if el.get(f"{{{W}}}instr"):
                slots.append(_AttrSlot(part, el, f"{{{W}}}instr"))
        for el in root.iter(f"{{{W}}}hyperlink"):
            if el.get(f"{{{W}}}tooltip"):
                slots.append(_AttrSlot(part, el, f"{{{W}}}tooltip"))

        # Spreadsheet text
        for tag in (f"{{{S}}}si", f"{{{S}}}is"):
            for el in root.iter(tag):
                slots += _text_group(part, el)
        for el in root.iter(f"{{{S}}}comment"):
            for text in el.iter(f"{{{S}}}text"):
                slots += _text_group(part, text)
        for el in root.iter(f"{{{XLSX_THREADED}}}text"):
            if el.text:
                slots.append(_GroupSlot(part, [el], False))
        for el in root.iter(f"{{{S}}}c"):
            if el.get("t") == "str":
                v = el.find(f"{{{S}}}v")
                if v is not None and v.text:
                    slots.append(_GroupSlot(part, [v], False))
        for tag in ("f", "formula", "formula1", "formula2", "definedName"):
            for el in root.iter(f"{{{S}}}{tag}"):
                if el.text and '"' in el.text:
                    seg = _Segments(part, el, _formula_pieces(el.text), render=_quote)
                    self.segments.append(seg)
                    slots += [_SegmentSlot(seg, i) for i, (s, _) in enumerate(seg.pieces) if s]
        for tag in ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter"):
            for el in root.iter(f"{{{S}}}{tag}"):
                if el.text:
                    seg = _Segments(part, el, _header_pieces(el.text))
                    self.segments.append(seg)
                    slots += [_SegmentSlot(seg, i) for i, (s, t) in enumerate(seg.pieces)
                              if s and t.strip()]
        for el in root.iter(f"{{{S}}}hyperlink"):
            for attr in ("display", "tooltip"):
                if el.get(attr):
                    slots.append(_AttrSlot(part, el, attr))
        if root.tag == f"{{{S}}}workbook":
            for el in root.iter(f"{{{S}}}sheet"):
                slot = _AttrSlot(part, el, "name",
                                 encode=lambda v: v.translate(_SHEET_BRACKETS),
                                 decode=lambda v: v.translate(_SHEET_BRACKETS_BACK))
                slot.original = el.get("name")
                slots.append(slot)
                self.sheet_slots.append(slot)

        # Chart caches hold a copy of the cells the chart shows.
        for el in root.iter(f"{{{C}}}v"):
            if _nearest(el, f"{{{C}}}strCache") is not None or _nearest(el, f"{{{C}}}multiLvlStrCache") is not None:
                if el.text:
                    slots.append(_GroupSlot(part, [el], False))

        # Legacy PowerPoint comments
        for el in root.iter(f"{{{P}}}text"):
            if el.text:
                slots.append(_GroupSlot(part, [el], False))

        # Alt text of pictures and shapes
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.rsplit("}", 1)[-1] in ("docPr", "cNvPr"):
                for attr in ("descr", "title"):
                    if el.get(attr):
                        slots.append(_AttrSlot(part, el, attr))

        # Targets of external links: mailto:, URLs, file paths
        if root.tag == f"{{{PKG_REL}}}Relationships":
            for el in root.iter(f"{{{PKG_REL}}}Relationship"):
                if el.get("TargetMode") == "External" and el.get("Target"):
                    slots.append(_AttrSlot(part, el, "Target",
                                           encode=lambda v: v.translate(_URI_BRACKETS),
                                           decode=_uri_brackets_back))

    # ----------------------------------------------------------------- writing

    def _clear_identity(self):
        for part in self.parts.values():
            root = part.root
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                if el.tag in _CLEARED_TEXT and el.text:
                    el.text, part.dirty = "", True
                for attr, value in _CLEARED_ATTRS.items():
                    if el.get(attr) not in (None, value):
                        el.set(attr, value)
                        part.dirty = True
                local = el.tag.rsplit("}", 1)[-1]
                if local in ("cmAuthor", "author") and el.tag != f"{{{S}}}author" and el.get("name"):
                    for attr, value in (("name", "Author"), ("initials", "A"), ("userId", "")):
                        if el.get(attr) not in (None, value):
                            el.set(attr, value)
                            part.dirty = True
                if local == "person" and el.get("displayName"):
                    for attr, value in (("displayName", "Author"), ("userId", "")):
                        if el.get(attr) not in (None, value):
                            el.set(attr, value)
                            part.dirty = True
            # Spreadsheet comment authors are element text.
            for el in root.iter(f"{{{S}}}author"):
                if el.text != "Author":
                    el.text, part.dirty = "Author", True
            # Sheet names and slide titles listed in app.xml, custom properties.
            if root.tag == f"{{{EXT}}}Properties":
                for el in root.iter(f"{{{VT}}}lpstr", f"{{{VT}}}lpwstr"):
                    if _nearest(el, f"{{{EXT}}}TitlesOfParts") is not None and el.text:
                        el.text, part.dirty = "", True
            if root.tag == f"{{{CUSTOM}}}Properties":
                for el in root.iter(f"{{{VT}}}lpstr", f"{{{VT}}}lpwstr", f"{{{VT}}}bstr"):
                    if el.text:
                        el.text, part.dirty = "", True

    def _apply_sheet_renames(self, renames):
        if not renames:
            return
        formula_tags = {f"{{{S}}}{t}" for t in ("f", "formula", "formula1", "formula2", "definedName")}
        formula_tags.add(f"{{{C}}}f")
        for part in self.parts.values():
            for el in part.root.iter():
                if el.tag in formula_tags and el.text:
                    new = _rename_sheet_references(el.text, renames)
                    if new != el.text:
                        el.text, part.dirty = new, True
                elif el.tag == f"{{{S}}}hyperlink" and el.get("location"):
                    new = _rename_sheet_references(el.get("location"), renames)
                    if new != el.get("location"):
                        el.set("location", new)
                        part.dirty = True
                elif el.tag == f"{{{S}}}worksheetSource" and el.get("sheet") in renames:
                    el.set("sheet", renames[el.get("sheet")])
                    part.dirty = True

    def _serialize(self) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for info in self.infos:
                name = info.filename
                data = self.raw[name]
                if name in self.parts and self.parts[name].dirty:
                    data = etree.tostring(self.parts[name].root, xml_declaration=True,
                                          encoding="UTF-8", standalone=True)
                elif name in self.children:
                    data = self.children[name].finished
                z.writestr(info, data)
        return out.getvalue()


# ------------------------------------------------------------------------- API

def read_fragments(path) -> list[str]:
    package = _Package(Path(path).read_bytes())
    return [slot.get() for slot in _nonempty(package)]


def _nonempty(package):
    return [slot for slot in package.slots if slot.get().strip()]


def write_fragments(path, fragments: list[str]) -> None:
    path = Path(path)
    package = _Package(path.read_bytes())
    slots = _nonempty(package)
    if len(fragments) != len(slots):
        raise ValueError(
            f"Fragment count mismatch: expected {len(slots)} fragments, "
            f"got {len(fragments)}"
        )
    for slot, value in zip(slots, fragments):
        slot.set(value)
    data = _finish(package)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _finish(package) -> bytes:
    """Flush pending edits in package and its embedded packages, then zip it."""
    renames = {}
    for child in package.children.values():
        child.finished = _finish(child)
        # A chart in this package refers to the sheets of its embedded workbook.
        renames.update(child.renames)
    for seg in package.segments:
        seg.flush()
    for slot in package.sheet_slots:
        old = slot.original
        new = slot.element.get("name")
        if new != old:
            if len(new) > _SHEET_NAME_MAX:
                raise ValueError(
                    f"the anonymized sheet name {new!r} is longer than the "
                    f"{_SHEET_NAME_MAX} characters Excel allows")
            renames[old] = new
            package.renames[old] = new
    package._apply_sheet_renames(renames)
    package._clear_identity()
    return package._serialize()


