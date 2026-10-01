"""
Generate PDF documentation for Events Data Schema
============================================

This script creates a comprehensive PDF document describing:
- Event data fields and meanings
- Event types (type column)
- Data sources / crawl origins
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem
)
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from collections import Counter
from urllib.parse import urlparse
import csv
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

OUTPUT_FILE = "data/event_documentation.pdf"
CSV_FILE = "data/event.csv"

# ============================================================
# STYLES
# ============================================================

def get_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='Title_Custom',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30,
        textColor=HexColor('#1a365d')
    ))

    styles.add(ParagraphStyle(
        name='Heading1_Custom',
        parent=styles['Heading1'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=12,
        textColor=HexColor('#2c5282')
    ))

    styles.add(ParagraphStyle(
        name='Heading2_Custom',
        parent=styles['Heading2'],
        fontSize=13,
        spaceBefore=15,
        spaceAfter=8,
        textColor=HexColor('#3182ce')
    ))

    styles.add(ParagraphStyle(
        name='Body_Custom',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6,
        leading=14
    ))

    styles.add(ParagraphStyle(
        name='Code_Custom',
        parent=styles['Code'],
        fontSize=9,
        backColor=HexColor('#f7fafc'),
        borderColor=HexColor('#e2e8f0'),
        borderWidth=1,
        borderPadding=5,
        spaceAfter=10
    ))

    return styles

# ============================================================
# DATA ANALYSIS
# ============================================================

def analyze_csv():
    """Analyze CSV file and return statistics."""
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Type distribution
    type_counts = Counter(row['type'] for row in rows)

    # Source distribution
    source_counts = Counter()
    for row in rows:
        url = row.get('source_url', '')
        if 'ticketbox' in url.lower():
            source_counts['ticketbox.vn'] += 1
        elif 'vanmieu' in url.lower():
            source_counts['vanmieu.gov.vn'] += 1
        elif 'lehoivietnam' in url.lower():
            source_counts['lehoivietnam.com.vn'] += 1
        elif 'vpf' in url.lower():
            source_counts['vpf.vn (football)'] += 1
        elif 'vff' in url.lower():
            source_counts['vff.org.vn (football)'] += 1
        elif 'hanoi.edu' in url.lower():
            source_counts['hanoi.edu.vn (education)'] += 1
        elif url:
            source_counts['Other'] += 1

    # Date range
    dates = [row['start_date'] for row in rows if row.get('start_date')]
    dates.sort()

    # Venue statistics
    venues = Counter(row.get('venue', '') for row in rows)
    venues_with_coords = sum(1 for row in rows if row.get('latitude') and row.get('longitude'))

    return {
        'total_rows': len(rows),
        'type_counts': type_counts,
        'source_counts': source_counts,
        'dates': dates,
        'venues': venues,
        'venues_with_coords': venues_with_coords
    }

# ============================================================
# PDF CONTENT
# ============================================================

def create_pdf():
    """Generate the PDF documentation."""
    doc = SimpleDocTemplate(
        OUTPUT_FILE,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = get_styles()
    story = []

    # ============================================================
    # TITLE PAGE
    # ============================================================

    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("EVENTS DATA DOCUMENTATION", styles['Title_Custom']))
    story.append(Paragraph("Mô tả chi tiết về cấu trúc dữ liệu sự kiện", styles['Body_Custom']))
    story.append(Spacer(1, 0.5*cm))

    # Metadata
    stats = analyze_csv()
    story.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Body_Custom']))
    story.append(Paragraph(f"<b>Total Records:</b> {stats['total_rows']:,} rows", styles['Body_Custom']))
    story.append(Paragraph(f"<b>Venue with Coordinates:</b> {stats['venues_with_coords']:,} ({stats['venues_with_coords']*100//stats['total_rows']}%)", styles['Body_Custom']))

    story.append(PageBreak())

    # ============================================================
    # SECTION 1: DATA FIELDS
    # ============================================================

    story.append(Paragraph("1. Cấu trúc dữ liệu (Data Schema)", styles['Heading1_Custom']))

    story.append(Paragraph("""
    File Excel/CSV chứa thông tin chi tiết về các sự kiện tại Hà Nội.
    Dữ liệu bao gồm thông tin thời gian, địa điểm, loại sự kiện và nguồn gốc.
    """, styles['Body_Custom']))

    # Field descriptions
    fields_data = [
        ['#', 'Field Name', 'Type', 'Description'],
        ['1', 'event_name', 'String', 'Tên đầy đủ của sự kiện'],
        ['2', 'venue', 'String', 'Địa điểm tổ chức sự kiện'],
        ['3', 'start_date', 'Date', 'Ngày bắt đầu (DD/MM/YY)'],
        ['4', 'start_time', 'Time', 'Giờ bắt đầu (HH:MM)'],
        ['5', 'end_time', 'Time', 'Giờ kết thúc (HH:MM)'],
        ['6', 'type', 'String', 'Loại sự kiện (xem mục 2)'],
        ['7', 'estimate_attendence', 'Number', 'Số lượng người tham dự ước tính'],
        ['8', 'source_url', 'URL', 'URL nguồn gốc sự kiện'],
        ['9', 'attendance_source_url', 'URL', 'URL nguồn dữ liệu về số lượng khán giả'],
        ['10', 'latitude', 'Float', 'Vĩ độ của địa điểm (geocoded)'],
        ['11', 'longitude', 'Float', 'Kinh độ của địa điểm (geocoded)'],
        ['12', 'h3_index', 'String', 'Mã H3 cell (resolution 8) cho spatial indexing'],
        ['13', 'time_slot', 'Time', 'Mốc thời gian 30 phút (dùng cho spike detection)'],
    ]

    fields_table = Table(fields_data, colWidths=[1*cm, 4.5*cm, 2.5*cm, 8*cm])
    fields_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f7fafc')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(fields_table)

    story.append(Spacer(1, 0.5*cm))

    # Field details
    story.append(Paragraph("1.1 Chi tiết các trường quan trọng", styles['Heading2_Custom']))

    field_details = [
        ("<b>latitude, longitude</b> - Tọa độ địa lý của địa điểm, được lấy từ geocoding service (Nominatim/OpenStreetMap). "
         "Các tọa độ được hard-coded cho các địa điểm phổ biến để đảm bảo độ chính xác cao nhất."),
        ("<b>h3_index</b> - Mã định danh H3 cell theo công nghệ hexagonal spatial indexing của Uber. "
         "Resolution 8 có nghĩa là mỗi hex có diện tích khoảng 33.9 km². "
         "Được dùng để group các sự kiện theo khu vực và join với dữ liệu weather."),
        ("<b>time_slot</b> - Mốc thời gian 30 phút, cho phép mỗi sự kiện được chia thành nhiều rows "
         "để phục vụ cho việc phát hiện spike demand. Ví dụ: sự kiện 09:00-11:00 sẽ có 4 slots: 09:00, 09:30, 10:00, 10:30."),
    ]

    for detail in field_details:
        story.append(Paragraph(f"• {detail}", styles['Body_Custom']))
        story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # ============================================================
    # SECTION 2: EVENT TYPES
    # ============================================================

    story.append(Paragraph("2. Loại sự kiện (Event Types)", styles['Heading1_Custom']))

    story.append(Paragraph("""
    Cột <b>type</b> xác định loại/hạng mục của sự kiện.
    Việc phân loại này giúp phân tích demand theo từng loại hình sự kiện.
    """, styles['Body_Custom']))

    # Type descriptions
    type_descriptions = {
        'exhibition': 'Triển lãm - các sự kiện trưng bày, giới thiệu sản phẩm hoặc tác phẩm',
        'cultural_event': 'Sự kiện văn hóa - hoạt động văn hóa, nghệ thuật, lễ kỷ niệm',
        'festival': 'Lễ hội - các festival, ngày hội, sự kiện quy mô lớn',
        'concert': 'Buổi hòa nhạc/hòa nhạc - các sự kiện âm nhạc, liveshow',
        'workshop': 'Hội thảo/Workshop - các buổi chia sẻ, đào tạo, workshop',
        'football': 'Bóng đá - các trận đấu bóng đá chuyên nghiệp',
        'official_or_diplomatic': 'Sự kiện nhà nước/ngoại giao - các sự kiện cấp nhà nước',
        'conference_seminar': 'Hội nghị/Hội thảo - các sự kiện học thuật, chuyên đề',
    }

    # Type statistics table
    type_data = [['Type', 'Mô tả', 'Số rows', '%']]
    for type_name, count in stats['type_counts'].most_common():
        desc = type_descriptions.get(type_name, 'Khác')
        pct = count * 100 / stats['total_rows']
        type_data.append([type_name, desc, f"{count:,}", f"{pct:.1f}%"])

    type_table = Table(type_data, colWidths=[4*cm, 8*cm, 2.5*cm, 2*cm])
    type_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f7fafc')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(type_table)

    story.append(PageBreak())

    # ============================================================
    # SECTION 3: DATA SOURCES
    # ============================================================

    story.append(Paragraph("3. Nguồn dữ liệu (Data Sources)", styles['Heading1_Custom']))

    story.append(Paragraph("""
    Cột <b>source_url</b> chứa URL của trang web nơi sự kiện được crawl.
    Việc phân tích nguồn gốc giúp đánh giá độ tin cậy và phạm vi của dữ liệu.
    """, styles['Body_Custom']))

    # Source descriptions
    source_descriptions = {
        'lehoivietnam.com.vn': 'Website tổng hợp sự kiện, lễ hội, triển lãm tại Việt Nam. Nguồn chính cho các sự kiện văn hóa và lễ hội.',
        'vanmieu.gov.vn': 'Website chính thức của Văn Miếu - Quốc Tử Giám. Nguồn cho các sự kiện văn hóa tại di tích này.',
        'ticketbox.vn': 'Nền tảng bán vé trực tuyến. Nguồn cho concerts và một số sự kiện đặc biệt.',
        'vpf.vn (football)': 'Liên đoàn Bóng đá Việt Nam (V-League). Nguồn cho các trận đấu bóng đá chuyên nghiệp.',
        'vff.org.vn (football)': 'Liên đoàn Bóng đá Việt Nam (Đội tuyển). Nguồn cho các trận đấu quốc tế và đội tuyển.',
        'hanoi.edu.vn (education)': 'Website Sở Giáo dục Hà Nội. Nguồn cho các sự kiện tại trường học.',
    }

    # Source statistics table
    source_data = [['Nguồn', 'Mô tả', 'Số rows', '%']]
    for source, count in stats['source_counts'].most_common():
        desc = source_descriptions.get(source, 'Nguồn khác')
        pct = count * 100 / stats['total_rows']
        source_data.append([source, desc, f"{count:,}", f"{pct:.1f}%"])

    source_table = Table(source_data, colWidths=[4*cm, 8*cm, 2.5*cm, 2*cm])
    source_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f7fafc')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(source_table)

    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("3.1 Đánh giá nguồn dữ liệu", styles['Heading2_Custom']))

    source_notes = [
        "<b>Ưu điểm:</b> Hai nguồn chính (lehoivietnam và vanmieu) cung cấp dữ liệu đa dạng về sự kiện văn hóa.",
        "<b>Hạn chế:</b> Thiếu dữ liệu về một số loại hình sự kiện như concert, workshop từ các nguồn khác.",
        "<b>Khuyến nghị:</b> Cần bổ sung thêm nguồn cho sports, concerts từ các nền tảng khác như Ticketbox, Idols.",
    ]

    for note in source_notes:
        story.append(Paragraph(f"• {note}", styles['Body_Custom']))
        story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # ============================================================
    # SECTION 4: DATA STATISTICS
    # ============================================================

    story.append(Paragraph("4. Thống kê dữ liệu", styles['Heading1_Custom']))

    story.append(Paragraph("4.1 Phân bố theo loại sự kiện", styles['Heading2_Custom']))

    # Create bar chart representation
    max_count = max(stats['type_counts'].values())
    bar_data = []
    for type_name, count in stats['type_counts'].most_common():
        bar_length = int(count * 50 / max_count)
        bar = '█' * bar_length
        bar_data.append([type_name, bar, count])

    bar_table = Table(bar_data, colWidths=[4*cm, 8*cm, 2.5*cm])
    bar_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (1, 0), (1, -1), HexColor('#3182ce')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(bar_table)

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("4.2 Phân bố theo nguồn", styles['Heading2_Custom']))

    max_count = max(stats['source_counts'].values())
    bar_data = []
    for source, count in stats['source_counts'].most_common():
        bar_length = int(count * 50 / max_count)
        bar = '█' * bar_length
        bar_data.append([source, bar, count])

    bar_table = Table(bar_data, colWidths=[5*cm, 7*cm, 2.5*cm])
    bar_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TEXTCOLOR', (1, 0), (1, -1), HexColor('#38a169')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(bar_table)

    story.append(PageBreak())

    # ============================================================
    # SECTION 5: H3 SPATIAL INDEXING
    # ============================================================

    story.append(Paragraph("5. H3 Spatial Indexing", styles['Heading1_Custom']))

    story.append(Paragraph("""
    H3 là thư viện hexagonal hierarchical spatial indexing của Uber,
    cho phép biểu diễn bề mặt Trái Đất dưới dạng lưới lục giác (hexagons).
    """, styles['Body_Custom']))

    h3_info = [
        "<b>Resolution 8</b>: Mỗi hex có diện tích khoảng 33.9 km², phù hợp cho phân tích cấp thành phố.",
        "<b>Cách tính</b>: H3 index được tính từ tọa độ lat/lon của venue bằng hàm h3.latlng_to_cell(lat, lon, 8).",
        "<b>Ứng dụng</b>: Dùng để group các sự kiện theo khu vực và join với dữ liệu thời tiết (weather plugins cũng dùng resolution 8).",
        "<b>Ví dụ</b>: Văn Miếu - Quốc Tử Giám có tọa độ (21.0369, 105.8351), H3 index: 88415cb4adfffff",
    ]

    for info in h3_info:
        story.append(Paragraph(f"• {info}", styles['Body_Custom']))
        story.append(Spacer(1, 0.3*cm))

    story.append(Spacer(1, 0.5*cm))

    # H3 resolution table
    resolution_data = [
        ['Resolution', 'Diện tích/hex', 'Ứng dụng'],
        ['7', '~254 km²', 'Cấp vùng/quốc gia'],
        ['8', '~34 km²', 'Cấp thành phố'],
        ['9', '~5 km²', 'Cấp quận/huyện'],
        ['10', '~0.7 km²', 'Cấp phường/xã'],
        ['11', '~0.1 km²', 'Cấp khu vực nhỏ'],
        ['12', '~0.007 km²', 'Cấp block/tòa nhà'],
    ]

    res_table = Table(resolution_data, colWidths=[2.5*cm, 3.5*cm, 10*cm])
    res_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f7fafc')]),
        ('BACKGROUND', (0, 3), (-1, 3), HexColor('#e6fffa')),  # Highlight current resolution
    ]))
    story.append(res_table)

    story.append(PageBreak())

    # ============================================================
    # SECTION 6: TIME SLOT FOR SPIKE DETECTION
    # ============================================================

    story.append(Paragraph("6. Time Slot cho Spike Detection", styles['Heading1_Custom']))

    story.append(Paragraph("""
    Cột <b>time_slot</b> chia sự kiện thành các mốc thời gian 30 phút.
    Cách chia này phục vụ cho việc phát hiện spike (đỉnh) trong demand forecasting.
    """, styles['Body_Custom']))

    story.append(Paragraph("6.1 Nguyên tắc chia slot", styles['Heading2_Custom']))

    slot_rules = [
        "<b>Event 09:00 - 11:00</b>: Chia thành 4 slots → 09:00, 09:30, 10:00, 10:30",
        "<b>Event 00:00 - 23:59</b>: Chia thành 48 slots (all-day event)",
        "<b>Event bắt đầu = kết thúc</b>: Giữ 1 slot duy nhất",
    ]

    for rule in slot_rules:
        story.append(Paragraph(f"• {rule}", styles['Body_Custom']))
        story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("6.2 Peak Hours Multipliers (đề xuất)", styles['Heading2_Custom']))

    story.append(Paragraph("""
    Để phản ánh đặc điểm demand thực tế, có thể áp dụng trọng số nhân (multiplier)
    cho các khung giờ cao điểm (peak hours):
    """, styles['Body_Custom']))

    peak_data = [
        ['Khung giờ', 'Multiplier', 'Ghi chú'],
        ['06:00 - 08:00', '1.5x', 'Rush hour sáng'],
        ['08:00 - 10:00', '2.0x', 'Peak sáng - event bắt đầu'],
        ['10:00 - 17:00', '1.0x', 'Giờ bình thường'],
        ['17:00 - 19:00', '2.5x', 'Peak chiều - event kết thúc'],
        ['19:00 - 22:00', '1.5x', 'Giờ tối'],
        ['22:00 - 06:00', '0.5x', 'Đêm - demand thấp'],
    ]

    peak_table = Table(peak_data, colWidths=[4*cm, 3*cm, 9*cm])
    peak_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f7fafc')]),
        ('BACKGROUND', (0, 2), (1, 2), HexColor('#fed7d7')),  # Highlight peak hours
        ('BACKGROUND', (0, 4), (1, 4), HexColor('#fed7d7')),  # Highlight peak hours
    ]))
    story.append(peak_table)

    story.append(Spacer(1, 1*cm))

    # ============================================================
    # FOOTER
    # ============================================================

    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("—" * 40, styles['Body_Custom']))
    story.append(Paragraph(f"<i>Document generated by Demand Spike Detector v0</i>", styles['Body_Custom']))
    story.append(Paragraph(f"<i>Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>", styles['Body_Custom']))

    # Build PDF
    doc.build(story)
    print(f"PDF generated: {OUTPUT_FILE}")

if __name__ == "__main__":
    create_pdf()
