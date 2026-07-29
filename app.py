import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re
import os
import base64
import matplotlib.pyplot as plt
import io

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

# --- VERİTABANI OLUŞTURMA & GÜNCELLEME ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    # Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT
    )''')

    # Öğrenci Sonuçları Tablosu
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

    # Öğrenci Eksikleri Tablosu
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

    # Kurum Bilgileri ve Logo Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        kurum_adi TEXT,
        logo_base64 TEXT
    )''')

    conn.commit()
    conn.close()

init_db()

# --- KURUM BİLGİLERİNİ GETİRME ---
def get_kurum_bilgileri():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kurum_adi, logo_base64 FROM kurum_ayarlari WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return "NAZİF TOKGÖZ BAŞARI KOLEJİ", None

# --- DİNAMİK / AKILLI EKSİK KONU SORGUSU ---
def get_ogrenci_eksik_durumu(conn, ogrenci_norm_adi):
    cursor = conn.cursor()
    
    # 1. Öğrencinin girdiği EN SON sınavın ID'sini bul
    cursor.execute('''
        SELECT s.sinav_id 
        FROM sinavlar s
        JOIN ogrenci_sonuclari os ON s.sinav_id = os.sinav_id
        WHERE os.ogrenci_adi_norm = ?
        ORDER BY s.tarih DESC, s.sinav_id DESC LIMIT 1
    ''', (ogrenci_norm_adi,))
    
    last_exam = cursor.fetchone()
    if not last_exam:
        return [], []
    
    last_sinav_id = last_exam[0]
    
    # 2. EN SON sınavında da hâlâ yanlış yaptığı konular (Aktif Eksikler)
    cursor.execute('''
        SELECT konu_kazanim, COUNT(*) as toplam_tekrar
        FROM ogrenci_eksikleri
        WHERE ogrenci_adi_norm = ? 
          AND konu_kazanim IN (
              SELECT konu_kazanim 
              FROM ogrenci_eksikleri 
              WHERE ogrenci_adi_norm = ? AND sinav_id = ?
          )
        GROUP BY konu_kazanim
        ORDER BY toplam_tekrar DESC
    ''', (ogrenci_norm_adi, ogrenci_norm_adi, last_sinav_id))
    
    aktif_eksikler = cursor.fetchall()
    
    # 3. Geçmişte yanlış yapıp SON SINAVDA DOĞRU YAPAN (Düzeltilen) konular
    cursor.execute('''
        SELECT DISTINCT konu_kazanim
        FROM ogrenci_eksikleri
        WHERE ogrenci_adi_norm = ? 
          AND konu_kazanim NOT IN (
              SELECT konu_kazanim 
              FROM ogrenci_eksikleri 
              WHERE ogrenci_adi_norm = ? AND sinav_id = ?
          )
    ''', (ogrenci_norm_adi, ogrenci_norm_adi, last_sinav_id))
    
    tamamlanan_konular = [row[0] for row in cursor.fetchall()]
    
    return aktif_eksikler, tamamlanan_konular

