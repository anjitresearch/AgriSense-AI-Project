# ==============================================================
#  CHAIN-PROOF™ — QR Certificate Generator
#  Generates a printable PDF certificate with embedded QR code
#  for each NutraCertificate issued on the Hyperledger Fabric ledger.
#
#  Usage:
#    python chain_proof_qr.py --cert-id "CERT~SAMPLE-001~1234567890000" \
#                             --ledger-url http://localhost:3002
#
#  Output: ./certs/<cert_id>.pdf   +   ./certs/<cert_id>.png (QR only)
#
#  Dependencies: pip install qrcode[pil] reportlab requests
# ==============================================================

import argparse
import json
import os
import hashlib
import requests
import qrcode
import logging
from datetime import datetime
from pathlib import Path

# ReportLab for PDF generation (optional — degrades to PNG-only if missing)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Image as RLImage, Table, TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logging.warning("reportlab not installed — PDF output disabled. Install with: pip install reportlab")

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
DEFAULT_LEDGER_URL = os.getenv("CHAIN_PROOF_API", "http://localhost:3002")
CERT_OUTPUT_DIR    = os.getenv("CERT_DIR", "./certs")
QR_BASE_URL        = os.getenv("QR_BASE_URL", "https://agrisense.example.com/verify")  # URL embedded in QR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CHAIN-PROOF-QR] %(levelname)s — %(message)s"
)
logger = logging.getLogger("chain_proof_qr")


