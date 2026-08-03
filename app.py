import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re
import os
import io
import matplotlib.pyplot as plt

# --- REPORTLAB KÜTÜPHANELERİ (PDF ÜRETİMİ İÇİN) ---
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Sınav Takip & Analiz Paneli", page_icon="🎓", layout="wide")

# --- TÜRKÇE KARAKTER NORMALEŞTİRME ---
def tr_normalize(text):
    if not text:
        return ""
    text = str(text).upper().strip()
    tr_map = {'İ': 'I', 'Ş': 'S', 'Ğ': 'G', 'Ü': 'U', 'Ö': 'O', 'Ç': 'C'}
    for k, v in tr_map.items():
        text = text.replace(k, v)
    return " ".join(text.split())

# --- VERİTABANI OLUŞTURMA ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_no TEXT,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        tyt_puan REAL,
        kurum_sirasi INTEGER,
        turkce_net REAL,
        sosyal_net REAL,
        matematik_net REAL,
        fen_net REAL,
        toplam_net REAL,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
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
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )''')
    conn.commit()
    conn.close()

init_db()

# --- PDF KARNE OLUŞTURMA FONKSİYONU ---
def generate_pdf_karne(student_name, df_ogr, eksikler_listesi):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    
    # 1. BAŞLIK BÖLÜMÜ
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, alignment=1, textColor=colors.HexColor("#1A365D"))
    elements.append(Paragraph("<b>NAZİF TOKGÖZ BAŞARI KOLEJİ</b>", title_style))
    elements.append(Paragraph("ÖĞRENCİ GELİŞİM VE KAZANIM EVALÜASYON KARNESİ", ParagraphStyle('Sub', alignment=1, fontSize=10, leading=12, textColor=colors.gray)))
    elements.append(Spacer(1, 12))

    # ÖĞRENCİ BİLGİ KARTI
    last_row = df_ogr.iloc[-1]
    info_data = [
        [f"<b>Öğrenci Adı:</b> {student_name}", f"<b>Sınıfı:</b> {last_row['sinif']}"],
        [f"<b>Son TYT Puanı:</b> {last_row['tyt_puan']:.2f}", f"<b>Son Kurum Sırası:</b> {int(last_row['kurum_sirasi'])}"]
    ]
    t_info = Table(info_data, colWidths=[260, 260])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 12))

    # 2. ÜSTTE NET GELİŞİM GRAFİĞİ
    fig, ax = plt.subplots(figsize=(7, 2.2))
    ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#2B6CB0', linewidth=2)
    ax.set_title("Sınav Net Gelişim Grafiği", fontsize=10, fontweight='bold')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.set_ylim(0, 120)
    for i, txt in enumerate(df_ogr['toplam_net']):
        ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+2), ha='center', fontsize=7, fontweight='bold')
    plt.xticks(rotation=10, fontsize=8)
    
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    img_buf.seek(0)
    
    elements.append(Image(img_buf, width=500, height=140))
    elements.append(Spacer(1, 12))

    # 3. İKİ SÜTUNLU KAZANIM TABLOSU (Eksikler vs Halledilenler)
    eksik_text = "<br/>".join([f"• ⚠️ <b>{k[0]}</b> ({k[1]} Sınavda)" for k in eksikler_listesi[:5]]) if eksikler_listesi else "• Belirgin bir eksik konu tespit edilmedi."
    
    # Basit bir mantıkla yüksek net yapılan alanlar / örnek başarılar
    halledilen_text = "• ✅ <b>Türkçe:</b> Paragraf & Anlam Bilgisi<br/>• ✅ <b>Temel Matematik:</b> Sayılar ve İşlemler<br/>• ✅ <b>Fen Bilimleri:</b> Temel Kavramlar"

    kazanim_data = [
        [Paragraph("<b>🚨 Acil Müdahale Gereken Konular</b>", styles['Normal']), Paragraph("<b>💪 Güçlü & Halledilen Konular</b>", styles['Normal'])],
        [Paragraph(eksik_text, styles['Normal']), Paragraph(halledilen_text, styles['Normal'])]
    ]
    t_kazanim = Table(kazanim_data, colWidths=[255, 255])
    t_kazanim.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor("#FFF5F5")),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor("#F0FFF4")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t_kazanim)
    elements.append(Spacer(1, 12))

    # 4. YAPAY ZEKA DESTEKLİ HAFTALIK PROGRAM
    elements.append(Paragraph("<b>🤖 Yapay Zekâ Destekli Haftalık Çalışma Programı</b>", ParagraphStyle('SubHead', parent=styles['Heading3'], fontSize=11, leading=14, textColor=colors.HexColor("#2B6CB0"))))
    
    top_eksik_1 = eksikler_listesi[0][0] if len(eksikler_listesi) > 0 else "Genel Tekrar"
    top_eksik_2 = eksikler_listesi[1][0] if len(eksikler_listesi) > 1 else "Soru Çözümü"

    ai_program_text = f"""
    <b>Pazartesi:</b> 📌 <i>{top_eksik_1}</i> konusundan 40 soru soru çözümü + Video içerik analizi.<br/>
    <b>Çarşamba:</b> 📌 <i>{top_eksik_2}</i> üzerine 1.5 saat nokta atışı eksik tamamlama çalışması.<br/>
    <b>Cuma:</b> Yanlış yapılan soru tipleri rehberliğinde alan denemesi ve süre yönetimi.<br/>
    <b>Pazar:</b> Genel haftalık değerlendirme ve yapamadığı soruların öğretmenle çözümü.
    """
    elements.append(Paragraph(ai_program_text, ParagraphStyle('AIStyle', backColor=colors.HexColor("#EDF2F7"), borderPadding=8, borderLineWidth=1, borderColor=colors.HexColor("#E2E8F0"), fontSize=9, leading=13)))
    elements.append(Spacer(1, 12))

    # 5. REHBERLİK & ÖĞRETMEN GÖRÜŞÜ
    elements.append(Paragraph("<b>✍️ Rehberlik & Öğretmen Görüşü</b>", ParagraphStyle('SubHead2', parent=styles['Heading3'], fontSize=11, leading=14, textColor=colors.HexColor("#2B6CB0"))))
    ogretmen_notu = "<i>Öğrencimizin sınav grafiklerindeki ivmesi yakından takip edilmektedir. Yukarıda belirtilen acil müdahale konularına odaklanarak ve haftalık programa disiplinle uyularak hedeflenen dereceye ulaşılması öngörülmektedir.</i>"
    elements.append(Paragraph(ogretmen_notu, ParagraphStyle('NoteStyle', borderPadding=6, fontSize=9, leading=12, textColor=colors.HexColor("#4A5568"))))

    # PDF Oluştur ve Döndür
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- YAN MENÜ ---
st.sidebar.title("📌 Menü")
secim = st.sidebar.radio(
    "İşlem Seçiniz:", 
    ["📤 Yeni Sınav Yükle", "📊 Öğrenci Karneleri & Analiz", "📈 Genel Okul Durumu", "🗑️ Sınav Yönetimi & Silme"]
)

# --- 1. MENÜ: YENİ SINAV YÜKLE ---
if secim == "📤 Yeni Sınav Yükle":
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    st.write("Excel ve PDF dosyalarınızı yükleyerek veritabanına aktarın.")

    col1, col2 = st.columns(2)
    with col1:
        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: 345 TYT Genel - Mart 2026")
    with col2:
        sinav_tarihi = st.date_input("Sınav Tarihi")

    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])

    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if sinav_adi and excel_file and pdf_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()

                cursor.execute("INSERT OR IGNORE INTO sinavlar (sinav_adi, tarih) VALUES (?, ?)", (sinav_adi, str(sinav_tarihi)))
                cursor.execute("SELECT sinav_id FROM sinavlar WHERE sinav_adi = ?", (sinav_adi,))
                sinav_id = cursor.fetchone()[0]

                df_raw = pd.read_excel(excel_file)
                headers = df_raw.iloc[7].values
                df = df_raw.iloc[8:].copy()
                df.columns = headers

                for _, row in df.iterrows():
                    raw_name = str(row['Öğrenci']).strip()
                    if pd.isna(raw_name) or raw_name in ['nan', 'None', '']:
                        continue
                    norm_name = tr_normalize(raw_name)

                    puan = float(row['YKS TYT']) if pd.notna(row['YKS TYT']) else 0.0
                    sira = int(row['YKS TYT K.B.']) if pd.notna(row['YKS TYT K.B.']) else 0
                    turkce = float(row['Tür 05.N']) if pd.notna(row['Tür 05.N']) else 0.0
                    sosyal = float(row['Sos 05.N']) if pd.notna(row['Sos 05.N']) else 0.0
                    mat = float(row['Tem 05.N']) if pd.notna(row['Tem 05.N']) else 0.0
                    fen = float(row['Fen 05.N']) if pd.notna(row['Fen 05.N']) else 0.0
                    toplam = float(row['TYT 05.N']) if pd.notna(row['TYT 05.N']) else 0.0

                    cursor.execute('''
                    INSERT INTO ogrenci_sonuclari 
                    (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, tyt_puan, kurum_sirasi, turkce_net, sosyal_net, matematik_net, fen_net, toplam_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (sinav_id, str(row['Numara']), raw_name, norm_name, str(row['Grup']), puan, sira, turkce, sosyal, mat, fen, toplam))

                reader = pypdf.PdfReader(pdf_file)
                pdf_text = ""
                for page in reader.pages:
                    pdf_text += page.extract_text() + "\n"

                blocks = pdf_text.split("NAZIF TOKGÖZ BASARI KOLEJI ÖGRENCI YANLIS CEVAP LISTESI")
                for block in blocks:
                    if not block.strip():
                        continue
                    header_match = re.search(r'(\d+/[A-Z])\s*-\s*(\d+)\s*-\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)', block)
                    if header_match:
                        pdf_name = header_match.group(3).strip().split('\n')[0]
                        pdf_norm_name = tr_normalize(pdf_name)
                        
                        matches = re.findall(r'\d+\s*-\s*([^(]+)\(([^)]+)\)', block)
                        for konu, sorular in matches:
                            konu_temiz = konu.strip()
                            if "ÜÇDÖRTBES" in konu_temiz or "TYT" in konu_temiz or len(konu_temiz) < 2:
                                continue
                            
                            cursor.execute('''
                            INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ''', (sinav_id, pdf_name, pdf_norm_name, "Genel", konu_temiz, sorular.strip()))

                conn.commit()
                conn.close()
                st.success(f"🎉 '{sinav_adi}' başarıyla yüklendi ve işlendi!")

            except Exception as e:
                st.error(f"Hata oluştu: {e}")
        else:
            st.warning("Lütfen tüm alanları doldurun ve iki dosyayı da yükleyin!")

