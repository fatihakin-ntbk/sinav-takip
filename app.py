import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import pdfplumber

# ---------------------------------------------------------
# 1. VERİTABANI KURULUMU
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect("okul_takip.db")
    cursor = conn.cursor()
    
    # Öğrenci Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ogrenciler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numara TEXT UNIQUE,
            ad_soyad TEXT,
            sinif TEXT,
            alan TEXT
        )
    """)
    
    # Sınav Sonuçları Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sinav_sonuclari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT,
            sinav_tarihi TEXT,
            numara TEXT,
            ad_soyad TEXT,
            sinif TEXT,
            alan TEXT,
            puan REAL DEFAULT 0,
            derece INTEGER DEFAULT 0,
            matematik REAL DEFAULT 0,
            fizik REAL DEFAULT 0,
            kimya REAL DEFAULT 0,
            biyoloji REAL DEFAULT 0,
            edebiyat REAL DEFAULT 0,
            tarih1 REAL DEFAULT 0,
            cografya1 REAL DEFAULT 0,
            turkce REAL DEFAULT 0,
            sosyal REAL DEFAULT 0
        )
    """)
    
    # Yanlış Cevaplar Tablosu (PDF Analizi İçin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS yanlis_cevaplar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT,
            numara TEXT,
            ders_adi TEXT,
            soru_no TEXT,
            ogrenci_cevabi TEXT,
            dogru_cevap TEXT,
            konu_adi TEXT
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# 2. ESNEK EXCEL OKUMA VE ANALİZ FONKSİYONU
# ---------------------------------------------------------
def guvenli_get(row, col_name, default=0):
    """Sütun bulunamazsa hata vermek yerine varsayılan değeri döndürür."""
    if col_name in row.index:
        val = row[col_name]
        if pd.notna(val):
            return val
    return default

def excel_veri_isle(uploaded_excel, sinav_adi, sinav_tarihi):
    try:
        # Excel başlığı genelde 7 veya 8. satırda başlar (Header=7)
        df = pd.read_excel(uploaded_excel, header=7)
        
        if 'Öğrenci' not in df.columns:
            # Yedek deneme: başlık 0. satırda mı?
            df = pd.read_excel(uploaded_excel, header=0)
            
        df = df.dropna(subset=['Öğrenci'])
        
        conn = sqlite3.connect("okul_takip.db")
        cursor = conn.cursor()
        
        kayit_sayisi = 0
        for _, row in df.iterrows():
            ogrenci_adi = str(guvenli_get(row, 'Öğrenci', '')).strip()
            numara = str(guvenli_get(row, 'Numara', '')).strip()
            sinif = str(guvenli_get(row, 'Grup', '')).strip()
            
            if not ogrenci_adi or ogrenci_adi == 'nan':
                continue
                
            raw_alan = str(guvenli_get(row, 'Alan', '')).upper()
            if 'SAY' in raw_alan:
                alan = 'SAY'
            elif 'EA' in raw_alan:
                alan = 'EA'
            elif 'TYT' in raw_alan:
                alan = 'TYT'
            else:
                alan = 'SAY'
                
            # Esnek Puan ve Derece Çekimi (Sütun yoksa hata vermez, 0 alır)
            puan_ea = pd.to_numeric(guvenli_get(row, 'YKS-EA', 0), errors='coerce')
            puan_say = pd.to_numeric(guvenli_get(row, 'YKS-SAY', 0), errors='coerce')
            puan_tyt = pd.to_numeric(guvenli_get(row, 'YKS TYT', 0), errors='coerce')
            
            derece_ea = pd.to_numeric(guvenli_get(row, 'YKS-EA K.B.', 0), errors='coerce')
            derece_say = pd.to_numeric(guvenli_get(row, 'YKS-SAY K.B.', 0), errors='coerce')
            derece_tyt = pd.to_numeric(guvenli_get(row, 'YKS TYT K.B.', 0), errors='coerce')
            
            if alan == 'EA':
                puan = puan_ea if pd.notna(puan_ea) and puan_ea > 0 else 0
                derece = derece_ea if pd.notna(derece_ea) else 0
            elif alan == 'SAY':
                puan = puan_say if pd.notna(puan_say) and puan_say > 0 else 0
                derece = derece_say if pd.notna(derece_say) else 0
            else:
                puan = puan_tyt if pd.notna(puan_tyt) and puan_tyt > 0 else 0
                derece = derece_tyt if pd.notna(derece_tyt) else 0
                
            # Netler
            mat = float(guvenli_get(row, 'Mat 05.N', 0))
            fiz = float(guvenli_get(row, 'Fiz 05.N', 0))
            kim = float(guvenli_get(row, 'Kim 05.N', 0))
            biy = float(guvenli_get(row, 'Biy 05.N', 0))
            edeb = float(guvenli_get(row, 'Tür 05.N (1)', 0))
            tar1 = float(guvenli_get(row, 'Tar 05.N', 0))
            cog1 = float(guvenli_get(row, 'Coğ 05.N', 0))
            turkce = float(guvenli_get(row, 'Tür 05.N', 0))
            sosyal = float(guvenli_get(row, 'Sos 05.N', 0))
            
            # Öğrenci Kaydet
            cursor.execute("""
                INSERT INTO ogrenciler (numara, ad_soyad, sinif, alan)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(numara) DO UPDATE SET
                ad_soyad=excluded.ad_soyad, sinif=excluded.sinif, alan=excluded.alan
            """, (numara, ogrenci_adi, sinif, alan))
            
            # Sonuç Kaydet
            cursor.execute("""
                INSERT INTO sinav_sonuclari 
                (sinav_adi, sinav_tarihi, numara, ad_soyad, sinif, alan, puan, derece, matematik, fizik, kimya, biyoloji, edebiyat, tarih1, cografya1, turkce, sosyal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sinav_adi, sinav_tarihi, numara, ogrenci_adi, sinif, alan,
                round(float(puan), 3), int(derece) if pd.notna(derece) else 0,
                mat, fiz, kim, biy, edeb, tar1, cog1, turkce, sosyal
            ))
            kayit_sayisi += 1
            
        conn.commit()
        conn.close()
        return True, f"{kayit_sayisi} öğrenci sonucu başarıyla yüklendi."
    except Exception as e:
        return False, f"Excel İşleme Hatası: {e}"

def pdf_veri_isle(uploaded_pdf, sinav_adi):
    """Yanlış Cevap Listesi PDF'sini okur ve veritabanına işler."""
    try:
        conn = sqlite3.connect("okul_takip.db")
        cursor = conn.cursor()
        
        with pdfplumber.open(uploaded_pdf) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                lines = text.split('\n')
                for line in lines:
                    # Örnek PDF satır analizi: Numara, Ders, Soru No vb.
                    parts = line.split()
                    if len(parts) >= 4 and parts[0].isdigit():
                        numara = parts[0]
                        ders = parts[1]
                        soru_no = parts[2]
                        ogrenci_cevap = parts[3]
                        
                        cursor.execute("""
                            INSERT INTO yanlis_cevaplar (sinav_adi, numara, ders_adi, soru_no, ogrenci_cevabi)
                            VALUES (?, ?, ?, ?, ?)
                        """, (sinav_adi, numara, ders, soru_no, ogrenci_cevap))
                        
        conn.commit()
        conn.close()
        return True, "PDF Analizi Tamamlandı."
    except Exception as e:
        return False, f"PDF İşleme Notu: {e}"

# ---------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ---------------------------------------------------------
st.set_page_config(page_title="Sınav Takip & Analiz Portalı", layout="wide", page_icon="📈")

st.sidebar.title("📌 Menü")
secim = st.sidebar.radio("Sayfa Seçiniz:", ["📥 Yeni Deneme Sınavı Yükle", "👨‍🎓 Öğrenci Karnesi & Analiz"])

# --- YENİ DENEME SINAVI YÜKLEME PANELİ ---
if secim == "📥 Yeni Deneme Sınavı Yükle":
    st.title("📥 Yeni Deneme Sınavı Yükleme Paneli")
    
    col_a, col_b = st.columns(2)
    with col_a:
        sinav_adi = st.text_input("Sınav Adı", "345 büyük prova ayt")
    with col_b:
        sinav_tarihi = st.date_input("Sınav Tarihi")
        
    uploaded_excel = st.file_uploader("Toplu Sonuç Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx", "xls"])
    uploaded_pdf = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])
    
    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if uploaded_excel is not None:
            with st.spinner("Excel dosyası okunuyor ve alanlar ayrıştırılıyor..."):
                durum, mesaj = excel_veri_isle(uploaded_excel, sinav_adi, str(sinav_tarihi))
                if durum:
                    st.success(mesaj)
                    if uploaded_pdf is not None:
                        pdf_durum, pdf_mesaj = pdf_veri_isle(uploaded_pdf, sinav_adi)
                        st.info(pdf_mesaj)
                else:
                    st.error(mesaj)
        else:
            st.warning("Lütfen en az bir Excel dosyası seçin!")