# ==============================================================
#  LEDGER FETCH  — calls the CHAIN-PROOF REST gateway
# ==============================================================
def fetch_certificate(cert_id: str, ledger_url: str) -> dict:
    """
    Fetch a NutraCertificate JSON from the CHAIN-PROOF™ REST API gateway.
    The gateway wraps Hyperledger Fabric peer calls via the fabric-sdk-node.

    Expected endpoint: GET /api/certificate/<certId>
    """
    url = f"{ledger_url}/api/certificate/{cert_id}"
    logger.info(f"Fetching certificate from ledger: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        logger.warning("Ledger gateway unreachable — using synthetic demo certificate")
        return _demo_certificate(cert_id)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.error(f"Certificate {cert_id} not found on ledger")
        raise


def _demo_certificate(cert_id: str) -> dict:
    """Return a synthetic certificate for offline testing / demo."""
    return {
        "certId":       cert_id,
        "sampleId":     "SAMPLE-DEMO-001",
        "batchId":      "BATCH-2026-TOM-001",
        "fieldId":      "FIELD-COIMBATORE-01",
        "cropType":     "tomato",
        "scanDeviceId": "NUTRA-001",
        "issuedAt":     datetime.utcnow().isoformat() + "Z",
        "timestamp":    datetime.utcnow().isoformat() + "Z",
        "phytochemicals": {
            "flavonoids_mg":    42.3,
            "anthocyanins_mg":  18.7,
            "lycopene_mg":      31.5,
            "vitamin_c_mg":     28.9,
            "total_phenols_mg": 187.4,
        },
        "status": "VALID",
        "revoked_at": None,
        "_demo": True,
    }


# ==============================================================
#  QR CODE GENERATION
# ==============================================================
def generate_qr(cert_id: str, output_path: str) -> str:
    """
    Encode a verification URL with the cert_id into a QR code PNG.
    The URL allows anyone to scan and verify the certificate on-chain.
    """
    verify_url = f"{QR_BASE_URL}?cert={cert_id}"

    qr = qrcode.QRCode(
        version=None,       # Auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # 30% damage tolerance
        box_size=10,
        border=4,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1a1a2e", back_color="white")
    qr_path = output_path.replace(".pdf", "_qr.png")
    img.save(qr_path)
    logger.info(f"QR code saved → {qr_path}  (URL: {verify_url})")
    return qr_path


# ==============================================================
#  CERTIFICATE FINGERPRINT
#  SHA-256 of canonical JSON — proves document hasn't changed
# ==============================================================
def compute_fingerprint(cert_data: dict) -> str:
    """
    Compute SHA-256 fingerprint of the certificate JSON (sorted keys).
    This fingerprint should match what's verified on-chain.
    """
    canonical = json.dumps(cert_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ==============================================================
#  PDF CERTIFICATE GENERATOR
# ==============================================================
def generate_pdf(cert_data: dict, qr_path: str, output_path: str):
    """
    Render a professional A4 PDF certificate using ReportLab.
    Includes:
      - AgriSense-AI™ header + logo text
      - Phytochemical data table
      - QR code for blockchain verification
      - SHA-256 fingerprint footer
    """
    if not REPORTLAB_AVAILABLE:
        logger.warning("ReportLab not available — skipping PDF generation")
        return

    doc    = SimpleDocTemplate(output_path, pagesize=A4,
                               rightMargin=2*cm, leftMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    # ── Custom Styles ────────────────────────────────────────
    title_style = ParagraphStyle("title",
        fontSize=22, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"),
        alignment=TA_CENTER, spaceAfter=4)

    sub_style = ParagraphStyle("sub",
        fontSize=11, fontName="Helvetica",
        textColor=colors.HexColor("#2ecc71"),
        alignment=TA_CENTER, spaceAfter=12)

    label_style = ParagraphStyle("label",
        fontSize=10, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"), spaceAfter=2)

    value_style = ParagraphStyle("value",
        fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#555555"), spaceAfter=6)

    mono_style = ParagraphStyle("mono",
        fontSize=7, fontName="Courier",
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER)

    # ── Header ───────────────────────────────────────────────
    story.append(Paragraph("AgriSense-AI™", title_style))
    story.append(Paragraph("CHAIN-PROOF™ Phytochemical Quality Certificate", sub_style))
    story.append(HRFlowable(width="100%", thickness=2,
                            color=colors.HexColor("#2ecc71"), spaceAfter=12))

    # ── Certificate metadata table ───────────────────────────
    issued_dt = cert_data.get("issuedAt", "N/A")[:10]
    meta_data = [
        ["Certificate ID",  cert_data.get("certId", "N/A")],
        ["Sample ID",       cert_data.get("sampleId", "N/A")],
        ["Batch ID",        cert_data.get("batchId", "N/A")],
        ["Field ID",        cert_data.get("fieldId", "N/A")],
        ["Crop Type",       cert_data.get("cropType", "N/A").title()],
        ["Scan Device",     cert_data.get("scanDeviceId", "N/A")],
        ["Issued Date",     issued_dt],
        ["Status",          cert_data.get("status", "UNKNOWN")],
    ]

    meta_table = Table(meta_data, colWidths=[5*cm, 12*cm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (0, -1), colors.HexColor("#f0faf4")),
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5*cm))

    # ── Phytochemical results table ──────────────────────────
    story.append(Paragraph("Phytochemical Analysis (NIR / NUTRA-SPEC™)", label_style))
    story.append(Spacer(1, 0.2*cm))

    phyto = cert_data.get("phytochemicals", {})
    phyto_rows = [
        ["Compound", "Concentration", "Unit", "Grade"],
        ["Flavonoids",      f"{phyto.get('flavonoids_mg', 0):.2f}",     "mg/100g FW", _grade(phyto.get('flavonoids_mg',    0), 30, 60)],
        ["Anthocyanins",    f"{phyto.get('anthocyanins_mg', 0):.2f}",   "mg/100g FW", _grade(phyto.get('anthocyanins_mg',  0), 10, 25)],
        ["Lycopene",        f"{phyto.get('lycopene_mg', 0):.2f}",       "mg/100g FW", _grade(phyto.get('lycopene_mg',      0), 15, 35)],
        ["Vitamin C",       f"{phyto.get('vitamin_c_mg', 0):.2f}",      "mg/100g FW", _grade(phyto.get('vitamin_c_mg',     0), 20, 50)],
        ["Total Phenols",   f"{phyto.get('total_phenols_mg', 0):.2f}",  "mg GAE/100g",_grade(phyto.get('total_phenols_mg', 0), 80, 200)],
    ]

    phyto_table = Table(phyto_rows, colWidths=[5*cm, 4*cm, 4*cm, 4*cm])
    phyto_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(phyto_table)
    story.append(Spacer(1, 0.5*cm))

    # ── QR Code + fingerprint ────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#cccccc"), spaceAfter=10))

    fingerprint = compute_fingerprint(cert_data)
    qr_img = RLImage(qr_path, width=4*cm, height=4*cm)

    qr_label = Paragraph(
        f"<b>Blockchain Verification</b><br/>"
        f"Scan to verify on-chain or visit:<br/>"
        f"{QR_BASE_URL}?cert={cert_data.get('certId','')}",
        value_style
    )
    fp_label = Paragraph(
        f"SHA-256 Fingerprint:<br/><font name='Courier' size='7'>{fingerprint}</font>",
        mono_style
    )

    bottom_table = Table([[qr_img, [qr_label, Spacer(1, 0.3*cm), fp_label]]],
                         colWidths=[5*cm, 12*cm])
    bottom_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(bottom_table)

    # ── Demo watermark ───────────────────────────────────────
    if cert_data.get("_demo"):
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(
            "⚠ DEMO CERTIFICATE — Connect to live Hyperledger Fabric ledger for production use",
            ParagraphStyle("warn", fontSize=8, textColor=colors.HexColor("#e74c3c"),
                           alignment=TA_CENTER)
        ))

    doc.build(story)
    logger.info(f"PDF certificate saved → {output_path}")


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def _grade(value: float, medium_threshold: float, high_threshold: float) -> str:
    """Simple 3-tier quality grade based on concentration thresholds."""
    if value >= high_threshold:
        return "★★★ High"
    elif value >= medium_threshold:
        return "★★  Medium"
    else:
        return "★   Low"


# ==============================================================
#  MAIN PIPELINE
# ==============================================================
def generate_certificate(cert_id: str, ledger_url: str, output_dir: str):
    """Full pipeline: fetch → QR → PDF."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Sanitize cert_id for use as filename (replace ~ and spaces)
    safe_name   = cert_id.replace("~", "_").replace(" ", "_")
    output_pdf  = os.path.join(output_dir, f"{safe_name}.pdf")
    output_png  = os.path.join(output_dir, f"{safe_name}_qr.png")

    # 1. Fetch from blockchain
    cert_data = fetch_certificate(cert_id, ledger_url)
    logger.info(f"Certificate fetched: {cert_data.get('certId')} | Status: {cert_data.get('status')}")

    if cert_data.get("status") == "REVOKED":
        logger.error(f"Certificate {cert_id} has been REVOKED on {cert_data.get('revoked_at')}")
        logger.error(f"Reason: {cert_data.get('revoke_reason', 'N/A')}")
        raise ValueError(f"Cannot generate certificate for REVOKED cert: {cert_id}")

    # 2. Generate QR code
    qr_path = generate_qr(cert_id, output_pdf)

    # 3. Generate PDF
    generate_pdf(cert_data, qr_path, output_pdf)

    # 4. Save raw JSON sidecar
    json_path = output_pdf.replace(".pdf", ".json")
    with open(json_path, "w") as f:
        json.dump(cert_data, f, indent=2)
    logger.info(f"JSON sidecar saved → {json_path}")

    logger.info("=" * 60)
    logger.info("CHAIN-PROOF™ Certificate generation complete!")
    logger.info(f"  PDF: {output_pdf}")
    logger.info(f"  QR:  {qr_path}")
    logger.info(f"  JSON:{json_path}")
    logger.info(f"  Fingerprint: {compute_fingerprint(cert_data)}")
    logger.info("=" * 60)

    return {"pdf": output_pdf, "qr": qr_path, "json": json_path}


# ──────────────────────────────────────────────
# CLI ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CHAIN-PROOF™ QR Certificate Generator — AgriSense-AI™")
    parser.add_argument("--cert-id",    required=True,
                        help="Certificate ID from the Hyperledger Fabric ledger")
    parser.add_argument("--ledger-url", default=DEFAULT_LEDGER_URL,
                        help=f"CHAIN-PROOF REST gateway URL (default: {DEFAULT_LEDGER_URL})")
    parser.add_argument("--output-dir", default=CERT_OUTPUT_DIR,
                        help=f"Output directory for generated files (default: {CERT_OUTPUT_DIR})")
    args = parser.parse_args()

    generate_certificate(
        cert_id=args.cert_id,
        ledger_url=args.ledger_url,
        output_dir=args.output_dir,
    )
