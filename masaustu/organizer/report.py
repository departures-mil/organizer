"""Döküm: bir kategorideki ya da bir yerdeki bütün eşyaların tek sayfada listesi.
Ekranda görülebilir, yazdırılabilir ya da PDF olarak kaydedilebilir."""
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QTextBrowser, QVBoxLayout)

from . import i18n
from .common import fmt_date, fmt_price, info, load_image
from .db import CURRENCIES
from .i18n import t

UNASSIGNED = -1


def build_report(db, table, node_id, with_photos=True):
    """HTML ve gömülecek küçük resimleri döndürür: (başlık, html, {ad: QImage})."""
    key = "category_id" if table == "categories" else "location_id"
    other_path = "location_path" if table == "categories" else "category_path"
    if node_id is None:
        ids, scope = None, (t("Bütün kategoriler") if table == "categories" else t("Bütün yerler"))
    elif node_id == UNASSIGNED:
        ids, scope = {None}, t("Belirtilmemiş")
    else:
        ids, scope = db.descendants(table, node_id), db.tree_paths(table).get(node_id, "")
    items = db.list_items(**{("category_ids" if table == "categories" else "location_ids"): ids}, sort="name_asc")

    order = {nid: i for i, (nid, *_rest) in enumerate(db.tree_ordered(table))}
    groups = {}
    for d in items:
        groups.setdefault(d[key], []).append(d)
    group_ids = sorted(groups, key=lambda g: (g is None, order.get(g, 0)))

    title = t("Döküm: {scope}", scope=scope)
    total_qty = sum(d["quantity"] for d in items)
    totals = db.totals_by_currency(items)
    value = " + ".join(fmt_price(totals[c], c) for c, *_ in CURRENCIES if c in totals)
    other_label = t("Yer") if table == "categories" else t("Kategori")
    rtl = i18n.is_rtl()
    align = "right" if rtl else "left"

    images = {}
    h = [f'<html dir="{"rtl" if rtl else "ltr"}"><head><style>'
         f'body {{ font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif; color: #20323a; }}'
         f'h1 {{ color: #1d5f74; font-size: 20pt; margin: 0; }}'
         f'h2 {{ color: #1d5f74; font-size: 13pt; margin-top: 16px; margin-bottom: 4px; }}'
         f'.muted {{ color: #6b8590; }}'
         f'th {{ background: #e6f3f1; color: #1d5f74; padding: 5px; text-align: {align}; }}'
         f'td {{ padding: 4px 5px; border-bottom: 1px solid #e1e8ea; vertical-align: middle; }}'
         f'</style></head><body>',
         f'<h1>{escape(title)}</h1>',
         f'<p class="muted">{escape(t("Organizer"))} · {datetime.now():%d.%m.%Y %H:%M} · '
         f'{escape(t("{n} eşya · toplam {q} adet", n=len(items), q=total_qty))}'
         + (f' · {escape(t("Değer:"))} {escape(value)}' if value else "") + '</p>']
    if not items:
        h.append(f'<p>{escape(t("Bu bölümde kayıtlı eşya yok."))}</p>')
    paths = db.tree_paths(table)
    for g in group_ids:
        rows = groups[g]
        name = paths.get(g) or t("Belirtilmemiş")
        q = sum(d["quantity"] for d in rows)
        h.append(f'<h2>{escape(name)} <span class="muted" style="font-size:10pt">· '
                 f'{escape(t("{n} eşya · toplam {q} adet", n=len(rows), q=q))}</span></h2>')
        h.append('<table width="100%" cellspacing="0">')
        head = ([("", "64")] if with_photos else []) + [(t("Adı"), "28%"), (t("Adet"), "8%"), (other_label, "24%"),
                                                     (t("Fiyat"), "14%"), (t("Notlar"), "")]
        h.append("<tr>" + "".join(f'<th{f" width={chr(34)}{w}{chr(34)}" if w else ""}>{escape(x)}</th>'
                                  for x, w in head) + "</tr>")
        for d in rows:
            cells = []
            if with_photos:
                if d["photo"]:
                    img = load_image(db.photos_dir / d["photo"], 120)
                    if not img.isNull():
                        images[d["photo"]] = img
                        cells.append(f'<td width="64"><img src="foto://{escape(d["photo"])}" width="56"></td>')
                    else:
                        cells.append("<td></td>")
                else:
                    cells.append('<td width="64"></td>')
            cells += [f'<td><b>{escape(d["name"])}</b><br><span class="muted" style="font-size:8pt">'
                      f'{escape(fmt_date(d["created_at"]))}</span></td>',
                      f'<td><b>{d["quantity"]}</b></td>',
                      f'<td>{escape(d[other_path] or "—")}</td>',
                      f'<td>{escape(fmt_price(d["price"], d["currency"]))}</td>',
                      f'<td>{escape(d["notes"]).replace(chr(10), "<br>")}</td>']
            h.append("<tr>" + "".join(cells) + "</tr>")
        h.append("</table>")
    h.append("</body></html>")
    return title, "".join(h), images


