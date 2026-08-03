import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re

# ---------------------------------------------------------
# SAYFA VE VERİTABANI AYARLARI
# ---------------------------------------------------------
st.set_page_config(
    page_title="Sınav Analiz Paneli",
    page_icon="📊",
    layout="wide"
)

def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    # Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT
    )
    ''')
    
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
        FOREIGN KEY(sinav_id) REFERENCES sinavlar(sinav_id)
    )
    ''')
    
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
        FOREIGN KEY(sinav_id) REFERENCES sinavlar(sinav_id)
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------
def tr_normalize(text):
    if not text:
        return ""
    text = str(text).strip()
    replacements = {
        'I': 'ı', 'İ': 'i', 'Ç': 'c', 'ç': 'c',
        'Ğ': 'g', 'ğ': 'g', 'Ö': 'o', 'ö': 'o',
        'Ş': 's', 'ş': 's', 'Ü': 'u', 'ü': 'u'
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
    return text.lower()

# Esnek sütun bulma fonksiyonu
def get_val(row, possible_names, default=0.0):
    for name in possible_names:
        for col in row.index:
            if name.upper() in str(col).strip().upper():
                val = row[col]
                if pd.notna(val) and str(val).strip() not in ['', 'nan', 'None']:
                    return val
    return default

# ---------------------------------------------------------
# OTURUM KONTROLÜ (DEMO GİRİŞİ)
# ---------------------------------------------------------
if 'role' not in st.session_state:
    st.session_state['role'] = 'admin'  # Varsayılan admin yetkisi

# ---------------------------------------------------------
# YAN MENÜ (NAVIGATION)
# ---------------------------------------------------------
st.sidebar.title("📌 Menü")
secim = st.sidebar.radio(
    "Görünüm Seçin",
    ["📤 Yeni Sınav Yükle", "📊 Sınav Analizi & Sonuçlar"]
)

# ---------------------------------------------------------
# 1. MENÜ: YENİ SINAV YÜKLE (DÜZELTİLMİŞ KISIM)
# ---------------------------------------------------------
if secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    
    col1, col2 = st.columns(2)
    with col1:
        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: aday")
    with col2:
        sinav_tarihi = st.date_input("Sınav Tarihi")

    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])

    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if sinav_adi and excel_file and pdf_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()

                # Sınavı kaydet
                cursor.execute("INSERT OR IGNORE INTO sinavlar (sinav_adi, tarih) VALUES (?, ?)", (sinav_adi, str(sinav_tarihi)))
                cursor.execute("SELECT sinav_id FROM sinavlar WHERE sinav_adi = ?", (sinav_adi,))
                sinav_id = cursor.fetchone()[0]

                # --- EXCEL ANALİZİ (DİNAMİK BAŞLIK TESPİTİ) ---
                df_raw = pd.read_excel(excel_file)
                
                header_row_idx = None
                # Excel satırlarında 'ÖĞRENCİ' kelimesini arayarak başlık satırını bulur
                for idx, row in df_raw.iterrows():
                    row_str_values = [str(val).strip().upper() for val in row.values if pd.notna(val)]
                    if any("ÖĞRENCİ" in val or "OGRENCI" in val for val in row_str_values):
                        header_row_idx = idx
                        break

                if header_row_idx is not None:
                    headers = [str(c).strip() if pd.notna(c) else '' for c in df_raw.iloc[header_row_idx].values]
                    df = df_raw.iloc[header_row_idx + 1:].copy()
                    df.columns = headers
                else:
                    df = df_raw.copy()

                # Satır satır öğrencileri ekle
                for _, row in df.iterrows():
                    raw_name = get_val(row, ['Öğrenci', 'Ogrenci', 'Adı Soyadı', 'Ad Soyad'], default=None)
                    
                    if not raw_name or str(raw_name).strip().upper() in ['NAN', 'NONE', '', 'ÖĞRENCİ', 'OGRENCI']:
                        continue
                    
                    raw_name = str(raw_name).strip()
                    norm_name = tr_normalize(raw_name)

                    numara = str(get_val(row, ['Numara', 'No'], default=''))
                    grup = str(get_val(row, ['Grup', 'Sınıf', 'Sinif'], default=''))
                    puan = float(get_val(row, ['YKS TYT', 'TYT Puan', 'Puan'], default=0.0))
                    sira = int(float(get_val(row, ['YKS TYT K.B.', 'K.B.', 'Kurum Sıra', 'Sıra'], default=0)))
                    turkce = float(get_val(row, ['Tür 05.N', 'Türkçe Net', 'Tür Net', 'Türkçe'], default=0.0))
                    sosyal = float(get_val(row, ['Sos 05.N', 'Sosyal Net', 'Sos Net', 'Sosyal'], default=0.0))
                    mat = float(get_val(row, ['Tem 05.N', 'Matematik Net', 'Mat Net', 'Matematik'], default=0.0))
                    fen = float(get_val(row, ['Fen 05.N', 'Fen Net', 'Fen'], default=0.0))
                    toplam = float(get_val(row, ['TYT 05.N', 'Toplam Net', 'TYT Net', 'Toplam'], default=0.0))

                    cursor.execute('''
                    INSERT INTO ogrenci_sonuclari 
                    (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, tyt_puan, kurum_sirasi, turkce_net, sosyal_net, matematik_net, fen_net, toplam_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (sinav_id, numara, raw_name, norm_name, grup, puan, sira, turkce, sosyal, mat, fen, toplam))

                # --- PDF ANALİZİ ---
                reader = pypdf.PdfReader(pdf_file)
                pdf_text = ""
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        pdf_text += extracted + "\n"

                blocks = pdf_text.split("ÖGRENCI YANLIS CEVAP LISTESI")
                if len(blocks) <= 1:
                    blocks = pdf_text.split("ÖĞRENCİ YANLIŞ CEVAP LİSTESİ")

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
                st.success(f"🎉 '{sinav_adi}' sınavı ve eksik analizleri başarıyla yüklendi!")

            except Exception as e:
                st.error(f"Hata oluştu: {e}")
        else:
            st.warning("Lütfen tüm alanları doldurun ve dosyaları yükleyin.")

# ---------------------------------------------------------
# 2. MENÜ: SINAV ANALİZİ & SONUÇLAR
# ---------------------------------------------------------
elif secim == "📊 Sınav Analizi & Sonuçlar":
    st.title("📊 Sınav Sonuç ve Analiz Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar", conn)
    
    if not df_sinavlar.empty:
        secilen_sinav = st.selectbox("Sınav Seçin", df_sinavlar["sinav_adi"].tolist())
        sinav_id = df_sinavlar[df_sinavlar["sinav_adi"] == secilen_sinav]["sinav_id"].values[0]

        df_sonuclar = pd.read_sql_query("SELECT * FROM ogrenci_sonuclari WHERE sinav_id = ?", conn, params=(int(sinav_id),))
        
        if not df_sonuclar.empty:
            st.subheader(f"📈 {secilen_sinav} - Genel Başarı Tablosu")
            st.dataframe(
                df_sonuclar[['ogrenci_no', 'ogrenci_adi', 'sinif', 'tyt_puan', 'kurum_sirasi', 'turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'toplam_net']],
                use_container_width=True
            )
        else:
            st.info("Bu sınava ait öğrenci sonucu bulunamadı.")
    else:
        st.info("Henüz yüklenmiş bir sınav bulunmuyor.")
    
    conn.close()