# --- ÖĞRENCİ KARNESİ ---
else:
    st.title("👨‍🎓 Öğrenci Karne ve Sınav Analiz Paneli")
    
    conn = sqlite3.connect("okul_takip.db")
    df_ogrenci = pd.read_sql_query("SELECT numara, ad_soyad, alan FROM ogrenciler", conn)
    
    if not df_ogrenci.empty:
        liste = (df_ogrenci['numara'] + " - " + df_ogrenci['ad_soyad'] + " (" + df_ogrenci['alan'] + ")").tolist()
        secilen = st.selectbox("Öğrenci Seçin:", liste)
        numara = secilen.split(" - ")[0]
        
        df_sonuc = pd.read_sql_query("SELECT * FROM sinav_sonuclari WHERE numara = ?", conn, params=(numara,))
        df_yanlis = pd.read_sql_query("SELECT * FROM yanlis_cevaplar WHERE numara = ?", conn, params=(numara,))
        conn.close()
        
        if not df_sonuc.empty:
            ogrenci_alan = df_sonuc['alan'].iloc[-1]
            st.subheader(f"📊 Sınav Geçmişi (Alan: {ogrenci_alan})")
            
            st.dataframe(df_sonuc[['sinav_adi', 'sinav_tarihi', 'puan', 'derece', 'matematik', 'fizik', 'kimya', 'biyoloji', 'edebiyat']], use_container_width=True)
            
            if not df_yanlis.empty:
                st.subheader("❌ Yanlış Cevap & Konu Analizi")
                st.dataframe(df_yanlis[['sinav_adi', 'ders_adi', 'soru_no', 'ogrenci_cevabi']], use_container_width=True)
        else:
            st.info("Bu öğrenciye ait kayıtlı sonuç bulunamadı.")
    else:
        st.warning("Henüz sisteme kayıtlı öğrenci yok.")