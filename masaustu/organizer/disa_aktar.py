"""2.3.0 — Dışa aktarma: Excel (.xlsx) ve CSV. Ek kütüphane gerektirmez (xlsx = elle yazılan küçük bir zip).
Telefonda aynı biçim ek230.js içinde üretilir."""
import csv
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from .db import is_receipt

COLUMNS = [  # (anahtar, Türkçe başlık, genişlik)
    ("name", "Adı", 34), ("quantity", "Adet", 8), ("category_path", "Kategori", 26), ("location_path", "Yer", 26),
    ("price", "Fiyat", 12), ("currency", "Para birimi", 11), ("created_at", "Ekleme tarihi", 18),
    ("shop_name", "Dükkan/Kişi Adı", 24), ("shop_place", "Dükkan/Kişi Yeri", 24), ("shop_phone", "İletişim numarası", 18),
    ("warranty_until", "Garanti bitişi", 14), ("expires_on", "Son kullanma tarihi", 14), ("min_qty", "En az adet", 10),
    ("loan_to", "Ödünç", 18), ("loan_due", "Dönüş günü", 12), ("photo_count", "Fotoğraf", 9), ("receipt_count", "Fatura / fiş", 10),
    ("notes", "Notlar", 50),
]
NUMERIC = {"quantity", "price", "min_qty", "photo_count", "receipt_count"}


def table(items, t):
    """(başlıklar, satırlar, genişlikler) — satırlar ham değerlerdir (sayılar sayı olarak kalır)."""
    head = [t(c[1]).rstrip(":") for c in COLUMNS]
    rows = []
    for d in items:
        photos = d.get("photos")
        pc = d.get("photo_count") if photos is None else len([p for p in photos if not is_receipt(p)])
        rc = d.get("receipt_count") if photos is None else len([p for p in photos if is_receipt(p)])
        vals = {**d, "photo_count": pc or 0, "receipt_count": rc or 0}
        row = []
        for key, _l, _w in COLUMNS:
            v = vals.get(key)
            if key in NUMERIC:
                row.append(v if isinstance(v, (int, float)) else (None if v in (None, "") else v))
            else:
                row.append("" if v is None else str(v))
        rows.append(row)
    return head, rows, [c[2] for c in COLUMNS]


def write_csv(path, head, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
    return path


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, v, style=0):
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return f'<c r="{ref}"{st}/>'
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    text = escape(str(v)).replace("\n", "&#10;")
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{text}</t></is></c>'


def xlsx_bytes(head, rows, widths=None, sheet="Organizer", rtl=False, title=""):
    """En küçük geçerli Excel dosyası (tek sayfa, kalın başlık, dondurulmuş ilk satır, otomatik filtre)."""
    start = 2 if title else 1
    data = []
    if title:
        data.append(f'<row r="1">{_cell("A1", title, 2)}</row>')
    data.append(f'<row r="{start}">' + "".join(_cell(f"{_col(i)}{start}", h, 1) for i, h in enumerate(head)) + "</row>")
    for n, r in enumerate(rows, start=start + 1):
        data.append(f'<row r="{n}">' + "".join(_cell(f"{_col(i)}{n}", v, 3 if isinstance(v, float) else 0)
                                              for i, v in enumerate(r)) + "</row>")
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths or []))
    last = f"{_col(max(len(head) - 1, 0))}{start + len(rows)}"
    sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 f'<sheetViews><sheetView workbookViewId="0"{" rightToLeft=" + chr(34) + "1" + chr(34) if rtl else ""}>'
                 f'<pane ySplit="{start}" topLeftCell="A{start + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                 + (f"<cols>{cols}</cols>" if cols else "") + f'<sheetData>{"".join(data)}</sheetData>'
                 f'<autoFilter ref="A{start}:{last}"/></worksheet>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
              '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
              '<font><b/><sz val="14"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FF1D5F74"/></patternFill></fill></fills>'
              '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="4"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/>'
              '<xf fontId="2" applyFont="1"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    name = escape((sheet or "Organizer")[:31].replace("/", "-"))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
        f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">\'{name}\'!$A${start}:${_col(max(len(head) - 1, 0))}${start + len(rows)}</definedName></definedNames>'
        '</workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
        "xl/styles.xml": styles,
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def write_xlsx(path, head, rows, widths=None, sheet="Organizer", rtl=False, title=""):
    with open(path, "wb") as f:
        f.write(xlsx_bytes(head, rows, widths, sheet, rtl, title))
    return path


def default_name(ext):
    return f"Organizer-{datetime.now():%Y-%m-%d}.{ext}"
