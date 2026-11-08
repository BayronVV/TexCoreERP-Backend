"""PDF de la relación de despacho (HU 7.2): la lista de paquetes que la transportadora recoge, para firmarla al entregarlos."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import catalog


def dispatch_pdf(relation):
    """Bytes del PDF de una relación (con sus guías ya cargadas)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Relación de despacho {relation.codigo}", author="TexCore ERP")
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    guides = list(relation.guias.select_related("factura").order_by("id"))
    story = [
        Paragraph("TexCore ERP", ParagraphStyle("brand", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#475569"))),
        Paragraph(f"Relación de despacho {relation.codigo}", styles["Title"]),
        Paragraph(
            f"<b>Transportadora:</b> {catalog.CARRIER_NAMES.get(relation.transportadora, relation.transportadora)} &nbsp; "
            f"<b>Fecha:</b> {relation.fecha.strftime('%d/%m/%Y')} &nbsp; <b>Paquetes:</b> {len(guides)}", small),
        Paragraph(f"<b>Responsable:</b> {relation.responsable or '—'}", small),
        Spacer(1, 0.4 * cm),
    ]
    rows = [["#", "Guía", "Factura", "Cliente", "Ciudad", "A recaudar"]]
    total = 0
    for index, guide in enumerate(guides, start=1):
        invoice = guide.factura
        total += invoice.valor_a_recaudar
        rows.append([
            str(index), guide.numero_guia, invoice.numero, Paragraph(invoice.cliente_nombre, small), Paragraph(invoice.cliente_ciudad, small),
            "$" + f"{invoice.valor_a_recaudar:,}".replace(",", "."),
        ])
    table = Table(rows, colWidths=[0.9 * cm, 3.2 * cm, 2.2 * cm, 5.3 * cm, 3.3 * cm, 2.6 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f8")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")), ("ALIGN", (5, 0), (5, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [table, Spacer(1, 0.4 * cm), Paragraph(f"<b>Total a recaudar por la transportadora:</b> ${total:,}".replace(",", "."), small)]
    if relation.observaciones:
        story += [Spacer(1, 0.3 * cm), Paragraph(f"Observaciones: {relation.observaciones}", small)]
    story += [Spacer(1, 1.6 * cm), Table([["Entrega (bodega)", "Recibe (transportadora)"], ["\n\n______________________", "\n\n______________________"]], colWidths=[8.5 * cm, 8.5 * cm])]
    doc.build(story)
    return buffer.getvalue()
