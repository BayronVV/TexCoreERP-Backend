"""PDF de la factura POS interna (HU 7.1). Se genera siempre desde el registro guardado, así que es idéntico al de la pantalla."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import catalog


def money(value):
    """Pesos con punto de miles: 1234567 → $1.234.567."""
    return "$" + f"{value:,}".replace(",", ".")


def invoice_pdf(invoice):
    """Bytes del PDF de una factura (con sus líneas ya cargadas)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Factura {invoice.numero}", author="TexCore ERP")
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    notice = ParagraphStyle("notice", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#9a5b00"))
    story = [
        Paragraph("TexCore ERP", ParagraphStyle("brand", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#475569"))),
        Paragraph(f"Factura {invoice.numero}", styles["Title"]),
        Paragraph(f"<b>{catalog.INVOICE_NOTICE}</b>", notice),
    ]
    if invoice.estado == catalog.STATUS_CANCELLED:
        story.append(Paragraph(f"<b>ANULADA</b> — {invoice.motivo_anulacion}", ParagraphStyle("void", parent=notice, textColor=colors.HexColor("#b3261e"))))
    story.append(Spacer(1, 0.4 * cm))

    seller = (f"{invoice.vendedor.first_name} {invoice.vendedor.last_name}".strip() or invoice.vendedor.username) if invoice.vendedor else "—"
    carrier = catalog.CARRIER_NAMES.get(invoice.transportadora, "Por definir")
    info = [
        ["Fecha", invoice.fecha.strftime("%d/%m/%Y"), "Vendedor", seller],
        ["Cliente", invoice.cliente_nombre, "Documento", invoice.cliente_documento],
        ["Ciudad", invoice.cliente_ciudad, "Teléfono", invoice.cliente_telefono],
        ["Dirección", invoice.cliente_direccion, "Pago", "Contraentrega"],
        ["Transportadora", carrier, "Guía", invoice.numero_guia or "Por asignar"],
    ]
    table = Table([[Paragraph(str(cell), small) for cell in row] for row in info], colWidths=[2.6 * cm, 6.4 * cm, 2.4 * cm, 6.0 * cm])
    table.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    story += [table, Spacer(1, 0.5 * cm)]

    rows = [["Referencia", "Talla y color", "Cant.", "Precio", "Desc.", "Base", "IVA", "Total"]]
    for line in invoice.lineas.all():
        rows.append([
            Paragraph(f"{line.referencia_codigo} {line.referencia_nombre}", small), Paragraph(f"{line.talla} · {line.color}", small),
            str(line.cantidad), money(line.precio_unitario), f"{line.descuento_pct} %", money(line.base), money(line.iva), money(line.total),
        ])
    lines = Table(rows, colWidths=[4.4 * cm, 3.0 * cm, 1.2 * cm, 2.0 * cm, 1.2 * cm, 2.1 * cm, 1.8 * cm, 2.1 * cm], repeatRows=1)
    lines.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f8")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")), ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [lines, Spacer(1, 0.4 * cm)]

    totals = Table([
        ["Subtotal", money(invoice.subtotal)], ["Descuento", "-" + money(invoice.descuento_total)], ["Base gravable", money(invoice.base_gravable)],
        [f"IVA {invoice.iva_tarifa} %", money(invoice.iva_total)], ["Total a pagar", money(invoice.total)],
    ], colWidths=[4 * cm, 3.4 * cm], hAlign="RIGHT")
    totals.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#0f172a")), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(totals)
    if invoice.observaciones:
        story += [Spacer(1, 0.4 * cm), Paragraph(f"Observaciones: {invoice.observaciones}", small)]
    story += [Spacer(1, 0.6 * cm), Paragraph(f"Valor a recaudar en la entrega: <b>{money(invoice.valor_a_recaudar)}</b>. {catalog.INVOICE_NOTICE}", small)]
    doc.build(story)
    return buffer.getvalue()