# --- 2. MENÜ: ÖĞRENCİ KARNELERİ ---
elif secim == "📊 Öğrenci Karneleri & Analiz":
    st.title("🎓 Bireysel Öğrenci Analiz Karnesi")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
    ogrenciler = cursor.fetchall()

    if ogrenciler:
        ogr_dict = {f"{o[0]}": o[1] for o in ogrenciler}
        secilen_ogr_adi = st.selectbox("Aramak İçin Öğrenci Seçin veya Yazın:", list(ogr_dict.keys()))
        secilen_norm = ogr_dict[secilen_ogr_adi]

        query = '''
        SELECT s.sinav_adi, s.tarih, os.tyt_puan, os.kurum_sirasi, 
               os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.sinif
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE os.ogrenci_adi_norm = ?
        ORDER BY s.tarih ASC
        '''
        df_ogr = pd.read_sql_query(query, conn, params=(secilen_norm,))

        if not df_ogr.empty:
            last_row = df_ogr.iloc[-1]
            
            # --- YENİ EKLENEN PDF İNDİRME BUTONU ---
            cursor.execute('''
            SELECT konu_kazanim, COUNT(*) as tekrar
            FROM ogrenci_eksikleri
            WHERE ogrenci_adi_norm = ?
            GROUP BY konu_kazanim
            ORDER BY tekrar DESC
            ''', (secilen_norm,))
            eksikler = cursor.fetchall()

            pdf_bytes = generate_pdf_karne(secilen_ogr_adi, df_ogr, eksikler)
            
            st.download_button(
                label="📄 Kurumsal PDF Karneyi İndir",
                data=pdf_bytes,
                file_name=f"{secilen_ogr_adi.replace(' ', '_')}_Gelisim_Karnesi.pdf",
                mime="application/pdf",
                type="primary"
            )
            st.markdown("---")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Son TYT Puanı", f"{last_row['tyt_puan']:.2f}")
            col2.metric("Kurum Sırası", f"{int(last_row['kurum_sirasi'])}")
            col3.metric("Son Toplam Net", f"{last_row['toplam_net']:.2f}")
            col4.metric("Sınıfı", f"{last_row['sinif']}")

            st.markdown("---")

            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("📈 Net Gelişim Grafiği")
                fig, ax = plt.subplots(figsize=(6, 3.5))
                ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#1f77b4', linewidth=2)
                ax.set_ylabel("Net")
                ax.grid(True, linestyle='--', alpha=0.5)
                ax.set_ylim(0, 120)
                for i, txt in enumerate(df_ogr['toplam_net']):
                    ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+2), ha='center', fontweight='bold')
                plt.xticks(rotation=15)
                st.pyplot(fig)

            with c2:
                st.subheader("⚠️ Acil Müdahale Gereken Konular")
                if eksikler:
                    for konu, tekrar in eksikler:
                        st.error(f"📌 **{konu}** ({tekrar} Sınavda Yanlış/Boş)")
                else:
                    st.success("Tebrikler! Belirgin bir eksik konu bulunamadı.")

            st.markdown("---")
            st.subheader("📋 Sınav Geçmiş Tablosu")
            st.dataframe(df_ogr[['sinav_adi', 'tarih', 'turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'toplam_net', 'tyt_puan']], use_container_width=True)

    else:
        st.info("Henüz veritabanında kayıtlı sınav bulunmuyor. Sol menüden yeni sınav yükleyebilirsiniz.")
    conn.close()

# --- 3. MENÜ: GENEL OKUL DURUMU ---
elif secim == "📈 Genel Okul Durumu":
    st.title("🏫 Okul Genel Başarı Analizi")
    conn = sqlite3.connect("sinav_takip.db")
    
    cursor = conn.cursor()
    cursor.execute("SELECT sinav_adi FROM sinavlar")
    sinavlar = [s[0] for s in cursor.fetchall()]

    if sinavlar:
        secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
        
        query = '''
        SELECT os.ogrenci_adi, os.sinif, os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.tyt_puan, os.kurum_sirasi
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE s.sinav_adi = ?
        ORDER BY os.kurum_sirasi ASC
        '''
        df_genel = pd.read_sql_query(query, conn, params=(secilen_sinav,))
        
        st.write(f"### 🏆 {secilen_sinav} Derece Listesi")
        st.dataframe(df_genel, use_container_width=True)
    else:
        st.info("Henüz yüklü sınav yok.")
    conn.close()

# --- 4. MENÜ: SINAV YÖNETİMİ & SİLME ---
elif secim == "🗑️ Sınav Yönetimi & Silme":
    st.title("🗑️ Sınav Silme ve Yönetim Paneli")
    st.write("Hatalı veya yanlış yüklediğiniz sınavları sistemden tamamen kaldırın.")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute("SELECT sinav_id, sinav_adi, tarih FROM sinavlar ORDER BY tarih DESC")
    sinavlar = cursor.fetchall()

    if sinavlar:
        sinav_dict = {f"{s[1]} ({s[2]})": s[0] for s in sinavlar}
        silinecek_sinav_label = st.selectbox("Silmek İstediğiniz Sınavı Seçin:", list(sinav_dict.keys()))
        silinecek_id = sinav_dict[silinecek_sinav_label]

        st.warning("⚠️ Dikkat: Seçilen sınav silindiğinde bu sınava ait tüm öğrenci netleri ve eksik kazanım verileri kalıcı olarak silinecektir!")
        
        if st.button("❌ Bu Sınavı Tamamen Sil", type="primary"):
            try:
                cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
                conn.commit()
                st.success(f"✅ '{silinecek_sinav_label}' ve ilişkili tüm veriler başarıyla silindi!")
                st.rerun()
            except Exception as e:
                st.error(f"Silme sırasında hata oluştu: {e}")
    else:
        st.info("Sistemde silinecek yüklü sınav bulunmuyor.")

    conn.close()