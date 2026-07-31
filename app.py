import streamlit as st
import pandas as pd
import sqlite3
import numpy as np
import matplotlib.pyplot as plt
import base64
import urllib.parse
import re

# --- 1. PAGE CONFIGURATION & STYLING ---
st.set_page_config(
    page_title="Sınav Takip & Analiz Portalı",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 15px;
        border-left: 5px solid #3182ce;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .stButton>button {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. DATABASE INITIALIZATION ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    # Kullanıcılar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE NOT NULL,
        sifre TEXT NOT NULL,
        rol TEXT NOT NULL,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )''')
    
    # Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT NOT NULL,
        tarih DATE,
        yayin_evi TEXT,
        sinav_turu TEXT
    )''')
    
    # Öğrenci Sonuçları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        kurum_sirasi INTEGER,
        genel_sira INTEGER,
        turkce_d REAL, turkce_y REAL, turkce_net REAL,
        sosyal_d REAL, sosyal_y REAL, sosyal_net REAL,
        matematik_d REAL, matematik_y REAL, matematik_net REAL,
        fen_d REAL, fen_y REAL, fen_net REAL,
        toplam_net REAL,
        tyt_puan REAL,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id) ON DELETE CASCADE
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
        FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id) ON DELETE CASCADE
    )''')
    
    # Ödevler Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinif TEXT,
        ders TEXT,
        konu_kaynak TEXT,
        son_tarih DATE,
        eklenme_tarihi DATE
    )''')
    
    # Ödev Takip Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odev_takip (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        odev_id INTEGER,
        ogrenci_adi_norm TEXT,
        durum TEXT DEFAULT 'Bekliyor',
        aciklama TEXT,
        FOREIGN KEY (odev_id) REFERENCES odevler(odev_id) ON DELETE CASCADE
    )''')
    
    # Hedefler Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        ogrenci_adi_norm TEXT PRIMARY KEY,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL
    )''')
    
    # Öğretmen Notları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogretmen_notlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT,
        tarih DATE,
        not_metni TEXT
    )''')
    
    # Kurum Ayarları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY DEFAULT 1,
        kurum_adi TEXT,
        logo_base64 TEXT
    )''')
    
    # Varsayılan Yöneticileri Ekle / Güncelle
    cursor.execute("INSERT OR REPLACE INTO kullanicilar (id, kullanici_adi, sifre, rol) VALUES (1, 'admin', 'admin123', 'admin')")
    cursor.execute("INSERT OR REPLACE INTO kullanicilar (id, kullanici_adi, sifre, rol) VALUES (2, 'ogretmen', 'ogretmen123', 'ogretmen')")
    
    conn.commit()
    conn.close()

init_db()

# --- 3. HELPER FUNCTIONS ---
def normalize_name(text):
    if not isinstance(text, str):
        return ""
    text = text.strip().upper()
    tr_map = str.maketrans("ÇĞİÖŞÜI", "CGIOSUI")
    text = text.translate(tr_map)
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return ' '.join(text.split())

def get_kurum_bilgileri():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kurum_adi, logo_base64 FROM kurum_ayarlari WHERE id = 1")
    res = cursor.fetchone()
    conn.close()
    if res:
        return res[0] or "Eğitim Kurumu", res[1] or ""
    return "Eğitim Kurumu", ""

def get_ogrenci_hedef(norm_adi):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT hedef_bolum, hedef_net, hedef_puan FROM ogrenci_hedefleri WHERE ogrenci_adi_norm = ?", (norm_adi,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {'bolum': res[0], 'net': res[1], 'puan': res[2]}
    return None