def make_document(html, images):
    doc = QTextDocument()
    for name, img in images.items():
        doc.addResource(QTextDocument.ImageResource, QUrl(f"foto://{name}"), img)
    doc.setHtml(html)
    return doc


class ReportDialog(QDialog):
    def __init__(self, db, table="categories", node_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(t("Döküm"))
        self.resize(1000, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        top = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem(t("Kategoriye göre"), "categories")
        self.kind.addItem(t("Yere göre"), "locations")
        self.kind.setCurrentIndex(0 if table == "categories" else 1)
        self.node = QComboBox()
        self.photos = QCheckBox(t("Fotoğraflarla"))
        self.photos.setChecked(True)
        top.addWidget(QLabel(t("Döküm türü:")))
        top.addWidget(self.kind)
        top.addWidget(self.node, 1)
        top.addWidget(self.photos)
        lay.addLayout(top)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        hint = QLabel(t("Döküm, seçilen bölümdeki ve altındaki bütün eşyaları gösterir."))
        hint.setObjectName("Muted")
        row.addWidget(hint, 1)
        pr = QPushButton(t("🖨  Yazdır…"))
        pr.setObjectName("Primary")
        pr.clicked.connect(self.print_)
        pdf = QPushButton(t("📄  PDF olarak kaydet…"))
        pdf.clicked.connect(self.save_pdf)
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.accept)
        row.addWidget(pr)
        row.addWidget(pdf)
        row.addWidget(close)
        lay.addLayout(row)
        self._fill_nodes(node_id)
        self.kind.currentIndexChanged.connect(lambda _: (self._fill_nodes(None), self.render()))
        self.node.currentIndexChanged.connect(lambda _: self.render())
        self.photos.toggled.connect(lambda _: self.render())
        self.render()

    def _fill_nodes(self, select):
        table = self.kind.currentData()
        self.node.blockSignals(True)
        self.node.clear()
        self.node.addItem(t("Bütün kategoriler") if table == "categories" else t("Bütün yerler"), None)
        for nid, name, depth, path in self.db.tree_ordered(table):
            self.node.addItem(("   " * depth) + (path if depth else name), nid)
        self.node.addItem(t("Belirtilmemiş"), UNASSIGNED)
        idx = self.node.findData(select) if select is not None else 0
        self.node.setCurrentIndex(max(idx, 0))
        self.node.blockSignals(False)

    def render(self):
        self.title, html, images = build_report(self.db, self.kind.currentData(), self.node.currentData(),
                                                self.photos.isChecked())
        self.doc = make_document(html, images)
        self.view.setDocument(self.doc)

    def _printer(self):
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        printer.setPageOrientation(QPageLayout.Portrait)
        printer.setDocName(self.title)
        return printer

    def print_(self):
        from PySide6.QtPrintSupport import QPrintDialog
        printer = self._printer()
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            self.doc.print_(printer)

    def save_pdf(self, target=None):
        from PySide6.QtPrintSupport import QPrinter
        interactive = not target
        if interactive:
            safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.title).strip()
            default = Path.home() / f"{safe}.pdf"
            target, _ = QFileDialog.getSaveFileName(self, t("PDF olarak kaydet"), str(default), "PDF (*.pdf)")
            if not target:
                return None
        printer = self._printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(target))
        self.doc.print_(printer)
        if interactive:
            info(self, t("Döküm"), t("PDF kaydedildi:\n{path}", path=target))
        return target

