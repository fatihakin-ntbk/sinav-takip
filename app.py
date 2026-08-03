import streamlit as st
import pandas as pd
import sqlite3
import numpy as np
import matplotlib.pyplot as plt
import base64
import urllib.parse
import re
import io
import os

# ReportLab Imports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import registerFont, registerFontFamily
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# --- GÜÇLENDİRİLMİŞ TÜRKÇE MAPPING VE METİN TEMİZLEYİCİ ---
def tr_clean(text):
    """PDF ve Veritabanı kaynaklı TÜM Türkçe karakter bozulmalarını kesin düzeltir."""
    if not isinstance(text, str):
        return ""
    
    replacements = {
        '■': '', '	': ' ',
        'Ý': 'İ', 'ý': 'ı', 'Þ': 'Ş', 'þ': 'ş',
        'Ð': 'Ğ', 'ð': 'ğ',
        'Geli im': 'Gelişim', 'S nav': 'Sınav', 'Ö renci': 'Öğrenci',
        'Çar amba': 'Çarşamba', 'Per embe': 'Perşembe', 'Görü ü': 'Görüşü',
        'Öretmen': 'Öğrenci', 'Balar yla': 'Başarıyla', 'Kazan m': 'Kazanım',
        'Çalma': 'Çalışma', 'Anlat m': 'Anlatım', 'Dier': 'Diğer', 'Diler': 'Diğer',
        'Dimer': 'Diğer', 'Snav': 'Sınav', 'liskilendirir': 'İlişkilendirir'
    }
    
    for bad, good in replacements.items():
        text = text.replace(bad, good)
        
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Sınav Takip & Analiz Portalı",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE NOT NULL,
        sifre TEXT NOT NULL,
        rol TEXT NOT NULL,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT NOT NULL,
        tarih DATE,
        yayin_evi TEXT,
        sinav_turu TEXT DEFAULT 'TYT'
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        kurum_sirasi INTEGER,
        genel_sira INTEGER,
        turkce_d REAL, turkce_y REAL, turkce_net REAL DEFAULT 0,
        sosyal_d REAL, sosyal_y REAL, sosyal_net REAL DEFAULT 0,
        matematik_d REAL, matematik_y REAL, matematik_net REAL DEFAULT 0,
        fen_d REAL, fen_y REAL, fen_net REAL DEFAULT 0,
        toplam_net REAL DEFAULT 0,
        tyt_puan REAL DEFAULT 0,
        ayt_mat_net REAL DEFAULT 0, ayt_fizik_net REAL DEFAULT 0,
        ayt_kimya_net REAL DEFAULT 0, ayt_biyo_net REAL DEFAULT 0,
        ayt_edebiyat_net REAL DEFAULT 0, ayt_tarih1_net REAL DEFAULT 0,
        ayt_cogr1_net REAL DEFAULT 0, ayt_tarih2_net REAL DEFAULT 0,
        ayt_cogr2_net REAL DEFAULT 0, ayt_felsefe_net REAL DEFAULT 0,
        ayt_din_net REAL DEFAULT 0, ayt_toplam_net REAL DEFAULT 0,
        ayt_say_puan REAL DEFAULT 0, ayt_ea_puan REAL DEFAULT 0, ayt_soz_puan REAL DEFAULT 0,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id) ON DELETE CASCADE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_eksikleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        ders TEXT,
        konu_kazanim TEXT,
        soru_nolari TEXT,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id) ON DELETE CASCADE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinif TEXT, ders TEXT, konu_kaynak TEXT, son_tarih DATE, eklenme_tarihi DATE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odev_takip (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        odev_id INTEGER, ogrenci_adi_norm TEXT, durum TEXT DEFAULT 'Bekliyor', aciklama TEXT,
        FOREIGN KEY (odev_id) REFERENCES odevler(odev_id) ON DELETE CASCADE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        ogrenci_adi_norm TEXT PRIMARY KEY, hedef_bolum TEXT, hedef_net REAL, hedef_puan REAL, alan_tercihi TEXT DEFAULT 'SAY'
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogretmen_notlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ogrenci_adi_norm TEXT, tarih DATE, not_metni TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY DEFAULT 1, kurum_adi TEXT, logo_base64 TEXT
    )''')
    
    cursor.execute("INSERT OR REPLACE INTO kullanicilar (id, kullanici_adi, sifre, rol) VALUES (1, 'admin', 'admin123', 'admin')")
    cursor.execute("INSERT OR REPLACE INTO kullanicilar (id, kullanici_adi, sifre, rol) VALUES (2, 'ogretmen', 'ogretmen123', 'ogretmen')")
    
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
def normalize_name(text):
    if not isinstance(text, str):
        return ""
    text = tr_clean(text).upper()
    tr_map = str.maketrans("ÇĞİÖŞÜI", "CGIOSUI")
    text = text.translate(tr_map)
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return ' '.join(text.split())

def detect_subject_from_topic(topic_str):
    t = tr_clean(topic_str).lower()
    if any(k in t for k in ['paragraf', 'sozcuk', 'sözcük', 'cümle', 'cumle', 'yazim', 'yazım', 'noktalama', 'dil bilgisi', 'edebiyat', 'turkce', 'türkçe', 'şiir', 'roman']):
        return "Türkçe / Edebiyat"
    elif any(k in t for k in ['üslü', 'köklü', 'fonksiyon', 'polinom', 'trigonometri', 'türev', 'integral', 'limit', 'logaritma', 'matematik', 'geometri']):
        return "Matematik"
    elif any(k in t for k in ['kuvvet', 'hareket', 'vektör', 'elektrik', 'manyetizma', 'dalga', 'optik', 'fizik', 'atom']):
        return "Fizik"
    elif any(k in t for k in ['mol', 'çözelti', 'gaz', 'tepkim', 'asit', 'baz', 'kimya', 'organik']):
        return "Kimya"
    elif any(k in t for k in ['hücre', 'kalıtım', 'dna', 'sistem', 'solunum', 'ekoloji', 'biyoloji', 'bitki']):
        return "Biyoloji"
    elif any(k in t for k in ['tarih', 'osmanlı', 'inkılap', 'savaş']):
        return "Tarih"
    elif any(k in t for k in ['harita', 'iklim', 'nüfus', 'coğrafya']):
        return "Coğrafya"
    elif any(k in t for k in ['felsefe', 'din', 'inanç', 'mantık']):
        return "Felsefe / Din"
    return "Genel / Diğer"

def get_col_val(row, possible_names, default=0):
    for name in possible_names:
        for col in row.index:
            if name.lower() in str(col).lower():
                try:
                    val = float(row[col])
                    if not np.isnan(val):
                        return val
                except:
                    pass
    return default

def get_kurum_bilgileri():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kurum_adi, logo_base64 FROM kurum_ayarlari WHERE id = 1")
    res = cursor.fetchone()
    conn.close()
    if res:
        return tr_clean(res[0]) if res[0] else "Eğitim Kurumu", res[1] or ""
    return "Eğitim Kurumu", ""

def get_ogrenci_hedef(norm_adi):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT hedef_bolum, hedef_net, hedef_puan, alan_tercihi FROM ogrenci_hedefleri WHERE ogrenci_adi_norm = ?", (norm_adi,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {'bolum': tr_clean(res[0]), 'net': res[1], 'puan': res[2], 'alan': res[3] or 'SAY'}
    return None

def generate_ai_study_plan(eksik_listesi):
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    study_plan = {day: [] for day in days}
    
    if not eksik_listesi:
        study_plan["Pazartesi"].append("Genel TYT/AYT Tekrarı + 40 Paragraf Soru Çözümü")
        study_plan["Salı"].append("Matematik Genel Soru Bankası Tarama (50 Soru)")
        study_plan["Çarşamba"].append("Fen / Sosyal Bilimler Özet Okumaları")
        study_plan["Perşembe"].append("Haftalık Konu Denemesi Çözümü")
        study_plan["Cuma"].append("Geçmiş Yanlış Sorular Kitapçığı İncelemesi")
        study_plan["Cumartesi"].append("Tam Boy TYT / AYT Deneme Sınavı")
        study_plan["Pazar"].append("Deneme Analizi ve Dinlenme")
        return study_plan

    idx = 0
    for item in eksik_listesi:
        ders = tr_clean(item.get('ders', 'Genel'))
        konu = tr_clean(item.get('konu', 'Konu Tekrarı'))
        day_name = days[idx % 6]
        task = f"📌 {ders}: {konu} (Konu Anlatım + 30 Soru)"
        study_plan[day_name].append(task)
        idx += 1
        
    study_plan["Pazar"].append("📝 Haftalık Genel Deneme Sınavı & Eksik Analizi")
    return study_plan

# --- REPORTLAB GELİŞMİŞ TÜRKÇE FONT YÜKLEME SİSTEMİ ---
def register_turkish_fonts():
    """İşletim sistemindeki veya proje klasöründeki Türkçe TTF fontları tarayıp ReportLab'a kaydeder."""
    font_candidates = [
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"), # Proje klasöründeki font
        ("arial.ttf", "arialbd.ttf"),             # Proje klasöründeki font
        ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
        ("C:\\Windows\\Fonts\\calibri.ttf", "C:\\Windows\\Fonts\\calibrib.ttf"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\segoeuib.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
    ]
    for norm_path, bold_path in font_candidates:
        if os.path.exists(norm_path):
            try:
                b_path = bold_path if os.path.exists(bold_path) else norm_path
                registerFont(TTFont('TRFont', norm_path))
                registerFont(TTFont('TRFont-Bold', b_path))
                registerFontFamily('TRFont', normal='TRFont', bold='TRFont-Bold')
                return 'TRFont', 'TRFont-Bold'
            except Exception:
                continue
    return 'Helvetica', 'Helvetica-Bold'

def generate_pdf_report(ogr_adi, hedef, df_sonuclari, eksik_konular, halledilen_konular, ai_plan, notlar):
    if not REPORTLAB_AVAILABLE:
        return None

    font_normal, font_bold = register_turkish_fonts()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=25, leftMargin=25, topMargin=20, bottomMargin=20)
    
    title_style = ParagraphStyle('TitleStyle', fontName=font_bold, fontSize=13, textColor=colors.HexColor('#1A365D'), alignment=1, spaceAfter=2)
    sub_title_style = ParagraphStyle('SubTitleStyle', fontName=font_normal, fontSize=8, textColor=colors.gray, alignment=1, spaceAfter=8)
    section_style = ParagraphStyle('SectionStyle', fontName=font_bold, fontSize=9, textColor=colors.HexColor('#2B6CB0'), spaceBefore=6, spaceAfter=3)
    normal_style = ParagraphStyle('NormalStyle', fontName=font_normal, fontSize=7.5, leading=9.5)
    bold_style = ParagraphStyle('BoldStyle', fontName=font_bold, fontSize=7.5, leading=9.5)
    
    elements = []
    
    # 1. BAŞLIK & BİLGİ KARTI
    kurum_adi, _ = get_kurum_bilgileri()
    elements.append(Paragraph(tr_clean(kurum_adi).upper(), title_style))
    elements.append(Paragraph("ÖĞRENCİ GELİŞİM VE KAZANIM EVALÜASYON KARNESİ", sub_title_style))
    
    last_row = df_sonuclari.iloc[-1] if not df_sonuclari.empty else {}
    hedef_str = f"{tr_clean(hedef['bolum'])} (Hedef Net: {hedef['net']})" if hedef else "Belirtilmedi"
    
    info_data = [
        [Paragraph(f"Öğrenci Adı: {tr_clean(ogr_adi)}", bold_style), Paragraph(f"Hedef: {hedef_str}", normal_style)],
        [Paragraph(f"Son TYT Puanı: {last_row.get('tyt_puan', 0):.2f}", normal_style), Paragraph(f"Son Kurum Sırası: {int(last_row.get('kurum_sirasi', 0)) if pd.notna(last_row.get('kurum_sirasi')) else '-'}", normal_style)]
    ]
    t_info = Table(info_data, colWidths=[270, 275])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F7FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 4))
    
    # 2. NET GELİŞİM GRAFİĞİ
    elements.append(Paragraph("Sınav Net Gelişim Grafiği", section_style))
    if not df_sonuclari.empty:
        fig, ax = plt.subplots(figsize=(7, 1.6))
        if 'tyt_toplam' in df_sonuclari.columns:
            ax.plot(df_sonuclari['sinav_adi'].apply(tr_clean), df_sonuclari['tyt_toplam'], marker='o', color='#2B6CB0', linewidth=1.5, label='TYT Net')
        if 'ayt_toplam' in df_sonuclari.columns and (df_sonuclari['ayt_toplam'] > 0).any():
            ax.plot(df_sonuclari['sinav_adi'].apply(tr_clean), df_sonuclari['ayt_toplam'], marker='s', color='#E53E3E', linewidth=1.5, label='AYT Net')
            
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.set_ylim(0, 120)
        plt.xticks(rotation=0, fontsize=6.5)
        plt.yticks(fontsize=6.5)
        ax.legend(loc='upper left', fontsize=6.5)
        
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png', bbox_inches='tight', dpi=150)
        plt.close(fig)
        img_buf.seek(0)
        elements.append(Image(img_buf, width=545, height=105))
    elements.append(Spacer(1, 4))

    # 3. KAZANIM VE KONU DURUMU
    elements.append(Paragraph("Kazanım ve Konu Durum Analizi", section_style))
    
    eksik_text = "<br/>".join([f"• [{tr_clean(ek.get('ders',''))}] {tr_clean(ek.get('konu',''))}" for ek in eksik_konular[:5]]) if eksik_konular else "• Belirgin bir eksik konu tespit edilmedi."
    halledilen_text = "<br/>".join([f"• [{tr_clean(h.get('ders',''))}] {tr_clean(h.get('konu',''))}" for h in halledilen_konular[:5]]) if halledilen_konular else "• Geçmiş sınavlardan tamamen çözülmüş konu kaydı yok."

    kazanim_data = [
        [Paragraph("Acil Müdahale Gereken Konular", bold_style), Paragraph("Başarıyla Halledilen Konular", bold_style)],
        [Paragraph(eksik_text, normal_style), Paragraph(halledilen_text, normal_style)]
    ]
    t_kazanim = Table(kazanim_data, colWidths=[270, 275])
    t_kazanim.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor("#FFF5F5")),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor("#F0FFF4")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(t_kazanim)
    elements.append(Spacer(1, 4))

    # 4. HAFTALIK ÇALIŞMA PROGRAMI
    elements.append(Paragraph("Yapay Zekâ Destekli Haftalık Çalışma Programı", section_style))
    plan_data = [[Paragraph("<b>Gün</b>", bold_style), Paragraph("<b>Atanan Görev ve Çalışma Odağı</b>", bold_style)]]
    for day, tasks in ai_plan.items():
        task_str = " <br/> ".join([tr_clean(t) for t in tasks]).replace("**", "")
        plan_data.append([Paragraph(tr_clean(day), bold_style), Paragraph(task_str if task_str else "Serbest Çalışma / Soru Çözümü", normal_style)])
    
    t_plan = Table(plan_data, colWidths=[100, 445])
    t_plan.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2B6CB0')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('PADDING', (0,0), (-1,-1), 3.5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    elements.append(t_plan)
    elements.append(Spacer(1, 4))
    
    # 5. REHBERLİK NOTU
    elements.append(Paragraph("Rehberlik & Öğretmen Görüşü", section_style))
    not_text = "<br/>".join([f"• {tr_clean(n)}" for n in notlar[:2]]) if notlar else "Öğrencimizin sınav grafiklerindeki ivmesi yakından takip edilmektedir. Yukarıda belirtilen eksik konulara odaklanılması önerilir."
    elements.append(Paragraph(not_text, ParagraphStyle('NoteStyle', parent=normal_style, fontName=font_normal, backColor=colors.HexColor("#EDF2F7"), borderPadding=4, borderColor=colors.HexColor("#CBD5E0"), borderLineWidth=1)))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- EKRAN SUNUMU ---
def render_student_report(norm_adi, ogr_adi, allow_notes=False):
    conn = sqlite3.connect("sinav_takip.db")
    
    st.header(f"👤 Öğrenci: {tr_clean(ogr_adi)}")
    
    hedef = get_ogrenci_hedef(norm_adi)
    if hedef:
        st.info(f"🎯 **Hedef Bölüm:** {hedef['bolum']} | **Alan:** {hedef.get('alan', 'SAY')} | **Hedef Net:** {hedef['net']} | **Hedef Puan:** {hedef['puan']}")
    
    view_type = st.radio("İncelenecek Sınav Türünü Seçin:", ["Tümü", "TYT", "AYT"], horizontal=True)
    
    # Güvenli Sorgu: Kolonların varlığını kontrol etmek yerine doğrudan SELECT veya COALESCE kullanıyoruz
    try:
        df_sonuc = pd.read_sql_query('''
            SELECT s.sinav_id, s.sinav_adi, s.tarih,
                   COALESCE(s.sinav_turu, 'TYT') as sinav_turu,
                   COALESCE(os.turkce_net, 0) as turkce_net, 
                   COALESCE(os.sosyal_net, 0) as sosyal_net, 
                   COALESCE(os.matematik_net, 0) as matematik_net, 
                   COALESCE(os.fen_net, 0) as fen_net, 
                   COALESCE(os.toplam_net, 0) as tyt_toplam, 
                   COALESCE(os.tyt_puan, 0) as tyt_puan,
                   COALESCE(os.ayt_mat_net, 0) as ayt_mat_net, 
                   COALESCE(os.ayt_fizik_net, 0) as ayt_fizik_net, 
                   COALESCE(os.ayt_kimya_net, 0) as ayt_kimya_net, 
                   COALESCE(os.ayt_biyo_net, 0) as ayt_biyo_net, 
                   COALESCE(os.ayt_edebiyat_net, 0) as ayt_edebiyat_net, 
                   COALESCE(os.ayt_tarih1_net, 0) as ayt_tarih1_net, 
                   COALESCE(os.ayt_cogr1_net, 0) as ayt_cogr1_net, 
                   COALESCE(os.ayt_toplam_net, 0) as ayt_toplam,
                   COALESCE(os.ayt_say_puan, 0) as ayt_say_puan, 
                   COALESCE(os.ayt_ea_puan, 0) as ayt_ea_puan, 
                   COALESCE(os.kurum_sirasi, 0) as kurum_sirasi
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE os.ogrenci_adi_norm LIKE ?
            ORDER BY s.tarih ASC, s.sinav_id ASC
        ''', conn, params=(f"%{norm_adi}%",))
    except Exception as e:
        st.error("Veritabanı okunurken bir hata oluştu. Lütfen veritabanını sıfırlamayı veya eski sınav kaydını silip tekrar yüklemeyi deneyin.")
        conn.close()
        return
    
    if view_type != "Tümü":
        df_filtered = df_sonuc[
            (df_sonuc['sinav_turu'].str.upper() == view_type) | 
            (df_sonuc['sinav_adi'].str.contains(view_type, case=False, na=False))
        ]
    else:
        df_filtered = df_sonuc.copy()

    eksik_konu_listesi = []
    halledilen_konu_listesi = []

    if not df_filtered.empty:
        st.subheader(f"📈 Sınav Net Gelişimi ({view_type})")
        fig, ax = plt.subplots(figsize=(10, 3.5))
        
        df_tyt = df_filtered[(df_filtered['sinav_turu'] == 'TYT') | (df_filtered['sinav_adi'].str.contains('TYT', case=False, na=False))]
        df_ayt = df_filtered[(df_filtered['sinav_turu'] == 'AYT') | (df_filtered['sinav_adi'].str.contains('AYT', case=False, na=False))]
        
        if view_type in ["Tümü", "TYT"] and not df_tyt.empty:
            ax.plot(df_tyt['sinav_adi'].apply(tr_clean), df_tyt['tyt_toplam'], marker='o', color='#3182ce', linewidth=2, label='TYT Toplam Net')
        if view_type in ["Tümü", "AYT"] and not df_ayt.empty:
            ax.plot(df_ayt['sinav_adi'].apply(tr_clean), df_ayt['ayt_toplam'], marker='s', color='#e53e3e', linewidth=2, label='AYT Toplam Net')
            
        if hedef and hedef['net']:
            ax.axhline(y=hedef['net'], color='g', linestyle='--', label=f"Hedef Net ({hedef['net']})")
            
        ax.set_ylabel("Net")
        plt.xticks(rotation=30, ha='right')
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend()
        st.pyplot(fig)
        
        st.subheader("📊 Sınav Detay Tablosu")
        cols_to_show = ['sinav_adi', 'tarih', 'sinav_turu']
        if view_type == "TYT":
            cols_to_show += ['turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'tyt_toplam', 'tyt_puan', 'kurum_sirasi']
        elif view_type == "AYT":
            cols_to_show += ['ayt_mat_net', 'ayt_fizik_net', 'ayt_kimya_net', 'ayt_biyo_net', 'ayt_edebiyat_net', 'ayt_tarih1_net', 'ayt_cogr1_net', 'ayt_toplam', 'ayt_say_puan', 'ayt_ea_puan', 'kurum_sirasi']
        else:
            cols_to_show += ['tyt_toplam', 'ayt_toplam', 'tyt_puan', 'ayt_say_puan', 'kurum_sirasi']
            
        existing_cols = [c for c in cols_to_show if c in df_filtered.columns]
        st.dataframe(df_filtered[existing_cols], use_container_width=True)
        
        st.markdown("---")
        c_eksik, c_basari = st.columns(2)
        
        son_sinav_id = df_filtered['sinav_id'].iloc[-1]
        
        df_tum_eksikler = pd.read_sql_query('''
            SELECT sinav_id, ders, konu_kazanim
            FROM ogrenci_eksikleri
            WHERE ogrenci_adi_norm LIKE ?
        ''', conn, params=(f"%{norm_adi}%",))

        if not df_tum_eksikler.empty:
            df_tum_eksikler['ders'] = df_tum_eksikler['ders'].apply(tr_clean)
            df_tum_eksikler['konu_kazanim'] = df_tum_eksikler['konu_kazanim'].apply(tr_clean)

        with c_eksik:
            st.subheader("⚠️ Aktif Eksik / Çalışılması Gereken Konular")
            if not df_tum_eksikler.empty:
                df_son_eksik = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]
                if not df_son_eksik.empty:
                    for _, row in df_son_eksik.iterrows():
                        eksik_konu_listesi.append({'ders': tr_clean(row['ders']), 'konu': tr_clean(row['konu_kazanim'])})
                    
                    df_eksik_ozet = df_son_eksik.groupby(['ders', 'konu_kazanim']).size().reset_index(name='Tekrar Sayısı')
                    df_eksik_ozet.columns = ['Ders', 'Konu / Kazanım', 'Tekrar Sayısı']
                    st.dataframe(df_eksik_ozet, use_container_width=True)
                else:
                    st.success("🎉 Son sınavda tespit edilen yeni bir konu eksiği yok.")
            else:
                st.success("Tebrikler! Belirlenmiş bir konu eksiğiniz bulunmuyor.")

        with c_basari:
            st.subheader("✅ Başarıyla Halledilen Konular")
            if not df_tum_eksikler.empty:
                gecmis_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] != son_sinav_id]['konu_kazanim'].unique()
                son_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]['konu_kazanim'].unique()
                halledilen_konular = [konu for konu in gecmis_eksikler if konu not in son_eksikler]
                
                if halledilen_konular:
                    df_halledilen = df_tum_eksikler[df_tum_eksikler['konu_kazanim'].isin(halledilen_konular)][['ders', 'konu_kazanim']].drop_duplicates()
                    for _, row in df_halledilen.iterrows():
                        halledilen_konu_listesi.append({'ders': tr_clean(row['ders']), 'konu': tr_clean(row['konu_kazanim'])})
                    df_halledilen.columns = ['Ders', 'Konu / Kazanım']
                    st.dataframe(df_halledilen, use_container_width=True)
                else:
                    st.info("Henüz düzeltilmiş bir konu kaydı bulunmuyor.")
            else:
                st.info("Henüz karşılaştırma yapılacak eksik veri yok.")
    else:
        st.warning(f"Bu öğrenciye ait {view_type} türünde girilmiş bir sınav sonucu bulunamadı.")
        
    st.markdown("---")
    st.subheader("🤖 Yapay Zeka Destekli Kişiselleştirilmiş Çalışma Programı")
    ai_study_plan = generate_ai_study_plan(eksik_konu_listesi)
    
    col_days = st.columns(len(ai_study_plan))
    for i, (day, tasks) in enumerate(ai_study_plan.items()):
        with col_days[i]:
            st.markdown(f"**{day}**")
            if tasks:
                for t in tasks:
                    st.caption(t)
            else:
                st.caption("Genel Tekrar / Serbest")

    df_notlar = pd.read_sql_query("SELECT tarih, not_metni FROM ogretmen_notlari WHERE ogrenci_adi_norm = ? ORDER BY id DESC", conn, params=(norm_adi,))
    notlar_list = [tr_clean(n) for n in df_notlar['not_metni'].tolist()] if not df_notlar.empty else []

    if allow_notes:
        st.markdown("---")
        st.subheader("📝 Öğretmen Görüş ve Notları")
        with st.form("ogretmen_not_form"):
            yeni_not = st.text_area("Öğrenci Hakkında Not Ekleyin:")
            if st.form_submit_button("Notu Kaydet"):
                if yeni_not.strip():
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO ogretmen_notlari (ogrenci_adi_norm, tarih, not_metni) VALUES (?, DATE('now'), ?)", (norm_adi, tr_clean(yeni_not.strip())))
                    conn.commit()
                    st.success("Not kaydedildi!")
                    st.rerun()

    st.markdown("---")
    st.subheader("📄 PDF Karne & Analiz Raporu İndir")
    if REPORTLAB_AVAILABLE:
        pdf_file = generate_pdf_report(ogr_adi, hedef, df_filtered, eksik_konu_listesi, halledilen_konu_listesi, ai_study_plan, notlar_list)
        if pdf_file:
            st.download_button(
                label="📥 Kusursuz Kurumsal PDF Karneyi İndir",
                data=pdf_file,
                file_name=f"{norm_adi}_Gelisim_Karnesi.pdf",
                mime="application/pdf",
                type="primary"
            )

    conn.close()

# --- AUTHENTICATION & LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_info' not in st.session_state:
    st.session_state['user_info'] = None
if 'role' not in st.session_state:
    st.session_state['role'] = None

def login():
    st.title("🎓 Sınav Takip & Analiz Portalı Girişi")
    kurum_adi, logo_b64 = get_kurum_bilgileri()
    if logo_b64:
        st.markdown(f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_b64}" width="150"></div>', unsafe_allow_html=True)
    st.subheader(kurum_adi)
    
    with st.form("login_form"):
        username = st.text_input("Kullanıcı Adı:")
        password = st.text_input("Şifre:", type="password")
        submit = st.form_submit_button("Giriş Yap")
        
        if submit:
            conn = sqlite3.connect("sinav_takip.db")
            cursor = conn.cursor()
            cursor.execute("SELECT kullanici_adi, rol, ogrenci_adi_norm FROM kullanicilar WHERE kullanici_adi = ? AND sifre = ?", (username.strip(), password.strip()))
            user = cursor.fetchone()
            conn.close()
            
            if user:
                st.session_state['logged_in'] = True
                st.session_state['user_info'] = {'username': user[0], 'norm_adi': user[2]}
                st.session_state['role'] = user[1]
                st.success("Giriş başarılı!")
                st.rerun()
            else:
                st.error("Hatalı kullanıcı adı veya şifre.")

if not st.session_state['logged_in']:
    login()
    st.stop()

# --- SIDEBAR & NAV ---
kurum_adi, logo_b64 = get_kurum_bilgileri()
if logo_b64:
    st.sidebar.markdown(f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_b64}" width="100"></div>', unsafe_allow_html=True)
st.sidebar.title(kurum_adi)
st.sidebar.write(f"👤 **{st.session_state['user_info']['username']}** ({st.session_state['role'].upper()})")

if st.sidebar.button("🚪 Çıkış Yap"):
    st.session_state['logged_in'] = False
    st.session_state['user_info'] = None
    st.session_state['role'] = None
    st.rerun()

st.sidebar.markdown("---")

if st.session_state['role'] in ['admin', 'ogretmen']:
    menu_options = [
        "📥 Sınav Yükle & Veri Aktarımı",
        "📊 Öğrenci Karneleri & Analiz",
        "📚 Ödev & Soru Bankası Takibi",
        "📱 Veli Bilgilendirme & WhatsApp/SMS",
        "🎯 Hedef Belirleme & Takip",
        "🏫 Okul Genel Durumu & Dereceler",
        "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım",
        "🔥 Okul Konu/Kazanım Analizi"
    ]
    if st.session_state['role'] == 'admin':
        menu_options.extend([
            "👥 Öğrenci & Veli Hesap Yönetimi",
            "⚙️ Kurum Ayarları & Logo",
            "🗑️ Sınav Yönetimi & Silme"
        ])
else:
    menu_options = [
        "🎓 Gelişim & Analiz Karnem",
        "📚 Ödevlerim & Ödev Durumu",
        "🎯 Üniversite / Hedefim"
    ]

secim = st.sidebar.radio("Navigasyon Menüsü:", menu_options)

# --- PAGE ROUTING ---
if secim == "📥 Sınav Yükle & Veri Aktarımı" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📥 Sınav Sonuçları ve Analiz PDF Yükleme")
    
    c1, c2, c3, c4 = st.columns(4)
    sinav_adi = c1.text_input("Sınav Adı:", placeholder="Örn: Özdebir AYT Deneme-1")
    yayin_evi = c2.text_input("Yayın Evi:", placeholder="Örn: Özdebir")
    sinav_turu = c3.selectbox("Sınav Türü:", ["AYT", "TYT", "TYT+AYT"])
    sinav_tarihi = c4.date_input("Sınav Tarihi")
    
    excel_file = st.file_uploader("📊 Sınav Sonuç Excel / CSV Dosyası Yükleyin:", type=["xlsx", "xls", "csv"])
    pdf_files = st.file_uploader("📑 Öğrenci Eksik Analiz PDF Dosyalarını Yükleyin:", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 Sınavı ve Analizleri Sisteme Aktar", type="primary"):
        if sinav_adi and excel_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()
                
                cursor.execute("INSERT INTO sinavlar (sinav_adi, tarih, yayin_evi, sinav_turu) VALUES (?, ?, ?, ?)", (tr_clean(sinav_adi), str(sinav_tarihi), tr_clean(yayin_evi), sinav_turu))
                sinav_id = cursor.lastrowid
                
                df = pd.read_csv(excel_file) if excel_file.name.endswith('.csv') else pd.read_excel(excel_file)
                
                for _, row in df.iterrows():
                    ogr_adi = tr_clean(str(get_col_val(row, ['ad soyad', 'ogrenci adi', 'ad', 'isim'], default="")))
                    ogr_norm = normalize_name(ogr_adi)
                    sinif = tr_clean(str(get_col_val(row, ['sinif', 'sınıf'], default="")))
                    
                    if ogr_norm:
                        cursor.execute('''
                        INSERT INTO ogrenci_sonuclari (
                            sinav_id, ogrenci_adi, ogrenci_adi_norm, sinif, kurum_sirasi,
                            turkce_net, sosyal_net, matematik_net, fen_net, toplam_net, tyt_puan,
                            ayt_mat_net, ayt_fizik_net, ayt_kimya_net, ayt_biyo_net,
                            ayt_edebiyat_net, ayt_tarih1_net, ayt_cogr1_net,
                            ayt_tarih2_net, ayt_cogr2_net, ayt_felsefe_net, ayt_din_net,
                            ayt_toplam_net, ayt_say_puan, ayt_ea_puan, ayt_soz_puan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            sinav_id, ogr_adi, ogr_norm, sinif,
                            get_col_val(row, ['kurum sira', 'sira', 'derece'], 0),
                            get_col_val(row, ['turkce net', 'tr net', 'turkce'], 0),
                            get_col_val(row, ['sosyal net', 'sos net', 'sosyal'], 0),
                            get_col_val(row, ['matematik net', 'mat net', 'tyt mat'], 0),
                            get_col_val(row, ['fen net', 'fn net', 'fen'], 0),
                            get_col_val(row, ['toplam net', 'tyt toplam', 'tyt net'], 0),
                            get_col_val(row, ['tyt puan', 'puan'], 0),
                            get_col_val(row, ['ayt mat net', 'ayt matematik', 'ayt mat'], 0),
                            get_col_val(row, ['ayt fizik', 'fizik net'], 0),
                            get_col_val(row, ['ayt kimya', 'kimya net'], 0),
                            get_col_val(row, ['ayt biyo', 'biyoloji net'], 0),
                            get_col_val(row, ['ayt edebiyat', 'edebiyat net'], 0),
                            get_col_val(row, ['ayt tarih1', 'tarih 1 net'], 0),
                            get_col_val(row, ['ayt cogr1', 'cografya 1 net'], 0),
                            get_col_val(row, ['ayt tarih2'], 0),
                            get_col_val(row, ['ayt cogr2'], 0),
                            get_col_val(row, ['ayt felsefe'], 0),
                            get_col_val(row, ['ayt din'], 0),
                            get_col_val(row, ['ayt toplam', 'ayt net'], 0),
                            get_col_val(row, ['ayt say puan', 'say puan'], 0),
                            get_col_val(row, ['ayt ea puan', 'ea puan'], 0),
                            get_col_val(row, ['ayt soz puan', 'soz puan'], 0)
                        ))
                
                if pdf_files:
                    try:
                        import pypdf
                        for pdf in pdf_files:
                            pdf_name = tr_clean(pdf.name.replace(".pdf", ""))
                            pdf_norm_name = normalize_name(pdf_name)
                            
                            reader = pypdf.PdfReader(pdf)
                            full_text = ""
                            for page in reader.pages:
                                txt = page.extract_text()
                                if txt:
                                    full_text += txt + "\n"
                            
                            full_text = tr_clean(full_text)
                            lines = full_text.split('\n')
                            for line in lines:
                                if ":" in line:
                                    parts = line.split(":")
                                    konu_temiz = tr_clean(parts[0].strip())
                                    sorular = tr_clean(parts[1].strip()) if len(parts) > 1 else ""
                                    tespit_edilen_ders = detect_subject_from_topic(konu_temiz)
                                    
                                    cursor.execute('''
                                    INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (sinav_id, pdf_name, pdf_norm_name, tespit_edilen_ders, konu_temiz, sorular))
                    except ImportError:
                        st.warning("PyPDF kütüphanesi eksik.")

                conn.commit()
                conn.close()
                st.success(f"✅ '{sinav_adi}' verileri temizlenerek başarıyla aktarıldı!")
            except Exception as e:
                st.error(f"Aktarım hatası: {str(e)}")
        else:
            st.warning("Lütfen dosya seçin ve sınav adını girin.")

elif secim in ["📊 Öğrenci Karneleri & Analiz", "🎓 Gelişim & Analiz Karnem"]:
    st.title("📑 Öğrenci Gelişim Karnesi & AI Çalışma Programı")
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC", conn)
        if not df_ogrenciler.empty:
            ogr_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi'].apply(tr_clean)))
            secilen_norm = st.selectbox("Analiz Edilecek Öğrenciyi Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            secilen_ogr_adi = ogr_dict[secilen_norm]
            render_student_report(secilen_norm, secilen_ogr_adi, allow_notes=True)
        else:
            st.info("Sistemde kayıtlı öğrenci sonucu yok.")
    else:
        norm_adi = st.session_state['user_info']['norm_adi']
        if norm_adi:
            render_student_report(norm_adi, st.session_state['user_info']['username'], allow_notes=False)
        else:
            st.warning("Öğrenci kaydınız bulunamadı.")
    conn.close()

elif secim in ["📚 Ödev & Soru Bankası Takibi", "📚 Ödevlerim & Ödev Durumu"]:
    st.title("📚 Ödev & Soru Bankası Takip Modülü")
    conn = sqlite3.connect("sinav_takip.db")
    if st.session_state['role'] in ['admin', 'ogretmen']:
        tab_odev_ver, tab_odev_liste = st.tabs(["➕ Yeni Ödev Ver", "📋 Ödev Durumları & Kontrol"])
        with tab_odev_ver:
            c1, c2, c3 = st.columns(3)
            sinif_secim = c1.selectbox("Sınıf / Grup:", ["Tüm Sınıflar", "12-A", "12-B", "11-A", "Mezun"])
            ders_secim = c2.selectbox("Ders:", ["Matematik", "Fizik", "Kimya", "Biyoloji", "Türkçe / Edebiyat", "Tarih", "Coğrafya", "Felsefe / Din"])
            son_tarih = c3.date_input("Son Teslim Tarihi")
            konu_kaynak = st.text_input("Ödev Konusu / Kaynak:")
            if st.button("🚀 Ödevi Yayınla", type="primary"):
                if konu_kaynak.strip():
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO odevler (sinif, ders, konu_kaynak, son_tarih, eklenme_tarihi) VALUES (?, ?, ?, ?, DATE('now'))", (sinif_secim, ders_secim, tr_clean(konu_kaynak), str(son_tarih)))
                    odev_id = cursor.lastrowid
                    df_ogrs = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm FROM ogrenci_sonuclari", conn)
                    for _, row in df_ogrs.iterrows():
                        cursor.execute("INSERT OR IGNORE INTO odev_takip (odev_id, ogrenci_adi_norm) VALUES (?, ?)", (odev_id, row['ogrenci_adi_norm']))
                    conn.commit()
                    st.success("Ödev yayınlandı!")
        with tab_odev_liste:
            df_odevler = pd.read_sql_query("SELECT * FROM odevler ORDER BY odev_id DESC", conn)
            if not df_odevler.empty:
                secilen_odev_id = st.selectbox("İncelenecek Ödev:", df_odevler['odev_id'].tolist(), format_func=lambda x: f"ID:{x} - {df_odevler[df_odevler['odev_id']==x]['ders'].values[0]} ({df_odevler[df_odevler['odev_id']==x]['konu_kaynak'].values[0]})")
                df_takip = pd.read_sql_query("SELECT ot.id, os.ogrenci_adi, os.sinif, ot.durum, ot.aciklama FROM odev_takip ot JOIN ogrenci_sonuclari os ON ot.ogrenci_adi_norm = os.ogrenci_adi_norm WHERE ot.odev_id = ? GROUP BY ot.ogrenci_adi_norm", conn, params=(secilen_odev_id,))
                if not df_takip.empty:
                    df_takip['ogrenci_adi'] = df_takip['ogrenci_adi'].apply(tr_clean)
                    edited_df = st.data_editor(df_takip, column_config={"durum": st.column_config.SelectboxColumn("Ödev Durumu", options=["Bekliyor", "Tamamlandı", "Eksik Yapıldı", "Yapılmadı"], required=True)}, disabled=["id", "ogrenci_adi", "sinif"], use_container_width=True)
                    if st.button("💾 Kaydet"):
                        cursor = conn.cursor()
                        for _, row in edited_df.iterrows():
                            cursor.execute("UPDATE odev_takip SET durum = ?, aciklama = ? WHERE id = ?", (row['durum'], tr_clean(row['aciklama']), row['id']))
                        conn.commit()
                        st.success("Güncellendi!")
    else:
        norm_adi = st.session_state['user_info']['norm_adi']
        df_my_odev = pd.read_sql_query("SELECT o.ders, o.konu_kaynak, o.son_tarih, ot.durum, ot.aciklama FROM odev_takip ot JOIN odevler o ON ot.odev_id = o.odev_id WHERE ot.ogrenci_adi_norm = ? ORDER BY o.son_tarih DESC", conn, params=(norm_adi,))
        st.dataframe(df_my_odev, use_container_width=True) if not df_my_odev.empty else st.info("Atanmış ödeviniz yok.")
    conn.close()

elif secim == "📱 Veli Bilgilendirme & WhatsApp/SMS":
    st.title("📱 Veli Bilgilendirme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    df_veliler = pd.read_sql_query("SELECT kullanici_adi, telefon FROM kullanicilar WHERE telefon IS NOT NULL AND telefon != ''", conn)
    if not df_veliler.empty:
        secilen_kullanici = st.selectbox("Kişi Seçin:", df_veliler['kullanici_adi'].tolist())
        tel_no = df_veliler[df_veliler['kullanici_adi'] == secilen_kullanici]['telefon'].values[0]
        mesaj = st.text_area("Mesaj Metni:", f"Sayın Velimiz, öğrencimiz {secilen_kullanici}'in sınav karnesi sisteme eklenmiştir.")
        if mesaj:
            encoded_msg = urllib.parse.quote(mesaj)
            st.markdown(f'<a href="https://wa.me/{tel_no}?text={encoded_msg}" target="_blank"><button style="background-color:#25D366; color:white; border:none; padding:10px 20px; border-radius:5px; cursor:pointer;">💬 WhatsApp ile Gönder ({tel_no})</button></a>', unsafe_allow_html=True)
    else:
        st.warning("Telefonu olan kullanıcı bulunamadı.")
    conn.close()

elif secim in ["🎯 Hedef Belirleme & Takip", "🎯 Üniversite / Hedefim"]:
    st.title("🎯 Hedef Takip Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogr = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC", conn)
        if not df_ogr.empty:
            ogr_dict = dict(zip(df_ogr['ogrenci_adi_norm'], df_ogr['ogrenci_adi'].apply(tr_clean)))
            secilen_norm = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            hedef_mevcut = get_ogrenci_hedef(secilen_norm)
            with st.form("hedef_form"):
                hedef_bolum = st.text_input("Hedef Bölüm:", value=hedef_mevcut['bolum'] if hedef_mevcut else "")
                alan_tercihi = st.selectbox("Alan:", ["SAY", "EA", "SÖZ", "DİL"])
                hedef_net = st.number_input("Hedef Net:", value=float(hedef_mevcut['net']) if hedef_mevcut else 75.0)
                hedef_puan = st.number_input("Hedef Puan:", value=float(hedef_mevcut['puan']) if hedef_mevcut else 350.0)
                if st.form_submit_button("🎯 Kaydet"):
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan, alan_tercihi) VALUES (?, ?, ?, ?, ?) ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET hedef_bolum=excluded.hedef_bolum, hedef_net=excluded.hedef_net, hedef_puan=excluded.hedef_puan, alan_tercihi=excluded.alan_tercihi", (secilen_norm, tr_clean(hedef_bolum), hedef_net, hedef_puan, alan_tercihi))
                    conn.commit()
                    st.success("Kaydedildi!")
    else:
        hedef = get_ogrenci_hedef(st.session_state['user_info']['norm_adi'])
        st.success(f"Hedef: {hedef['bolum']}") if hedef else st.info("Hedef bulunamadı.")
    conn.close()

elif secim == "🏫 Okul Genel Durumu & Dereceler":
    st.title("🏫 Okul Genel Durumu")
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar ORDER BY sinav_id DESC", conn)
    if not df_sinavlar.empty:
        secilen_sinav_id = st.selectbox("Sınav Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: tr_clean(df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0]))
        df_derece = pd.read_sql_query("SELECT kurum_sirasi as 'Sıra', ogrenci_adi as 'Öğrenci', sinif as 'Sınıf', toplam_net as 'TYT Toplam', ayt_toplam_net as 'AYT Toplam' FROM ogrenci_sonuclari WHERE sinav_id = ? ORDER BY kurum_sirasi ASC", conn, params=(secilen_sinav_id,))
        if not df_derece.empty:
            df_derece['Öğrenci'] = df_derece['Öğrenci'].apply(tr_clean)
        st.dataframe(df_derece, use_container_width=True)
    conn.close()

elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım":
    st.title("🕸️ Sınıf Ortalamaları")
    conn = sqlite3.connect("sinav_takip.db")
    df_sinif = pd.read_sql_query("SELECT sinif, AVG(toplam_net) as 'TYT Ort', AVG(ayt_toplam_net) as 'AYT Ort' FROM ogrenci_sonuclari GROUP BY sinif", conn)
    st.dataframe(df_sinif, use_container_width=True) if not df_sinif.empty else st.info("Veri yok.")
    conn.close()

elif secim == "🔥 Okul Konu/Kazanım Analizi":
    st.title("🔥 Konu Analizi")
    conn = sqlite3.connect("sinav_takip.db")
    df_eksik = pd.read_sql_query("SELECT ders as 'Ders', konu_kazanim as 'Konu', COUNT(*) as 'Yanlış Sayısı' FROM ogrenci_eksikleri GROUP BY konu_kazanim ORDER BY [Yanlış Sayısı] DESC LIMIT 15", conn)
    if not df_eksik.empty:
        df_eksik['Ders'] = df_eksik['Ders'].apply(tr_clean)
        df_eksik['Konu'] = df_eksik['Konu'].apply(tr_clean)
    st.dataframe(df_eksik, use_container_width=True) if not df_eksik.empty else st.info("Veri yok.")
    conn.close()

elif secim == "👥 Öğrenci & Veli Hesap Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Hesap Yönetimi")
    conn = sqlite3.connect("sinav_takip.db")
    k_adi = st.text_input("Kullanıcı Adı:")
    sifre = st.text_input("Şifre:")
    rol = st.selectbox("Rol:", ["ogrenci", "veli", "ogretmen", "admin"])
    telefon = st.text_input("Telefon:")
    df_ogrs = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
    ogr_norm = None
    if not df_ogrs.empty and rol in ['ogrenci', 'veli']:
        ogr_dict = dict(zip(df_ogrs['ogrenci_adi_norm'], df_ogrs['ogrenci_adi'].apply(tr_clean)))
        ogr_norm = st.selectbox("İlişkilendirilecek Öğrenci:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
    if st.button("➕ Oluştur"):
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, ?, ?, ?, ?)", (tr_clean(k_adi), sifre, rol, ogr_norm, telefon))
        conn.commit()
        st.success("Hesap oluşturuldu.")
    conn.close()

elif secim == "⚙️ Kurum Ayarları & Logo" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum Ayarları")
    conn = sqlite3.connect("sinav_takip.db")
    kurum_adi, logo_b64 = get_kurum_bilgileri()
    yeni_kurum_adi = st.text_input("Kurum Adı:", value=kurum_adi)
    uploaded_logo = st.file_uploader("Logo Yükleyin:", type=["png", "jpg", "jpeg"])
    if st.button("💾 Kaydet"):
        cursor = conn.cursor()
        b64_str = logo_b64
        if uploaded_logo:
            b64_str = base64.b64encode(uploaded_logo.read()).decode('utf-8')
        cursor.execute("DELETE FROM kurum_ayarlari")
        cursor.execute("INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) VALUES (1, ?, ?)", (tr_clean(yeni_kurum_adi), b64_str))
        conn.commit()
        st.success("Ayarlar güncellendi.")
    conn.close()

elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar ORDER BY sinav_id DESC", conn)
    if not df_sinavlar.empty:
        st.dataframe(df_sinavlar, use_container_width=True)
        silinecek_id = st.selectbox("Silinecek Sınavı Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: f"ID: {x} - {tr_clean(df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0])}")
        if st.button("🔴 Kalıcı Olarak Sil", type="primary"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (silinecek_id,))
            conn.commit()
            st.success("Sınav ve bağlı tüm veriler silindi!")
            st.rerun()
    conn.close()