def render_student_report(norm_adi, ogr_adi, allow_notes=False):
    conn = sqlite3.connect("sinav_takip.db")
    
    st.header(f"👤 Öğrenci: {ogr_adi}")
    
    # Hedef Göstergesi
    hedef = get_ogrenci_hedef(norm_adi)
    if hedef:
        st.info(f"🎯 **Hedef Bölüm:** {hedef['bolum']} | **Hedef Net:** {hedef['net']} | **Hedef Puan:** {hedef['puan']}")
    
    # Sınav Sonuçları
    df_sonuc = pd.read_sql_query('''
        SELECT s.sinav_id, s.sinav_adi, s.tarih, os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.tyt_puan, os.kurum_sirasi
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE os.ogrenci_adi_norm = ?
        ORDER BY s.tarih ASC, s.sinav_id ASC
    ''', conn, params=(norm_adi,))
    
    if not df_sonuc.empty:
        st.subheader("📈 Sınav Net Gelişimi")
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(df_sonuc['sinav_adi'], df_sonuc['toplam_net'], marker='o', color='#3182ce', linewidth=2, label='Toplam Net')
        if hedef and hedef['net']:
            ax.axhline(y=hedef['net'], color='r', linestyle='--', label=f"Hedef Net ({hedef['net']})")
        ax.set_ylabel("Net")
        plt.xticks(rotation=45, ha='right')
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend()
        st.pyplot(fig)
        
        st.subheader("📊 Sınav Detay Tablosu")
        st.dataframe(df_sonuc.drop(columns=['sinav_id']), use_container_width=True)
        
        # --- AKILLI DERS & KONU GELİŞİM ANALİZİ ---
        st.markdown("---")
        c_eksik, c_basari = st.columns(2)
        
        # 1. En Son Sınav ID'sini alalım
        son_sinav_id = df_sonuc['sinav_id'].iloc[-1]
        
        # Öğrencinin TÜM sınavlardaki eksik kaydı
        df_tum_eksikler = pd.read_sql_query('''
            SELECT sinav_id, ders, konu_kazanim
            FROM ogrenci_eksikleri
            WHERE ogrenci_adi_norm = ?
        ''', conn, params=(norm_adi,))

        with c_eksik:
            st.subheader("⚠️ Aktif Eksik / Çalışılması Gereken Konular")
            if not df_tum_eksikler.empty:
                # Son sınavda yanlış yapılanlar güncel eksiklerdir
                df_son_eksik = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]
                if not df_son_eksik.empty:
                    df_eksik_ozet = df_son_eksik.groupby(['ders', 'konu_kazanim']).size().reset_index(name='Son Sınav Tekrarı')
                    
                    # 🔴 Kırmızı Arka Plan Stil Uygulaması
                    styled_eksik = df_eksik_ozet.style.set_properties(**{
                        'background-color': '#ffe5e5',
                        'color': '#900c3f',
                        'border-color': '#ffb3b3'
                    })
                    st.dataframe(styled_eksik, use_container_width=True)
                else:
                    st.success("🎉 Harika! Son sınavda tespit edilen yeni bir konu eksiği yok.")
            else:
                st.success("Tebrikler! Belirlenmiş bir konu eksiğiniz bulunmuyor.")

        with c_basari:
            st.subheader("✅ Başarıyla Halledilen Konular (Gelişim Gösterilen)")
            
            if not df_tum_eksikler.empty:
                # Geçmiş sınavlarda (son sınav hariç) yanlış yapılan konular
                gecmis_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] != son_sinav_id]['konu_kazanim'].unique()
                
                # Son sınavda yanlış yapılan konular
                son_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]['konu_kazanim'].unique()
                
                # KURAL: Geçmişte yanlış yapılmış AMA son sınavda eksik listesinden çıkmış konular = HALLEDİLEN KONULAR!
                halledilen_konular = [konu for konu in gecmis_eksikler if konu not in son_eksikler]
                
                if halledilen_konular:
                    df_halledilen = df_tum_eksikler[df_tum_eksikler['konu_kazanim'].isin(halledilen_konular)][['ders', 'konu_kazanim']].drop_duplicates()
                    df_halledilen['Gelişim Durumu'] = '🎉 Son Sınavda Doğru Yapıldı (Halledildi)'
                    
                    # 🟢 Yeşil Arka Plan Stil Uygulaması
                    styled_halledilen = df_halledilen.style.set_properties(**{
                        'background-color': '#e6ffe6',
                        'color': '#006600',
                        'border-color': '#b3ffb3'
                    })
                    st.dataframe(styled_halledilen, use_container_width=True)
                else:
                    st.info("Geçmiş sınavlarda yanlış yapılıp son sınavda düzeltilen henüz bir konu bulunmuyor. Denemeler arttıkça burası güncellenecektir.")
            else:
                st.info("Henüz karşılaştırma yapılacak yeterli eksik veri analizi yok.")
                
    else:
        st.warning("Bu öğrenciye ait girilmiş sınav sonucu bulunamadı.")
        
    # Öğretmen Notları Bölümü
    if allow_notes:
        st.markdown("---")
        st.subheader("📝 Öğretmen Görüş ve Notları")
        with st.form("ogretmen_not_form"):
            yeni_not = st.text_area("Öğrenci Hakkında Not Ekleyin:")
            if st.form_submit_button("Notu Kaydet"):
                if yeni_not.strip():
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO ogretmen_notlari (ogrenci_adi_norm, tarih, not_metni) VALUES (?, DATE('now'), ?)", (norm_adi, yeni_not.strip()))
                    conn.commit()
                    st.success("Not kaydedildi!")
                    
        df_notlar = pd.read_sql_query("SELECT tarih, not_metni FROM ogretmen_notlari WHERE ogrenci_adi_norm = ? ORDER BY id DESC", conn, params=(norm_adi,))
        if not df_notlar.empty:
            for _, row in df_notlar.iterrows():
                st.write(f"📅 **{row['tarih']}:** {row['not_metni']}")
    
    conn.close()

