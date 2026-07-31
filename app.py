import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px

# ---------------------------------------------------------
# 1. VERİTABANI BAĞLANTISI VE TABLO OLUŞTURMA
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect("okul_takip.db")
    cursor = conn.cursor()
    
    # Öğrenci Bilgileri Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ogrenciler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numara TEXT UNIQUE,
            ad_soyad TEXT,
            sinif TEXT,
            alan TEXT -- 'SAY' veya 'EA'
        )
    """)
    
    # AYT Sınav Sonuçları Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ayt_sonuclari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT,
            numara TEXT,
            ad_soyad TEXT,
            sinif TEXT,
            alan TEXT, -- 'SAY' veya 'EA'
            puan REAL,
            derece INTEGER,
            matematik REAL DEFAULT 0,
            fizik REAL DEFAULT 0,
            kimya REAL DEFAULT 0,
            biyoloji REAL DEFAULT 0,
            edebiyat REAL DEFAULT 0,
            tarih1 REAL DEFAULT 0,
            cografya1 REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# 2. AYT EXCEL PARSER (ÜÇDÖRTBEŞ V.B. FORMATLAR İÇİN)
# ---------------------------------------------------------
def ayt_excel_oku(uploaded_file, secilen_alan):
    """
    ÜçDörtBeş ve Benzeri Karmaşık AYT Excel Listelerini Okur ve Temizler.
    """
    try:
        # 7. satır başlık (header=7) kabul edilerek okunur
        df = pd.read_excel(uploaded_file, header=7)
        
        # Öğrenci ismi boş olan satırları eliyoruz
        if 'Öğrenci' in df.columns:
            df = df.dropna(subset=['Öğrenci'])
        else:
            st.error("Excel dosyasında 'Öğrenci' sütunu bulunamadı. Lütfen formatı kontrol edin.")
            return None
        
        temiz_veri = []
        
        for _, row in df.iterrows():
            ogrenci_adi = str(row.get('Öğrenci', '')).strip()
            numara = str(row.get('Numara', '')).strip()
            sinif = str(row.get('Grup', '')).strip()
            
            # İsim boşsa pas geç
            if not ogrenci_adi or ogrenci_adi == 'nan':
                continue
                
            if secilen_alan == 'SAY':
                puan = pd.to_numeric(row.get('YKS-SAY', 0), errors='coerce')
                derece = pd.to_numeric(row.get('YKS-SAY K.B.', 0), errors='coerce')
                
                mat_net = pd.to_numeric(row.get('Mat 05.N', 0), errors='coerce')
                fiz_net = pd.to_numeric(row.get('Fiz 05.N', 0), errors='coerce')
                kim_net = pd.to_numeric(row.get('Kim 05.N', 0), errors='coerce')
                biy_net = pd.to_numeric(row.get('Biy 05.N', 0), errors='coerce')
                
                temiz_veri.append({
                    'numara': numara,
                    'ad_soyad': ogrenci_adi,
                    'sinif': sinif,
                    'alan': 'SAY',
                    'puan': round(puan, 3) if pd.notna(puan) else 0.0,
                    'derece': int(derece) if pd.notna(derece) else 0,
                    'matematik': round(mat_net, 2) if pd.notna(mat_net) else 0.0,
                    'fizik': round(fiz_net, 2) if pd.notna(fiz_net) else 0.0,
                    'kimya': round(kim_net, 2) if pd.notna(kim_net) else 0.0,
                    'biyoloji': round(biy_net, 2) if pd.notna(biy_net) else 0.0,
                    'edebiyat': 0.0, 'tarih1': 0.0, 'cografya1': 0.0
                })
                
            elif secilen_alan == 'EA':
                puan = pd.to_numeric(row.get('YKS-EA', row.get('YKS-SAY', 0)), errors='coerce')
                derece = pd.to_numeric(row.get('YKS-EA K.B.', row.get('YKS-SAY K.B.', 0)), errors='coerce')
                
                mat_net = pd.to_numeric(row.get('Mat 05.N', 0), errors='coerce')
                edebiyat_net = pd.to_numeric(row.get('Tür 05.N (1)', 0), errors='coerce')
                tarih1_net = pd.to_numeric(row.get('Tar 05.N', 0), errors='coerce')
                cografya1_net = pd.to_numeric(row.get('Coğ 05.N', 0), errors='coerce')
                
                temiz_veri.append({
                    'numara': numara,
                    'ad_soyad': ogrenci_adi,
                    'sinif': sinif,
                    'alan': 'EA',
                    'puan': round(puan, 3) if pd.notna(puan) else 0.0,
                    'derece': int(derece) if pd.notna(derece) else 0,
                    'matematik': round(mat_net, 2) if pd.notna(mat_net) else 0.0,
                    'edebiyat': round(edebiyat_net, 2) if pd.notna(edebiyat_net) else 0.0,
                    'tarih1': round(tarih1_net, 2) if pd.notna(tarih1_net) else 0.0,
                    'cografya1': round(cografya1_net, 2) if pd.notna(cografya1_net) else 0.0,
                    'fizik': 0.0, 'kimya': 0.0, 'biyoloji': 0.0
                })
                
        return pd.DataFrame(temiz_veri)
    except Exception as e:
        st.error(f"Excel okunurken bir hata oluştu: {e}")
        return None

# ---------------------------------------------------------
# 3. STREAMLIT ARAYÜZ MİMARİSİ
# ---------------------------------------------------------
st.set_page_config(page_title="AYT Takip Portalı", layout="wide", page_icon="🎓")

st.sidebar.title("🎓 Navigasyon")
rol = st.sidebar.radio("Giriş Türü Seçin:", ["👨‍🏫 Admin / Öğretmen Paneli", "👨‍🎓 Öğrenci / Veli Paneli"])

# =========================================================
# A. ADMİN / ÖĞRETMEN PANELİ
# =========================================================
if rol == "👨‍🏫 Admin / Öğretmen Paneli":
    st.title("👨‍🏫 Admin Yönetim Paneli")
    
    tab1, tab2 = st.tabs(["📊 AYT Sınavı Yükle", "📈 Genel Başarı Raporları"])
    
    with tab1:
        st.subheader("📤 AYT Excel Sonuç Dosyası Yükle")
        
        col1, col2 = st.columns(2)
        with col1:
            sinav_adi = st.text_input("Sınav Adı", "ÜçDörtBeş AYT Türkiye Geneli (Mart 2026)")
        with col2:
            secilen_alan = st.radio("Yüklenecek Liste Alanı:", ["SAY", "EA"], horizontal=True)
            
        uploaded_file = st.file_uploader("Excel Dosyasını Sürükleyin veya Seçin", type=["xlsx", "xls"])
        
        if uploaded_file and st.button("🚀 Sınav Verilerini Veritabanına Kaydet", type="primary"):
            with st.spinner("Excel işleniyor ve veritabanına kaydediliyor..."):
                df_sonuc = ayt_excel_oku(uploaded_file, secilen_alan)
                
                if df_sonuc is not None and not df_sonuc.empty:
                    conn = sqlite3.connect("okul_takip.db")
                    cursor = conn.cursor()
                    
                    kayit_sayisi = 0
                    for _, r in df_sonuc.iterrows():
                        # Öğrenciyi kaydet/güncelle
                        cursor.execute("""
                            INSERT INTO ogrenciler (numara, ad_soyad, sinif, alan)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(numara) DO UPDATE SET
                            ad_soyad=excluded.ad_soyad, sinif=excluded.sinif, alan=excluded.alan
                        """, (r['numara'], r['ad_soyad'], r['sinif'], r['alan']))
                        
                        # AYT sonucunu kaydet
                        cursor.execute("""
                            INSERT INTO ayt_sonuclari 
                            (sinav_adi, numara, ad_soyad, sinif, alan, puan, derece, matematik, fizik, kimya, biyoloji, edebiyat, tarih1, cografya1)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sinav_adi, r['numara'], r['ad_soyad'], r['sinif'], r['alan'],
                            r['puan'], r['derece'], r['matematik'], r['fizik'], r['kimya'],
                            r['biyoloji'], r['edebiyat'], r['tarih1'], r['cografya1']
                        ))
                        kayit_sayisi += 1
                        
                    conn.commit()
                    conn.close()
                    
                    st.success(f"🎉 Başarılı! **{kayit_sayisi}** öğrencinin **{secilen_alan}** AYT sonucu veritabanına eklendi.")
                    st.dataframe(df_sonuc.head(10), use_container_width=True)

    with tab2:
        st.subheader("📉 Kayıtlı AYT Sınav Listesi")
        conn = sqlite3.connect("okul_takip.db")
        df_all = pd.read_sql_query("SELECT * FROM ayt_sonuclari", conn)
        conn.close()
        
        if not df_all.empty:
            filtre_alan = st.selectbox("Alana Göre Filtrele:", ["Tümü", "SAY", "EA"])
            if filtre_alan != "Tümü":
                df_filtered = df_all[df_all['alan'] == filtre_alan]
            else:
                df_filtered = df_all
                
            st.dataframe(df_filtered, use_container_width=True)
        else:
            st.info("Henüz veritabanında kayıtlı sınav bulunmuyor.")