# --- ÖĞRENCİ HTML KARNE ÜRETİCİ (TAM GENİŞLİKLİ YATAY DÜZEN) ---
def generate_student_html_report(df_ogr, aktif_eksikler, tamamlanan_konular, student_name, fig_img_base64, veli_notu=""):
    last_row = df_ogr.iloc[-1]
    kurum_adi, logo_base64 = get_kurum_bilgileri()
    
    # Logo HTML
    if logo_base64:
        logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="max-height: 75px; max-width: 220px; object-fit: contain;">'
    else:
        logo_html = f'<div style="font-size:22px; font-weight:bold; color:#1a365d;">🏛️ {kurum_adi}</div>'

    # Veli Notu HTML
    not_html = ""
    if veli_notu.strip():
        not_html = f"""
        <div style="margin-top: 15px; background: #f7fafc; border: 1px solid #cbd5e0; border-left: 5px solid #3182ce; border-radius: 8px; padding: 12px;">
            <div style="font-size: 13px; font-weight: bold; color: #2b6cb0; margin-bottom: 4px;">✍️ REHBERLİK & ÖĞRETMEN DEĞERLENDİRME NOTU:</div>
            <div style="font-size: 12px; color: #2d3748; line-height: 1.4; white-space: pre-wrap;">{veli_notu}</div>
        </div>
        """

    # Sınav Geçmiş Tablosu Rows
    table_rows = ""
    for _, r in df_ogr.iterrows():
        table_rows += f"""
        <tr>
            <td>{r['sinav_adi']}</td>
            <td>{r['tarih']}</td>
            <td>{r['turkce_net']:.2f}</td>
            <td>{r['sosyal_net']:.2f}</td>
            <td>{r['matematik_net']:.2f}</td>
            <td>{r['fen_net']:.2f}</td>
            <td style="font-weight:bold; color:#1a365d;">{r['toplam_net']:.2f}</td>
            <td style="font-weight:bold; color:#2b6cb0;">{r['tyt_puan']:.2f}</td>
            <td>{int(r['kurum_sirasi'])}</td>
        </tr>
        """
        
    # Aktif Eksikler HTML (Sol Sütun)
    eksik_rows = ""
    if aktif_eksikler:
        for konu, tekrar in aktif_eksikler:
            badge_color = "#e53e3e" if tekrar > 1 else "#dd6b20"
            badge_text = f"{tekrar} Sınavdır Yanlış"
            eksik_rows += f"""
            <div style="background:#fff5f5; border-left:4px solid {badge_color}; padding:8px 10px; margin-bottom:6px; border-radius:4px; display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:600; color:#2d3748; font-size:12px;">📌 {konu}</span>
                <span style="background:{badge_color}; color:white; font-size:10px; padding:2px 6px; border-radius:10px; font-weight:bold;">{badge_text}</span>
            </div>
            """
    else:
        eksik_rows = "<p style='color:#38a169; font-weight:bold; font-size:12px; margin:0;'>🎉 En son sınavda tespit edilen aktif eksik konu bulunmuyor!</p>"

    # Tamamlanan/Düzeltilen Konular HTML (Sağ Sütun)
    tamamlanan_rows = ""
    if tamamlanan_konular:
        for konu in tamamlanan_konular:
            tamamlanan_rows += f"""
            <div style="background:#f0fff4; border-left:4px solid #38a169; padding:8px 10px; margin-bottom:6px; border-radius:4px; font-size:12px; color:#276749; font-weight:600;">
                ✅ {konu} <span style="font-size:10px; font-weight:normal; color:#48bb78;">(Son sınavda düzeltildi)</span>
            </div>
            """
    else:
        tamamlanan_rows = "<p style='color:#718096; font-size:12px; margin:0;'>Henüz önceden eksik olup sonradan kazanılan konu kaydı bulunmuyor.</p>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>{student_name} - Öğrenci Analiz Karnesi</title>
        <style>
            @page {{ size: A4; margin: 8mm; }}
            * {{ box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f7fafc; color: #2d3748; margin: 0; padding: 10px; }}
            .card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; width: 100%; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #3182ce; padding-bottom: 12px; margin-bottom: 15px; }}
            .header-info h1 {{ margin: 0; color: #1a365d; font-size: 20px; }}
            .header-info p {{ margin: 2px 0 0 0; color: #718096; font-size: 12px; }}
            
            .metrics {{ display: flex; gap: 10px; margin-bottom: 15px; }}
            .metric-box {{ flex: 1; background: #ebf8ff; border: 1px solid #bee3f8; border-radius: 6px; padding: 8px; text-align: center; }}
            .metric-title {{ font-size: 10px; color: #2b6cb0; font-weight: bold; text-transform: uppercase; }}
            .metric-value {{ font-size: 16px; font-weight: bold; color: #2c5282; margin-top: 2px; }}
            
            .section-title {{ font-size: 13px; font-weight: bold; color: #2d3748; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
            
            /* ÜST BÖLÜM: YATAY TAM GENİŞLİKLİ GRAFİK */
            .chart-full-width {{ width: 100%; margin-bottom: 15px; background: #fafafa; border: 1px solid #edf2f7; border-radius: 8px; padding: 10px; text-align: center; }}
            .chart-full-width img {{ width: 100%; max-height: 230px; object-fit: contain; }}
            
            /* ALT BÖLÜM: YAN YANA İKİ SÜTUN */
            .two-column-grid {{ display: flex; gap: 15px; margin-bottom: 15px; }}
            .col-half {{ flex: 1; background: #fafafa; border: 1px solid #edf2f7; border-radius: 8px; padding: 12px; }}
            
            table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; }}
            th {{ background-color: #2b6cb0; color: white; padding: 6px; text-align: left; }}
            td {{ padding: 6px; border-bottom: 1px solid #e2e8f0; }}
            tr:nth-child(even) {{ background-color: #f7fafc; }}
            
            @media print {{
                body {{ background: white; padding: 0; }}
                .card {{ box-shadow: none; border: none; padding: 0; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print" style="text-align:right; margin-bottom:10px;">
            <button onclick="window.print()" style="background:#3182ce; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:bold;">🖨️ Yazdır / PDF Olarak Kaydet</button>
        </div>

        <div class="card">
            <!-- HEADER -->
            <div class="header">
                <div>
                    {logo_html}
                </div>
                <div class="header-info" style="text-align:right;">
                    <h1>🎓 {student_name.upper()}</h1>
                    <p>Bireysel TYT Deneme Sınavı Gelişim & Analiz Karnesi</p>
                    <span style="background:#e2e8f0; padding:2px 8px; border-radius:12px; font-weight:bold; color:#4a5568; font-size:11px;">Sınıf: {last_row['sinif']}</span>
                </div>
            </div>

            <!-- METRİKLER -->
            <div class="metrics">
                <div class="metric-box">
                    <div class="metric-title">Son TYT Puanı</div>
                    <div class="metric-value">{last_row['tyt_puan']:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-title">Son Kurum Sırası</div>
                    <div class="metric-value">{int(last_row['kurum_sirasi'])}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-title">Son Toplam Net</div>
                    <div class="metric-value">{last_row['toplam_net']:.2f}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-title">Girdiği Sınav Sayısı</div>
                    <div class="metric-value">{len(df_ogr)}</div>
                </div>
            </div>

            <!-- ÜST BÖLÜM: ENLEMELİNE TAM KAPLAYAN GRAFİK -->
            <div class="chart-full-width">
                <div class="section-title" style="text-align:left;">📈 Sınav Performans & Net Gelişim Grafiği</div>
                <img src="data:image/png;base64,{fig_img_base64}">
            </div>

            <!-- ALT BÖLÜM: YAN YANA İKİ SÜTUN HAKKİNDA -->
            <div class="two-column-grid">
                <!-- Sol Sütun: Aktif Eksikler -->
                <div class="col-half" style="border-top: 3px solid #e53e3e;">
                    <div class="section-title" style="color: #c53030;">⚠️ Aktif Müdahale Gereken Konular</div>
                    <div style="font-size: 10px; color: #718096; margin-bottom: 8px;">(Son sınavda da hâlâ yanlış yapılanlar)</div>
                    {eksik_rows}
                </div>

                <!-- Sağ Sütun: Tamamlanan/Kazanılan Konular -->
                <div class="col-half" style="border-top: 3px solid #38a169;">
                    <div class="section-title" style="color: #276749;">🎉 Başarıyla Halledilen Konular</div>
                    <div style="font-size: 10px; color: #718096; margin-bottom: 8px;">(Önceki sınavlarda yanlış yapılıp son sınavda çözülenler)</div>
                    {tamamlanan_rows}
                </div>
            </div>

            <!-- REHBERLİK NOTU -->
            {not_html}

            <!-- SINAV GEÇMİŞ TABLOSU -->
            <div style="margin-top:12px;">
                <div class="section-title">📋 Sınav Katılım & Geçmiş Tablosu</div>
                <table>
                    <thead>
                        <tr>
                            <th>Sınav Adı</th>
                            <th>Tarih</th>
                            <th>Türkçe</th>
                            <th>Sosyal</th>
                            <th>Matematik</th>
                            <th>Fen</th>
                            <th>Toplam Net</th>
                            <th>TYT Puanı</th>
                            <th>Sıra</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content

# --- YAN MENÜ ---
st.sidebar.title("📌 Menü")
secim = st.sidebar.radio(
    "İşlem Seçiniz:", 
    [
        "📤 Yeni Sınav Yükle", 
        "📊 Öğrenci Karneleri & Analiz", 
        "🏫 Okul Genel Durumu & Dereceler", 
        "🔥 Okul Konu/Kazanım Analizi", 
        "⚙️ Kurum Ayarları & Logo",
        "🗑️ Sınav Yönetimi & Silme"
    ]
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

    excel_file = st.file_uploader("Toplu Sonuç Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
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

    cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
    siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
    secilen_sinif = st.selectbox("Sınıf Seçin (Filtreleme):", siniflar)

    if secilen_sinif == "Tüm Sınıflar":
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
    else:
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari WHERE sinif = ? ORDER BY ogrenci_adi ASC", (secilen_sinif,))
    
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
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Son TYT Puanı", f"{last_row['tyt_puan']:.2f}")
            col2.metric("Kurum Sırası", f"{int(last_row['kurum_sirasi'])}")
            col3.metric("Son Toplam Net", f"{last_row['toplam_net']:.2f}")
            col4.metric("Sınıfı", f"{last_row['sinif']}")

            st.markdown("---")

            grafik_turu = st.radio("Grafik Türü Seçiniz:", ["Toplam Net Gelişimi", "Ders Bazlı Net Dağılımı"], horizontal=True)

            # --- YATAY GENİŞ GRAFİK ÜRETİMİ (12x4.5 inç) ---
            fig, ax = plt.subplots(figsize=(12, 4.5))
            if grafik_turu == "Toplam Net Gelişimi":
                ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#2b5797', linewidth=2.5, label="Toplam Net")
                for i, txt in enumerate(df_ogr['toplam_net']):
                    ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+2), ha='center', fontweight='bold')
                ax.set_ylim(0, 120)
            else:
                ax.plot(df_ogr['sinav_adi'], df_ogr['turkce_net'], marker='s', color='#e74c3c', label="Türkçe")
                ax.plot(df_ogr['sinav_adi'], df_ogr['matematik_net'], marker='^', color='#27ae60', label="Matematik")
                ax.plot(df_ogr['sinav_adi'], df_ogr['fen_net'], marker='o', color='#f39c12', label="Fen")
                ax.plot(df_ogr['sinav_adi'], df_ogr['sosyal_net'], marker='d', color='#8e44ad', label="Sosyal")
                ax.legend(loc="upper left")
                ax.set_ylim(0, 42)

            ax.set_ylabel("Net")
            ax.grid(True, linestyle='--', alpha=0.5)
            plt.xticks(rotation=10)

            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            buf.seek(0)
            fig_img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

            # EKRAN GÖRÜNÜMÜ
            st.subheader("📈 Net Gelişim Grafiği")
            st.pyplot(fig)

            # Akıllı/Dinamik Eksik Hesabı
            aktif_eksikler, tamamlanan_konular = get_ogrenci_eksik_durumu(conn, secilen_norm)

            c1, c2 = st.columns(2)
            with c1:
                st.subheader("⚠️ Acil Müdahale Gereken Konular")
                st.caption("(Son sınavda da hâlâ yanlış yapılan konular)")
                if aktif_eksikler:
                    for konu, tekrar in aktif_eksikler:
                        st.error(f"📌 **{konu}** ({tekrar} Sınavda Yanlış Yapıldı)")
                else:
                    st.success("🎉 En son sınavda tespit edilen aktif eksik konu bulunmuyor!")

            with c2:
                st.subheader("🎉 Başarıyla Halledilen Konular")
                st.caption("(Önceki sınavlarda yanlış yapılıp son sınavda düzeltilenler)")
                if tamamlanan_konular:
                    for konu in tamamlanan_konular:
                        st.success(f"✅ **{konu}** (Son sınavda başarıyla çözüldü)")
                else:
                    st.info("Henüz kazanılan konu kaydı bulunmuyor.")

            st.markdown("---")
            
            # --- ÖĞRETMEN / REHBERLİK NOTU VE İNDİRME ---
            st.subheader("🖨️ Karne Raporu İndirme")
            
            veli_notu = st.text_area(
                "✍️ Rehberlik / Öğretmen Veli Değerlendirme Notu (İsteğe Bağlı):", 
                placeholder="Örn: Öğrencimiz matematik netlerinde düzenli bir artış gösteriyor. Problem çözme ve paragraf çalışmalarına ağırlık verilmesi önerilmektedir...",
                height=80
            )

            html_report = generate_student_html_report(df_ogr, aktif_eksikler, tamamlanan_konular, secilen_ogr_adi, fig_img_base64, veli_notu)
            
            st.download_button(
                label=f"📄 {secilen_ogr_adi} Özel Karne Raporunu İndir (PDF/HTML)",
                data=html_report,
                file_name=f"{secilen_norm}_Gelisim_Karnesi.html",
                mime="text/html",
                type="primary",
                use_container_width=True
            )

            st.markdown("---")
            st.subheader("📋 Sınav Geçmiş Tablosu")
            st.dataframe(df_ogr[['sinav_adi', 'tarih', 'turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'toplam_net', 'tyt_puan']], use_container_width=True)

    else:
        st.info("Seçilen sınıfta öğrenci bulunamadı.")
    conn.close()

# --- 3. MENÜ: GENEL OKUL DURUMU ---
elif secim == "🏫 Okul Genel Durumu & Dereceler":
    st.title("🏫 Okul Genel Başarı Analizi ve Derece Listeleri")
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT sinav_adi FROM sinavlar")
    sinavlar = [s[0] for s in cursor.fetchall()]

    if sinavlar:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
        with col_s2:
            cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
            siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
            secilen_sinif = st.selectbox("Sınıf Filtresi:", siniflar)
        
        if secilen_sinif == "Tüm Sınıflar":
            query = '''
            SELECT os.kurum_sirasi as 'Sıra', os.ogrenci_no as 'No', os.ogrenci_adi as 'Öğrenci Adı', os.sinif as 'Sınıf',
                   os.turkce_net as 'Türkçe', os.sosyal_net as 'Sosyal', os.matematik_net as 'Matematik', os.fen_net as 'Fen',
                   os.toplam_net as 'Toplam Net', os.tyt_puan as 'TYT Puanı'
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ?
            ORDER BY os.kurum_sirasi ASC
            '''
            df_genel = pd.read_sql_query(query, conn, params=(secilen_sinav,))
        else:
            query = '''
            SELECT os.kurum_sirasi as 'Sıra', os.ogrenci_no as 'No', os.ogrenci_adi as 'Öğrenci Adı', os.sinif as 'Sınıf',
                   os.turkce_net as 'Türkçe', os.sosyal_net as 'Sosyal', os.matematik_net as 'Matematik', os.fen_net as 'Fen',
                   os.toplam_net as 'Toplam Net', os.tyt_puan as 'TYT Puanı'
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ? AND os.sinif = ?
            ORDER BY os.kurum_sirasi ASC
            '''
            df_genel = pd.read_sql_query(query, conn, params=(secilen_sinav, secilen_sinif))

        st.write(f"### 🏆 {secilen_sinav} Derece Listesi ({secilen_sinif})")
        st.dataframe(df_genel, use_container_width=True)

        excel_data = df_genel.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 Derece Listesini Excel/CSV Olarak İndir",
            data=excel_data,
            file_name=f"{secilen_sinav}_{secilen_sinif}_Derece_Listesi.csv",
            mime="text/csv"
        )
    else:
        st.info("Henüz veritabanında sınav bulunmuyor.")
    conn.close()

# --- 4. MENÜ: OKUL KONU ANALİZİ ---
elif secim == "🔥 Okul Konu/Kazanım Analizi":
    st.title("🔥 Okul & Sınıf Geneli En Çok Yanlış Yapılan Konular")
    st.write("Okul genelinde öğrencilerin en çok zorlandığı ilk 10 konuyu tespit ederek toplu etütler planlayabilirsiniz.")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT sinav_adi FROM sinavlar")
    sinavlar = ["Tüm Sınavlar"] + [s[0] for s in cursor.fetchall()]

    col1, col2 = st.columns(2)
    with col1:
        secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
    with col2:
        cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
        siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
        secilen_sinif = st.selectbox("Sınıf Seçiniz:", siniflar)

    if secilen_sinav == "Tüm Sınavlar" and secilen_sinif == "Tüm Sınıflar":
        query = '''
        SELECT konu_kazanim as 'Konu / Kazanım', COUNT(*) as 'Yanlış/Boş Sayısı'
        FROM ogrenci_eksikleri
        GROUP BY konu_kazanim
        ORDER BY COUNT(*) DESC LIMIT 10
        '''
        df_konu = pd.read_sql_query(query, conn)
    elif secilen_sinav != "Tüm Sınavlar" and secilen_sinif == "Tüm Sınıflar":
        query = '''
        SELECT oe.konu_kazanim as 'Konu / Kazanım', COUNT(*) as 'Yanlış/Boş Sayısı'
        FROM ogrenci_eksikleri oe
        JOIN sinavlar s ON oe.sinav_id = s.sinav_id
        WHERE s.sinav_adi = ?
        GROUP BY oe.konu_kazanim
        ORDER BY COUNT(*) DESC LIMIT 10
        '''
        df_konu = pd.read_sql_query(query, conn, params=(secilen_sinav,))
    else:
        query = '''
        SELECT oe.konu_kazanim as 'Konu / Kazanım', COUNT(*) as 'Yanlış/Boş Sayısı'
        FROM ogrenci_eksikleri oe
        JOIN sinavlar s ON oe.sinav_id = s.sinav_id
        JOIN ogrenci_sonuclari os ON (os.sinav_id = oe.sinav_id AND os.ogrenci_adi_norm = oe.ogrenci_adi_norm)
        WHERE (s.sinav_adi = ? OR ? = 'Tüm Sınavlar') AND os.sinif = ?
        GROUP BY oe.konu_kazanim
        ORDER BY COUNT(*) DESC LIMIT 10
        '''
        df_konu = pd.read_sql_query(query, conn, params=(secilen_sinav, secilen_sinav, secilen_sinif))

    if not df_konu.empty:
        c1, c2 = st.columns([1.2, 0.8])
        with c1:
            st.subheader("📊 En Çok Yanlış Yapılan İlk 10 Konu (Grafik)")
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.barh(df_konu['Konu / Kazanım'], df_konu['Yanlış/Boş Sayısı'], color='#e74c3c')
            ax.invert_yaxis()
            ax.set_xlabel("Yanlış/Boş Yapan Öğrenci Sayısı")
            ax.grid(True, linestyle='--', alpha=0.5)
            st.pyplot(fig)

        with c2:
            st.subheader("📋 Detaylı Konu Listesi")
            st.dataframe(df_konu, use_container_width=True)
    else:
        st.info("Seçilen kriterlere uygun veri bulunamadı.")

    conn.close()

# --- 5. MENÜ: KURUM AYARLARI VE LOGO ---
elif secim == "⚙️ Kurum Ayarları & Logo":
    st.title("⚙️ Kurum ve Logo Ayarları")
    st.write("Buradan yükleyeceğiniz kurum logosu ve kurum adı, basılan **tüm öğrenci karnelerinde** kalıcı olarak otomatik kullanılır.")

    mevcut_adi, mevcut_logo = get_kurum_bilgileri()

    col1, col2 = st.columns([1, 1])

    with col1:
        yeni_kurum_adi = st.text_input("Kurum Adı:", value=mevcut_adi)
        uploaded_logo = st.file_uploader("Okul/Kurum Logosu Yükleyin (PNG veya JPG):", type=["png", "jpg", "jpeg"])

        if st.button("💾 Kurum Bilgilerini ve Logoyu Kaydet", type="primary"):
            conn = sqlite3.connect("sinav_takip.db")
            cursor = conn.cursor()

            if uploaded_logo is not None:
                logo_bytes = uploaded_logo.read()
                logo_b64 = base64.b64encode(logo_bytes).decode('utf-8')
            else:
                logo_b64 = mevcut_logo

            cursor.execute('''
            INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) 
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET kurum_adi=excluded.kurum_adi, logo_base64=excluded.logo_base64
            ''', (yeni_kurum_adi, logo_b64))

            conn.commit()
            conn.close()
            st.success("✅ Kurum logosu ve bilgileri başarıyla veritabanına kaydedildi!")
            st.rerun()

    with col2:
        st.subheader("🖼️ Şu Anki Kayıtlı Logo / Başlık")
        if mevcut_logo:
            st.image(base64.b64decode(mevcut_logo), width=250, caption="Sistemde Kayıtlı Olan Resmi Logo")
        else:
            st.warning("Henüz özel bir logo yüklenmedi. Varsayılan metin başlığı kullanılıyor.")

# --- 6. MENÜ: SINAV SİLME ---
elif secim == "🗑️ Sınav Yönetimi & Silme":
    st.title("🗑️ Sınav Yönetim ve Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT sinav_id, sinav_adi, tarih FROM sinavlar ORDER BY tarih DESC")
    sinavlar = cursor.fetchall()

    if sinavlar:
        st.subheader("📋 Kayıtlı Sınavlar")
        sinav_dict = {f"{s[1]} ({s[2]})": s[0] for s in sinavlar}
        
        silinecek_sinav_label = st.selectbox("Silmek İstediğiniz Sınavı Seçin:", list(sinav_dict.keys()))
        silinecek_id = sinav_dict[silinecek_sinav_label]

        if st.button("🔴 Seçilen Sınavı Sil", type="primary"):
            try:
                cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (silinecek_id,))
                cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (silinecek_id,))
                cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
                
                conn.commit()
                st.success(f"✅ '{silinecek_sinav_label}' başarıyla silindi.")
                st.rerun()
            except Exception as e:
                st.error(f"Silme hatası: {e}")
    else:
        st.info("Kayıtlı sınav yok.")

    conn.close()