# --- 4. AUTHENTICATION (GİRİŞ) ---
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
                st.success("Giriş başarılı! Yönlendiriliyorsunuz...")
                st.rerun()
            else:
                st.error("Hatalı kullanıcı adı veya şifre.")

if not st.session_state['logged_in']:
    login()
    st.stop()

# --- 5. SIDEBAR & NAVIGATION ---
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

# Menü Yetkilendirmesi
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
    # Öğrenci / Veli Menüsü
    menu_options = [
        "🎓 Gelişim & Analiz Karnem",
        "📚 Ödevlerim & Ödev Durumu",
        "🎯 Üniversite / Hedefim"
    ]

secim = st.sidebar.radio("Navigasyon Menüsü:", menu_options)

# --- 6. PAGE ROUTING & LOGIC ---

# --- 1. MENÜ: SINAV YÜKLE & VERİ AKTARIMI ---
if secim == "📥 Sınav Yükle & Veri Aktarımı" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📥 Sınav Sonuçları ve Analiz PDF Yükleme")
    
    st.markdown("""
    Bu alandan **Excel/CSV** formatındaki sınav sonuç listesini ve öğrencilerin **Eksik Analiz PDF** dosyalarını sisteme aktarabilirsiniz.
    """)
    
    c1, c2, c3 = st.columns(3)
    sinav_adi = c1.text_input("Sınav Adı:", placeholder="Örn: Özdebir TYT Deneme-1")
    yayin_evi = c2.text_input("Yayın Evi:", placeholder="Örn: Özdebir")
    sinav_tarihi = c3.date_input("Sınav Tarihi")
    
    excel_file = st.file_uploader("📊 Sınav Sonuç Excel / CSV Dosyası Yükleyin:", type=["xlsx", "xls", "csv"])
    pdf_files = st.file_uploader("📑 Öğrenci Eksik Analiz PDF Dosyalarını Yükleyin (Çoklu Seçilebilir):", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 Sınavı ve Analizleri Sisteme Aktar", type="primary"):
        if sinav_adi and excel_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()
                
                # Sınavı Kaydet
                cursor.execute("INSERT INTO sinavlar (sinav_adi, tarih, yayin_evi) VALUES (?, ?, ?)", (sinav_adi, str(sinav_tarihi), yayin_evi))
                sinav_id = cursor.lastrowid
                
                # Excel Okuma
                if excel_file.name.endswith('.csv'):
                    df = pd.read_csv(excel_file)
                else:
                    df = pd.read_excel(excel_file)
                
                # Kolon Normalizasyonu
                df.columns = [str(c).strip().lower() for c in df.columns]
                
                for _, row in df.iterrows():
                    ogr_adi = str(row.get('ad soyad', row.get('ogrenci adi', row.get('ad', ''))))
                    ogr_norm = normalize_name(ogr_adi)
                    sinif = str(row.get('sinif', row.get('sınıf', '')))
                    
                    if ogr_norm:
                        cursor.execute('''
                        INSERT INTO ogrenci_sonuclari (
                            sinav_id, ogrenci_adi, ogrenci_adi_norm, sinif, kurum_sirasi,
                            turkce_d, turkce_y, turkce_net,
                            sosyal_d, sosyal_y, sosyal_net,
                            matematik_d, matematik_y, matematik_net,
                            fen_d, fen_y, fen_net,
                            toplam_net, tyt_puan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            sinav_id, ogr_adi, ogr_norm, sinif,
                            row.get('kurum sira', row.get('sira', 0)),
                            row.get('turkce d', 0), row.get('turkce y', 0), row.get('turkce net', 0),
                            row.get('sosyal d', 0), row.get('sosyal y', 0), row.get('sosyal net', 0),
                            row.get('matematik d', 0), row.get('matematik y', 0), row.get('matematik net', 0),
                            row.get('fen d', 0), row.get('fen y', 0), row.get('fen net', 0),
                            row.get('toplam net', 0), row.get('tyt puan', 0)
                        ))
                
                # PDF Analizlerini İşleme (Opsiyonel)
                if pdf_files:
                    try:
                        import pypdf
                        for pdf in pdf_files:
                            pdf_name = pdf.name.replace(".pdf", "")
                            pdf_norm_name = normalize_name(pdf_name)
                            
                            reader = pypdf.PdfReader(pdf)
                            full_text = ""
                            for page in reader.pages:
                                full_text += page.extract_text() + "\n"
                            
                            lines = full_text.split('\n')
                            for line in lines:
                                if ":" in line:
                                    parts = line.split(":")
                                    konu_temiz = parts[0].strip()
                                    sorular = parts[1].strip() if len(parts) > 1 else ""
                                    cursor.execute('''
                                    INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (sinav_id, pdf_name, pdf_norm_name, "Genel", konu_temiz, sorular))
                    except ImportError:
                        st.warning("PyPDF kütüphanesi yüklenmediği için PDF okuma işlemi atlandı. (pip install pypdf)")

                conn.commit()
                conn.close()
                st.success(f"✅ '{sinav_adi}' sınav verileri başarıyla veritabanına aktarıldı!")
            except Exception as e:
                st.error(f"Sınav aktarılırken bir hata oluştu: {str(e)}")
        else:
            st.warning("Lütfen tüm alanları doldurun ve sınav dosyasını yükleyin.")

# --- 2. MENÜ: ÖĞRENCİ KARNELERİ & ANALİZ ---
elif secim in ["📊 Öğrenci Karneleri & Analiz", "🎓 Gelişim & Analiz Karnem"]:
    st.title("📑 Öğrenci Gelişim Karnesi ve Bireysel Analiz")
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC", conn)
        if not df_ogrenciler.empty:
            ogr_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
            secilen_norm = st.selectbox("Analiz Edilecek Öğrenciyi Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            secilen_ogr_adi = ogr_dict[secilen_norm]
            render_student_report(secilen_norm, secilen_ogr_adi, allow_notes=True)
        else:
            st.info("Sistemde henüz kayıtlı öğrenci sonucu bulunmamaktadır.")
    else:
        # Öğrenci / Veli Girişi
        norm_adi = st.session_state['user_info']['norm_adi']
        if norm_adi:
            render_student_report(norm_adi, st.session_state['user_info']['username'], allow_notes=False)
        else:
            st.warning("Hesabınıza tanımlı bir öğrenci kaydı bulunamadı. Lütfen yönetimle iletişime geçin.")
    conn.close()

# --- 3. MENÜ: ÖDEV & SORU BANKASI TAKİBİ ---
elif secim in ["📚 Ödev & Soru Bankası Takibi", "📚 Ödevlerim & Ödev Durumu"]:
    st.title("📚 Ödev & Soru Bankası Takip Modülü")
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        tab_odev_ver, tab_odev_liste = st.tabs(["➕ Yeni Ödev Ver", "📋 Ödev Durumları & Kontrol"])
        
        with tab_odev_ver:
            st.subheader("Yeni Ödev Tanımlama")
            c1, c2, c3 = st.columns(3)
            sinif_secim = c1.selectbox("Sınıf / Grup:", ["Tüm Sınıflar", "12-A", "12-B", "12-C", "11-A", "Mezun"])
            ders_secim = c2.selectbox("Ders:", ["Matematik", "Fizik", "Kimya", "Biyoloji", "Türkçe", "Tarih", "Coğrafya", "Felsefe"])
            son_tarih = c3.date_input("Son Teslim Tarihi")
            
            konu_kaynak = st.text_input("Ödev Konusu / Kaynak ve Sayfa Aralığı:", placeholder="Örn: 345 Matematik SB - Türev Test 1-5 (Sayfa 120-130)")
            
            if st.button("🚀 Ödevi Yayınla", type="primary"):
                if konu_kaynak.strip():
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO odevler (sinif, ders, konu_kaynak, son_tarih, eklenme_tarihi)
                        VALUES (?, ?, ?, ?, DATE('now'))
                    ''', (sinif_secim, ders_secim, konu_kaynak, str(son_tarih)))
                    odev_id = cursor.lastrowid
                    
                    if sinif_secim == "Tüm Sınıflar":
                        df_ogrs = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm FROM ogrenci_sonuclari", conn)
                    else:
                        df_ogrs = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm FROM ogrenci_sonuclari WHERE sinif = ?", conn, params=(sinif_secim,))
                    
                    for _, row in df_ogrs.iterrows():
                        cursor.execute("INSERT OR IGNORE INTO odev_takip (odev_id, ogrenci_adi_norm) VALUES (?, ?)", (odev_id, row['ogrenci_adi_norm']))
                    
                    conn.commit()
                    st.success("Ödev başarıyla oluşturuldu ve öğrencilere atandı!")
                else:
                    st.warning("Lütfen ödev konusunu ve kaynağını belirtin.")
                    
        with tab_odev_liste:
            st.subheader("Ödev Takip Listesi")
            df_odevler = pd.read_sql_query("SELECT * FROM odevler ORDER BY odev_id DESC", conn)
            if not df_odevler.empty:
                secilen_odev_id = st.selectbox("İncelenecek Ödev:", df_odevler['odev_id'].tolist(), format_func=lambda x: f"ID:{x} - {df_odevler[df_odevler['odev_id']==x]['ders'].values[0]} ({df_odevler[df_odevler['odev_id']==x]['konu_kaynak'].values[0]})")
                
                df_takip = pd.read_sql_query('''
                    SELECT ot.id, os.ogrenci_adi, os.sinif, ot.durum, ot.aciklama 
                    FROM odev_takip ot
                    JOIN ogrenci_sonuclari os ON ot.ogrenci_adi_norm = os.ogrenci_adi_norm
                    WHERE ot.odev_id = ?
                    GROUP BY ot.ogrenci_adi_norm
                ''', conn, params=(secilen_odev_id,))
                
                if not df_takip.empty:
                    edited_df = st.data_editor(
                        df_takip,
                        column_config={
                            "durum": st.column_config.SelectboxColumn("Ödev Durumu", options=["Bekliyor", "Tamamlandı", "Eksik Yapıldı", "Yapılmadı"], required=True),
                            "aciklama": st.column_config.TextColumn("Öğretmen Notu")
                        },
                        disabled=["id", "ogrenci_adi", "sinif"],
                        use_container_width=True
                    )
                    
                    if st.button("💾 Ödev Durumlarını Kaydet"):
                        cursor = conn.cursor()
                        for _, row in edited_df.iterrows():
                            cursor.execute("UPDATE odev_takip SET durum = ?, aciklama = ? WHERE id = ?", (row['durum'], row['aciklama'], row['id']))
                        conn.commit()
                        st.success("Ödev durumları başarıyla güncellendi!")
                else:
                    st.info("Bu ödeve tanımlı öğrenci bulunamadı.")
            else:
                st.info("Henüz eklenmiş bir ödev bulunmuyor.")
    else:
        st.subheader("📚 Ödevlerim ve Durumları")
        norm_adi = st.session_state['user_info']['norm_adi']
        df_my_odev = pd.read_sql_query('''
            SELECT o.ders, o.konu_kaynak, o.son_tarih, ot.durum, ot.aciklama
            FROM odev_takip ot
            JOIN odevler o ON ot.odev_id = o.odev_id
            WHERE ot.ogrenci_adi_norm = ?
            ORDER BY o.son_tarih DESC
        ''', conn, params=(norm_adi,))
        
        if not df_my_odev.empty:
            st.dataframe(df_my_odev, use_container_width=True)
        else:
            st.info("Atanmış aktif bir ödeviniz bulunmamaktadır.")
    conn.close()

# --- 4. MENÜ: VELİ BİLGİLENDİRME & WHATSAPP/SMS ---
elif secim == "📱 Veli Bilgilendirme & WhatsApp/SMS":
    st.title("📱 Veli Bilgilendirme & WhatsApp / SMS Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    
    df_veliler = pd.read_sql_query("SELECT kullanici_adi, telefon, ogrenci_adi_norm FROM kullanicilar WHERE telefon IS NOT NULL AND telefon != ''", conn)
    
    if not df_veliler.empty:
        c1, c2 = st.columns([1, 2])
        with c1:
            secilen_kullanici = st.selectbox("Kişi Seçin:", df_veliler['kullanici_adi'].tolist())
            user_info = df_veliler[df_veliler['kullanici_adi'] == secilen_kullanici].iloc[0]
            tel_no = user_info['telefon']
            
            sablon = st.radio("Mesaj Şablonu:", [
                "📊 Son Sınav Karnesi Bilgilendirmesi",
                "⚠️ Eksik Ödev Hatırlatması",
                "✍️ Özel Mesaj"
            ])
            
        with c2:
            if sablon == "📊 Son Sınav Karnesi Bilgilendirmesi":
                varsayilan_mesaj = f"Sayın Velimiz, öğrencimiz {secilen_kullanici}'in son deneme sınavı sonuçları sisteme yüklenmiştir. Sınav portalı üzerinden detaylı analizi inceleyebilirsiniz."
            elif sablon == "⚠️ Eksik Ödev Hatırlatması":
                varsayilan_mesaj = f"Sayın Velimiz, öğrencimiz {secilen_kullanici}'in teslim tarihi geçen eksik ödevleri bulunmaktadır. Detaylar için portalı kontrol edebilirsiniz."
            else:
                varsayilan_mesaj = ""
                
            mesaj_metni = st.text_area("Gönderilecek Mesaj İçeriği:", value=varsayilan_mesaj, height=150)
            
            if mesaj_metni:
                encoded_msg = urllib.parse.quote(mesaj_metni)
                whatsapp_url = f"https://wa.me/{tel_no}?text={encoded_msg}"
                st.markdown(f'<a href="{whatsapp_url}" target="_blank"><button style="background-color:#25D366; color:white; border:none; padding:12px 24px; font-size:16px; border-radius:8px; cursor:pointer; font-weight:bold;">💬 WhatsApp ile Gönder ({tel_no})</button></a>', unsafe_allow_html=True)
    else:
        st.warning("Telefon numarası kayıtlı veli/öğrenci bulunamadı. 'Öğrenci & Veli Hesap Yönetimi' menüsünden telefon numarası ekleyebilirsiniz.")
    conn.close()

# --- 5. MENÜ: HEDEF BELİRLEME & TAKİP ---
elif secim in ["🎯 Hedef Belirleme & Takip", "🎯 Üniversite / Hedefim"]:
    st.title("🎯 Üniversite & Hedef Net Takip Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogr = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC", conn)
        if not df_ogr.empty:
            ogr_dict = dict(zip(df_ogr['ogrenci_adi_norm'], df_ogr['ogrenci_adi']))
            secilen_norm = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            
            hedef_mevcut = get_ogrenci_hedef(secilen_norm)
            
            with st.form("hedef_form"):
                hedef_bolum = st.text_input("Hedeflenen Üniversite & Bölüm:", value=hedef_mevcut['bolum'] if hedef_mevcut else "")
                hedef_net = st.number_input("Hedeflenen TYT Toplam Net:", min_value=0.0, max_value=120.0, value=float(hedef_mevcut['net']) if hedef_mevcut else 75.0)
                hedef_puan = st.number_input("Hedeflenen TYT Puanı:", min_value=0.0, max_value=500.0, value=float(hedef_mevcut['puan']) if hedef_mevcut else 350.0)
                
                if st.form_submit_button("🎯 Hedefi Kaydet / Güncelle"):
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET
                        hedef_bolum=excluded.hedef_bolum,
                        hedef_net=excluded.hedef_net,
                        hedef_puan=excluded.hedef_puan
                    ''', (secilen_norm, hedef_bolum, hedef_net, hedef_puan))
                    conn.commit()
                    st.success("Hedef başarıyla kaydedildi!")
    else:
        norm_adi = st.session_state['user_info']['norm_adi']
        hedef = get_ogrenci_hedef(norm_adi)
        if hedef:
            st.success(f"🎯 **Hedef Bölümünüz:** {hedef['bolum']}")
            c1, c2 = st.columns(2)
            c1.metric("Hedef Net", f"{hedef['net']} Net")
            c2.metric("Hedef Puan", f"{hedef['puan']} Puan")
        else:
            st.info("Henüz tanımlanmış bir hedefiniz bulunmuyor. Rehberlik öğretmeninizle iletişime geçebilirsiniz.")
    conn.close()

# --- 6. MENÜ: OKUL GENEL DURUMU & DERECELER ---
elif secim == "🏫 Okul Genel Durumu & Dereceler":
    st.title("🏫 Okul Genel Başarı Durumu & Dereceler")
    conn = sqlite3.connect("sinav_takip.db")
    
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar ORDER BY sinav_id DESC", conn)
    if not df_sinavlar.empty:
        secilen_sinav_id = st.selectbox("Sınav Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0])
        
        df_derece = pd.read_sql_query('''
            SELECT kurum_sirasi as 'Sıra', ogrenci_adi as 'Öğrenci Adı', sinif as 'Sınıf', turkce_net as 'Türkçe', sosyal_net as 'Sosyal', matematik_net as 'Matematik', fen_net as 'Fen', toplam_net as 'Toplam Net', tyt_puan as 'TYT Puanı'
            FROM ogrenci_sonuclari
            WHERE sinav_id = ?
            ORDER BY kurum_sirasi ASC
        ''', conn, params=(secilen_sinav_id,))
        
        st.subheader("🏆 Sınav Derece Listesi (Dereceye Giren İlk 10 Öğrenci)")
        st.dataframe(df_derece.head(10), use_container_width=True)
        
        st.subheader("📊 Tüm Öğrenci Sıralaması")
        st.dataframe(df_derece, use_container_width=True)
    else:
        st.info("Kayıtlı sınav bulunamadı.")
    conn.close()

# --- 7. MENÜ: SINIF KARŞILAŞTIRMALI RADAR & DAĞILIM ---
elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım":
    st.title("🕸️ Sınıf Bazlı Ders Ortalamaları ve Karşılaştırma")
    conn = sqlite3.connect("sinav_takip.db")
    
    df_sinif_ort = pd.read_sql_query('''
        SELECT sinif, AVG(turkce_net) as Türkçe, AVG(sosyal_net) as Sosyal, AVG(matematik_net) as Matematik, AVG(fen_net) as Fen, AVG(toplam_net) as Toplam
        FROM ogrenci_sonuclari
        GROUP BY sinif
    ''', conn)
    
    if not df_sinif_ort.empty:
        st.subheader("📊 Sınıf Ders Ortalamaları Tablosu")
        st.dataframe(df_sinif_ort.style.highlight_max(axis=0, color='#c6f6d5'), use_container_width=True)
        
        st.subheader("📈 Sınıf Toplam Net Ortalamaları")
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(df_sinif_ort['sinif'], df_sinif_ort['Toplam'], color='#3182ce')
        ax.set_ylabel("Ortalama Toplam Net")
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        st.pyplot(fig)
    else:
        st.info("Analiz için yeterli veri bulunmamaktadır.")
    conn.close()

# --- 8. MENÜ: OKUL KONU/KAZANIM ANALİZİ ---
elif secim == "🔥 Okul Konu/Kazanım Analizi":
    st.title("🔥 Okul Genel Konu ve Kazanım Analizi")
    conn = sqlite3.connect("sinav_takip.db")
    
    df_eksikler = pd.read_sql_query('''
        SELECT konu_kazanim, COUNT(*) as 'Yanlış Yapılma Sayısı'
        FROM ogrenci_eksikleri
        GROUP BY konu_kazanim
        ORDER BY [Yanlış Yapılma Sayısı] DESC
        LIMIT 15
    ''', conn)
    
    if not df_eksikler.empty:
        st.subheader("⚠️ Okul Genelinde En Çok Yanlış Yapılan İlk 15 Konu")
        st.dataframe(df_eksikler, use_container_width=True)
        
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.barh(df_eksikler['konu_kazanim'], df_eksikler['Yanlış Yapılma Sayısı'], color='#e53e3e')
        ax.invert_yaxis()
        ax.set_xlabel("Toplam Hata/Yanlış Frekansı")
        ax.grid(axis='x', linestyle='--', alpha=0.7)
        st.pyplot(fig)
    else:
        st.info("Kazanım eksik verisi bulunamadı.")
    conn.close()

# --- 9. MENÜ: ÖĞRENCİ & VELİ HESAP YÖNETİMİ ---
elif secim == "👥 Öğrenci & Veli Hesap Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Öğrenci ve Veli Kullanıcı Hesap Yönetimi")
    conn = sqlite3.connect("sinav_takip.db")
    
    tab_yeni, tab_liste = st.tabs(["➕ Yeni Kullanıcı Tanımla", "📋 Kullanıcı Listesi"])
    
    with tab_yeni:
        with st.form("kullanici_ekle_form"):
            c1, c2 = st.columns(2)
            k_adi = c1.text_input("Kullanıcı Adı:")
            sifre = c2.text_input("Şifre:", type="password")
            
            c3, c4 = st.columns(2)
            rol = c3.selectbox("Rol:", ["ogrenci", "veli", "ogretmen", "admin"])
            telefon = c4.text_input("Telefon No (WhatsApp için - Örn: 905xxxxxxxxx):")
            
            df_ogrs = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
            ogr_norm = None
            if not df_ogrs.empty and rol in ['ogrenci', 'veli']:
                ogr_dict = dict(zip(df_ogrs['ogrenci_adi_norm'], df_ogrs['ogrenci_adi']))
                ogr_norm = st.selectbox("İlişkilendirilecek Öğrenci:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
                
            if st.form_submit_button("➕ Kullanıcıyı Oluştur"):
                if k_adi and sifre:
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, ?, ?, ?, ?)", (k_adi.strip(), sifre.strip(), rol, ogr_norm, telefon.strip()))
                        conn.commit()
                        st.success("Kullanıcı başarıyla oluşturuldu!")
                    except Exception as e:
                        st.error(f"Kullanıcı eklenirken hata oluştu: {str(e)}")
                        
    with tab_liste:
        df_users = pd.read_sql_query("SELECT id, kullanici_adi, rol, ogrenci_adi_norm, telefon FROM kullanicilar", conn)
        st.dataframe(df_users, use_container_width=True)
    conn.close()

# --- 10. MENÜ: KURUM AYARLARI & LOGO ---
elif secim == "⚙️ Kurum Ayarları & Logo" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum Ayarları ve Logo Yükleme")
    conn = sqlite3.connect("sinav_takip.db")
    
    kurum_adi, logo_b64 = get_kurum_bilgileri()
    
    yeni_kurum_adi = st.text_input("Kurum Adı:", value=kurum_adi)
    uploaded_logo = st.file_uploader("Kurum Logosu (PNG/JPG):", type=["png", "jpg", "jpeg"])
    
    if st.button("💾 Ayarları Kaydet"):
        cursor = conn.cursor()
        b64_str = logo_b64
        if uploaded_logo:
            b64_str = base64.b64encode(uploaded_logo.read()).decode('utf-8')
            
        cursor.execute("DELETE FROM kurum_ayarlari")
        cursor.execute("INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) VALUES (1, ?, ?)", (yeni_kurum_adi, b64_str))
        conn.commit()
        st.success("Kurum bilgileri başarıyla güncellendi!")
    conn.close()

# --- 11. MENÜ: SINAV YÖNETİMİ & SİLME ---
elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Yönetimi ve Veri Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar ORDER BY sinav_id DESC", conn)
    if not df_sinavlar.empty:
        st.dataframe(df_sinavlar, use_container_width=True)
        
        silinecek_id = st.selectbox("Silinecek Sınavı Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: f"ID: {x} - {df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0]}")
        
        if st.button("🔴 Sınavı ve Tüm Sonuçlarını Kalıcı Olarak Sil", type="primary"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (silinecek_id,))
            conn.commit()
            st.success("Sınav ve bağlı tüm veriler veritabanından başarıyla silindi!")
            st.rerun()
    else:
        st.info("Kayıtlı sınav bulunmamaktadır.")
    conn.close()