# =========================================================
# B. ÖĞRENCİ / VELİ PANELİ
# =========================================================
else:
    st.title("👨‍🎓 Öğrenci & Veli Karneyi Görme Paneli")
    
    conn = sqlite3.connect("okul_takip.db")
    ogrenciler_df = pd.read_sql_query("SELECT numara, ad_soyad, alan FROM ogrenciler", conn)
    
    if ogrenciler_df.empty:
        st.warning("Henüz sisteme kayıtlı öğrenci bulunmuyor. Lütfen önce Admin panelinden sınav yükleyin.")
    else:
        # Öğrenci Arama / Seçme Kutusu
        ogrenci_listesi = (ogrenciler_df['numara'] + " - " + ogrenciler_df['ad_soyad'] + " (" + ogrenciler_df['alan'] + ")").tolist()
        secilen_ogrenci_str = st.selectbox("Öğrenci Seçiniz / Okul Numarası Giriniz:", ogrenci_listesi)
        
        numara = secilen_ogrenci_str.split(" - ")[0]
        
        # Seçilen öğrencinin sonuçlarını çek
        df_ogrenci = pd.read_sql_query("SELECT * FROM ayt_sonuclari WHERE numara = ?", conn, params=(numara,))
        conn.close()
        
        if not df_ogrenci.empty:
            ogrenci_alan = df_ogrenci['alan'].iloc[0]
            ogrenci_ad = df_ogrenci['ad_soyad'].iloc[0]
            
            st.markdown(f"### 📋 **{ogrenci_ad}** - AYT Performans Karnesi (`Alan: {ogrenci_alan}`)")
            
            # --- SAYISAL (SAY) ÖĞRENCİSİ GÖSTERİMİ ---
            if ogrenci_alan == 'SAY':
                col1, col2, col3, col4 = st.columns(4)
                son_sınav = df_ogrenci.iloc[-1]
                col1.metric("Son AYT Puanı", f"{son_sınav['puan']} P")
                col2.metric("Okul Derecesi", f"{son_sınav['derece']}. Sıra")
                col3.metric("Matematik Net", f"{son_sınav['matematik']}")
                col4.metric("Fen Toplam Net", f"{round(son_sınav['fizik'] + son_sınav['kimya'] + son_sınav['biyoloji'], 2)}")
                
                st.divider()
                
                # Tablo Görünümü
                st.subheader("📚 Sınav Bazlı Sayısal Net Dağılımı")
                st.dataframe(
                    df_ogrenci[['sinav_adi', 'puan', 'derece', 'matematik', 'fizik', 'kimya', 'biyoloji']],
                    use_container_width=True
                )
                
                # Net Gelişim Grafiği
                fig = px.line(
                    df_ogrenci, x='sinav_adi', y=['matematik', 'fizik', 'kimya', 'biyoloji'],
                    markers=True, title="📈 Ders Bazlı Net Gelişim Grafiği"
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- EŞİT AĞIRLIK (EA) ÖĞRENCİSİ GÖSTERİMİ ---
            elif ogrenci_alan == 'EA':
                col1, col2, col3, col4 = st.columns(4)
                son_sınav = df_ogrenci.iloc[-1]
                col1.metric("Son EA Puanı", f"{son_sınav['puan']} P")
                col2.metric("Okul Derecesi", f"{son_sınav['derece']}. Sıra")
                col3.metric("Matematik Net", f"{son_sınav['matematik']}")
                col4.metric("Edebiyat Net", f"{son_sınav['edebiyat']}")
                
                st.divider()
                
                # Tablo Görünümü
                st.subheader("📚 Sınav Bazlı Eşit Ağırlık Net Dağılımı")
                st.dataframe(
                    df_ogrenci[['sinav_adi', 'puan', 'derece', 'matematik', 'edebiyat', 'tarih1', 'cografya1']],
                    use_container_width=True
                )
                
                # Net Gelişim Grafiği
                fig = px.line(
                    df_ogrenci, x='sinav_adi', y=['matematik', 'edebiyat', 'tarih1', 'cografya1'],
                    markers=True, title="📈 Ders Bazlı Net Gelişim Grafiği"
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Bu öğrenciye ait girilmiş bir AYT sınav sonucu bulunamadı.")