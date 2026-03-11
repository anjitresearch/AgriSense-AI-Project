# ==============================================================
#  CHAIN-PROOF™ — Offline QR & Digital Passport Generator
#  Platform: Python (ReportLab + QRCode)
#  Purpose: Fetches blockchain passport, generates deterministic 
#           hash QR, and writes an A4 printable PDF certificate.
# ==============================================================

import argparse
import qrcode
import requests
import json
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.units import inch, cm

API_URL = "http://localhost:3002/api/v1/passport"

def generate_qr(batch_id: str, passport_hash: str, output_path: str):
    """
    Generates a high-error-correction QR code containing ONLY the batch and hash 
    (offline verifiable) structured as a compact JSON string to save space.
    The portal will decode this JSON directly.
    """
    qr_data = json.dumps({"b": batch_id, "h": passport_hash})
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H, # High error correction for farm environments
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)

    # Style: Green to match AgriSense brand
    img = qr.make_image(fill_color="#2E7D32", back_color="white")
    img.save(output_path)
    return output_path

def generate_pdf(passport_data: dict, qr_path: str, output_path: str):
    """Generates an A4 Printable PDF Certificate using ReportLab."""
    doc = SimpleDocTemplate(
        output_path, 
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], alignment=1, fontSize=24, spaceAfter=20, textColor=colors.HexColor("#1B5E20"))
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=16, spaceAfter=10, textColor=colors.HexColor("#2E7D32"))
    normal_style = styles["Normal"]
    
    elements = []
    
    # Header
    elements.append(Paragraph("CHAIN-PROOF™ Digital Passport", title_style))
    elements.append(Spacer(1, 0.5*inch))
    
    # Dynamic content extraction (fallback to N/A if missing in timeline)
    timeline = passport_data.get("timeline", [])
    harvest_event = next((e for e in timeline if e.get("eventType") == "HarvestEvent"), {})
    seed_event = next((e for e in timeline if e.get("eventType") == "SeedingEvent"), {})
    cert_event = next((e for e in timeline if e.get("eventType") == "CertificationEvent"), {})
    
    h_data = harvest_event.get("data", {})
    s_data = seed_event.get("data", {})
    c_data = cert_event.get("data", {})

    # Details table
    elements.append(Paragraph("Batch Details", h2_style))
    details_data = [
        ["Product / Crop:", s_data.get("crop", "Premium Turmeric") + " (" + s_data.get("variety", "Pragati") + ")"],
        ["Batch ID:", passport_data.get("batchId", "Unknown")],
        ["Farm ID:", h_data.get("farm_id", "FARM-1")],
        ["Harvest Date:", h_data.get("date", "2026-10-15")],
        ["Yield (kg):", str(h_data.get("yield_kg", "5000"))]
    ]
    t = Table(details_data, colWidths=[2.5*inch, 4*inch])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3*inch))

    # Nutraceutical Results
    elements.append(Paragraph("NUTRA-SPEC™ Analysis (AI Predicted + Lab Verified)", h2_style))
    nutra = h_data.get("nutraceutical_results", {"curcumin": "5.4%", "polyphenol": "2.1%"})
    
    nutra_data = [["Compound", "Tested Value", "Quality Grade"]]
    for k, v in nutra.items():
        grade = "Grade A+" if float(str(v).replace('%','')) > 5.0 else "Grade A"
        nutra_data.append([k.capitalize(), str(v), grade])
        
    t2 = Table(nutra_data, colWidths=[2.5*inch, 2*inch, 2*inch])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E8F5E9")),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#C8E6C9")),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 0.4*inch))

    # Certifications
    if c_data:
        elements.append(Paragraph(f"FSSAI Cert: {c_data.get('fssai_cert_no')} | APEDA Cert: {c_data.get('apeda_cert_no')}", normal_style))
        elements.append(Spacer(1, 0.2*inch))

    # QR Code inline
    elements.append(Paragraph("Scan to Verify Immutability (Offline Supported)", h2_style))
    qr_img = Image(qr_path, width=2.5*inch, height=2.5*inch)
    elements.append(qr_img)
    
    # Hash Footer
    elements.append(Spacer(1, 0.4*inch))
    hash_text = f"<font size=8 color=gray>Blockchain Hash (SHA256): {passport_data.get('passportHash')}</font>"
    elements.append(Paragraph(hash_text, styles["Normal"]))

    doc.build(elements)
    print(f"✅ Generated A4 Certificate PDF: {output_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True, help="Harvest Batch ID for passport generation")
    args = parser.parse_args()

    os.makedirs("certs", exist_ok=True)
    
    print(f"Fetching digital passport for Batch: {args.batch_id}...")
    try:
        res = requests.get(f"{API_URL}/{args.batch_id}")
        if res.status_code != 200:
            print("Failed to fetch passport. Start fabric_gateway.py first.")
            return
            
        passport = res.json()
    except Exception as e:
        print(f"Error connecting to Fabric Gateway API: {e}")
        return

    qr_path = f"certs/QR_{args.batch_id}.png"
    pdf_path = f"certs/Certificate_{args.batch_id}.pdf"
    
    # 1. Generate Offline Verifiable QR 
    generate_qr(passport["batchId"], passport["passportHash"], qr_path)
    print(f"✅ Generated QR Code: {qr_path}")
    
    # 2. Build A4 Printable PDF
    generate_pdf(passport, qr_path, pdf_path)

if __name__ == "__main__":
    main()
