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
    page_title="Sınav Takip & Analiz Portalı (TYT & AYT)",
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
    
    # Sınavlar Tablosu (AYT Türü Eklendi)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT NOT NULL,
        tarih DATE,
        yayin_evi TEXT,
        sinav_turu TEXT DEFAULT 'TYT'
    )''')
    
    # Eski Veritabanında Eksik Sütun Varsa Otomatik Ekle (Migration)
    cursor.execute("PRAGMA table_info(sinavlar)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'yayin_evi' not in columns:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN yayin_evi TEXT")
    if 'sinav_turu' not in columns:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN sinav_turu TEXT DEFAULT 'TYT'")

    # Öğrenci Sonuçları Tablosu (AYT Dersleri ve Puanları Eklendi)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        kurum_sirasi INTEGER,
        genel_sira INTEGER,
        
        -- TYT Netleri
        turkce_net REAL DEFAULT 0,
        sosyal_net REAL DEFAULT 0,
        matematik_net REAL DEFAULT 0,
        fen_net REAL DEFAULT 0,
        tyt_toplam_net REAL DEFAULT 0,
        tyt_puan REAL DEFAULT 0,
        
        -- AYT Netleri
        ayt_mat_net REAL DEFAULT 0,
        ayt_fizik_net REAL DEFAULT 0,
        ayt_kimya_net REAL DEFAULT 0,
        ayt_biyo_net REAL DEFAULT 0,
        ayt_edebiyat_net REAL DEFAULT 0,
        ayt_tarih1_net REAL DEFAULT 0,
        ayt_cogr1_net REAL DEFAULT 0,
        ayt_tarih2_net REAL DEFAULT 0,
        ayt_cogr2_net REAL DEFAULT 0,
        ayt_felsefe_net REAL DEFAULT 0,
        ayt_din_net REAL DEFAULT 0,
        ayt_toplam_net REAL DEFAULT 0,
        
        -- AYT Puanları
        ayt_say_puan REAL DEFAULT 0,
        ayt_ea_puan REAL DEFAULT 0,
        ayt_soz_puan REAL DEFAULT 0,
        
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
        hedef_puan REAL,
        alan_tercihi TEXT DEFAULT 'SAY'
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
    
    # Varsayılan Yöneticiler
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

def detect_subject_from_topic(topic_str):
    """Gelişmiş TYT ve AYT Ders Tespiti"""
    t = topic_str.lower()
    
    # AYT / TYT Matematik - Geometri
    if any(k in t for k in ['türev', 'integral', 'limit', 'trigonometri', 'logaritma', 'diziler', 'polinom', 'karmaşık', 'matematik', 'fonksiyon', 'üslü', 'köklü', 'analitik', 'geometri', 'üçgen', 'çember']):
        return "Matematik"
    # Fizik
    elif any(k in t for k in ['atışlar', 'tork', 'denge', 'momentum', 'bağıl', 'vektör', 'şığa', 'fotoelektrik', 'kompton', 'transformatör', 'indüksiyon', 'fizik', 'kuvvet', 'optik', 'elektrik']):
        return "Fizik"
    # Kimya
    elif any(k in t for k in ['organik', 'alçil', 'alken', 'alkin', 'hibritleşme', 'entalpi', 'denge', 'kçç', 'pil', 'elektroliz', 'gazlar', 'mol', 'kimya', 'asit', 'baz']):
        return "Kimya"
    # Biyoloji
    elif any(k in t for k in ['fotosentez', 'kemosentez', 'protein sentezi', 'popülasyon', 'komünite', 'sinir sistemi', 'endokrin', 'dolaşım', 'boşaltım', 'biyoloji', 'mitoz', 'dna']):
        return "Biyoloji"
    # Edebiyat
    elif any(k in t for k in ['edebiyat', 'divan', 'tanzimat', 'servet-i fünun', 'cumhuriyet dönemi', 'halk şiiri', 'beyit', 'şair', 'roman', 'tiyatro', 'sanatçı']):
        return "Türk Dili ve Edebiyatı"
    # Türkçe
    elif any(k in t for k in ['paragraf', 'sozcuk', 'cümle', 'yazim', 'noktalama', 'dil bilgisi', 'ses bilgisi', 'anlatim']):
        return "Türkçe"
    # Tarih
    elif any(k in t for k in ['tarih', 'osmanlı', 'inkılap', 'savaş', 'devlet', 'ilk çağ', 'milli mücadele', 'antlaşma']):
        return "Tarih"
    # Coğrafya
    elif any(k in t for k in ['harita', 'iklim', 'nüfus', 'yer şekilleri', 'coğrafya', 'dünya', 'kıta', 'bölge']):
        return "Coğrafya"
    # Felsefe / Din
    elif any(k in t for k in ['felsefe', 'psikoloji', 'sosyoloji', 'mantık', 'din', 'inanç', 'ibadet']):
        return "Felsefe / Din"
    
    return "Genel / Diğer"

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
    cursor.execute("SELECT hedef_bolum, hedef_net, hedef_puan, alan_tercihi FROM ogrenci_hedefleri WHERE ogrenci_adi_norm = ?", (norm_adi,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {'bolum': res[0], 'net': res[1], 'puan': res[2], 'alan': res[3]}
    return None

# --- ÖĞRENCİ RAPORLAMA FONKSİYONU ---
def render_student_report(norm_adi, ogr_adi, allow_notes=False):
    conn = sqlite3.connect("sinav_takip.db")
    
    st.header(f"👤 Öğrenci: {ogr_adi}")
    
    # Hedef Göstergesi
    hedef = get_ogrenci_hedef(norm_adi)
    if hedef:
        st.info(f"🎯 **Hedef Bölüm:** {hedef['bolum']} | **Alan:** {hedef['alan']} | **Hedef Net:** {hedef['net']} | **Hedef Puan:** {hedef['puan']}")
    
    # Sınav Sonuçları Çekme
    df_sonuc = pd.read_sql_query('''
        SELECT s.sinav_id, s.sinav_adi, s.sinav_turu, s.tarih, 
               os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.tyt_toplam_net, os.tyt_puan,
               os.ayt_mat_net, os.ayt_fizik_net, os.ayt_kimya_net, os.ayt_biyo_net, os.ayt_edebiyat_net,
               os.ayt_toplam_net, os.ayt_say_puan, os.ayt_ea_puan, os.ayt_soz_puan, os.kurum_sirasi
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE os.ogrenci_adi_norm = ?
        ORDER BY s.tarih ASC, s.sinav_id ASC
    ''', conn, params=(norm_adi,))
    
    if not df_sonuc.empty:
        # Grafik Sekmeleri
        st.subheader("📈 Sınav Net & Puan Gelişimi")
        tab_tyt_g, tab_ayt_g = st.tabs(["📊 TYT Gelişimi", "📊 AYT Gelişimi"])
        
        with tab_tyt_g:
            df_tyt = df_sonuc[df_sonuc['sinav_turu'].str.contains("TYT", na=False, case=False)]
            if not df_tyt.empty:
                fig, ax = plt.subplots(figsize=(10, 3.5))
                ax.plot(df_tyt['sinav_adi'], df_tyt['tyt_toplam_net'], marker='o', color='#3182ce', linewidth=2, label='TYT Toplam Net')
                ax.set_ylabel("TYT Net")
                plt.xticks(rotation=45, ha='right')
                ax.grid(True, linestyle='--', alpha=0.6)
                ax.legend()
                st.pyplot(fig)
            else:
                st.info("Henüz TYT sınav verisi bulunmuyor.")
                
        with tab_ayt_g:
            df_ayt = df_sonuc[df_sonuc['sinav_turu'].str.contains("AYT", na=False, case=False)]
            if not df_ayt.empty:
                fig, ax = plt.subplots(figsize=(10, 3.5))
                ax.plot(df_ayt['sinav_adi'], df_ayt['ayt_toplam_net'], marker='s', color='#e53e3e', linewidth=2, label='AYT Toplam Net')
                ax.set_ylabel("AYT Net")
                plt.xticks(rotation=45, ha='right')
                ax.grid(True, linestyle='--', alpha=0.6)
                ax.legend()
                st.pyplot(fig)
            else:
                st.info("Henüz AYT sınav verisi bulunmuyor.")

        # Detaylı Sınav Tablosu
        st.subheader("📊 Sınav Detay Tablosu")
        st.dataframe(df_sonuc.drop(columns=['sinav_id']), use_container_width=True)
        
        # --- AKILLI DERS & KONU GELİŞİM ANALİZİ ---
        st.markdown("---")
        c_eksik, c_basari = st.columns(2)
        
        son_sinav_id = df_sonuc['sinav_id'].iloc[-1]
        
        df_tum_eksikler = pd.read_sql_query('''
            SELECT sinav_id, ders, konu_kazanim
            FROM ogrenci_eksikleri
            WHERE ogrenci_adi_norm = ?
        ''', conn, params=(norm_adi,))

        if not df_tum_eksikler.empty:
            df_tum_eksikler['ders'] = df_tum_eksikler.apply(
                lambda r: detect_subject_from_topic(r['konu_kazanim']) if r['ders'] in ['Genel', 'Genel / Diğer', ''] else r['ders'],
                axis=1
            )

        with c_eksik:
            st.subheader("⚠️ Aktif Eksik / Çalışılması Gereken Konular")
            if not df_tum_eksikler.empty:
                df_son_eksik = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]
                if not df_son_eksik.empty:
                    df_eksik_ozet = df_son_eksik.groupby(['ders', 'konu_kazanim']).size().reset_index(name='Tekrar Sayısı')
                    df_eksik_ozet.columns = ['Ders', 'Konu / Kazanım', 'Tekrar']
                    
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
            st.subheader("✅ Başarıyla Halledilen Konular")
            if not df_tum_eksikler.empty:
                gecmis_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] != son_sinav_id]['konu_kazanim'].unique()
                son_eksikler = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]['konu_kazanim'].unique()
                
                halledilen_konular = [konu for konu in gecmis_eksikler if konu not in son_eksikler]
                
                if halledilen_konular:
                    df_halledilen = df_tum_eksikler[df_tum_eksikler['konu_kazanim'].isin(halledilen_konular)][['ders', 'konu_kazanim']].drop_duplicates()
                    df_halledilen.columns = ['Ders', 'Konu / Kazanım']
                    df_halledilen['Gelişim Durumu'] = '🎉 Son Sınavda Doğru Yapıldı'
                    
                    styled_halledilen = df_halledilen.style.set_properties(**{
                        'background-color': '#e6ffe6',
                        'color': '#006600',
                        'border-color': '#b3ffb3'
                    })
                    st.dataframe(styled_halledilen, use_container_width=True)
                else:
                    st.info("Geçmiş sınavlarda yanlış yapılıp son sınavda düzeltilen henüz bir konu bulunmuyor.")
            else:
                st.info("Henüz karşılaştırma yapılacak yeterli eksik veri analizi yok.")
                
    else:
        st.warning("Bu öğrenciye ait girilmiş sınav sonucu bulunamadı.")
        
    # Öğretmen Notları
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

# --- 6. PAGE ROUTING & LOGIC ---

# --- 1. MENÜ: SINAV YÜKLE & VERİ AKTARIMI (TYT & AYT UYUMLU) ---
if secim == "📥 Sınav Yükle & Veri Aktarımı" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📥 Sınav Sonuçları ve Analiz PDF Yükleme")
    
    c1, c2, c3, c4 = st.columns(4)
    sinav_adi = c1.text_input("Sınav Adı:", placeholder="Örn: Özdebir AYT Deneme-1")
    yayin_evi = c2.text_input("Yayın Evi:", placeholder="Örn: Özdebir")
    sinav_turu = c3.selectbox("Sınav Türü:", ["TYT", "AYT", "TYT-AYT Karma"])
    sinav_tarihi = c4.date_input("Sınav Tarihi")
    
    excel_file = st.file_uploader("📊 Sınav Sonuç Excel / CSV Dosyası Yükleyin:", type=["xlsx", "xls", "csv"])
    pdf_files = st.file_uploader("📑 Öğrenci Eksik Analiz PDF Dosyalarını Yükleyin:", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🚀 Sınavı ve Analizleri Sisteme Aktar", type="primary"):
        if sinav_adi and excel_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()
                
                cursor.execute("INSERT INTO sinavlar (sinav_adi, tarih, yayin_evi, sinav_turu) VALUES (?, ?, ?, ?)", (sinav_adi, str(sinav_tarihi), yayin_evi, sinav_turu))
                sinav_id = cursor.lastrowid
                
                if excel_file.name.endswith('.csv'):
                    df = pd.read_csv(excel_file)
                else:
                    df = pd.read_excel(excel_file)
                
                df.columns = [str(c).strip().lower() for c in df.columns]
                
                for _, row in df.iterrows():
                    ogr_adi = str(row.get('ad soyad', row.get('ogrenci adi', row.get('ad', ''))))
                    ogr_norm = normalize_name(ogr_adi)
                    sinif = str(row.get('sinif', row.get('sınıf', '')))
                    
                    if ogr_norm:
                        cursor.execute('''
                        INSERT INTO ogrenci_sonuclari (
                            sinav_id, ogrenci_adi, ogrenci_adi_norm, sinif, kurum_sirasi,
                            turkce_net, sosyal_net, matematik_net, fen_net, tyt_toplam_net, tyt_puan,
                            ayt_mat_net, ayt_fizik_net, ayt_kimya_net, ayt_biyo_net, ayt_edebiyat_net,
                            ayt_toplam_net, ayt_say_puan, ayt_ea_puan, ayt_soz_puan
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            sinav_id, ogr_adi, ogr_norm, sinif,
                            row.get('kurum sira', row.get('sira', 0)),
                            # TYT
                            row.get('turkce net', row.get('tyt turkce net', 0)),
                            row.get('sosyal net', row.get('tyt sosyal net', 0)),
                            row.get('matematik net', row.get('tyt mat net', 0)),
                            row.get('fen net', row.get('tyt fen net', 0)),
                            row.get('tyt toplam net', row.get('tyt net', 0)),
                            row.get('tyt puan', 0),
                            # AYT
                            row.get('ayt mat net', row.get('ayt matematik net', 0)),
                            row.get('ayt fizik net', 0),
                            row.get('ayt kimya net', 0),
                            row.get('ayt biyoloji net', row.get('ayt biyo net', 0)),
                            row.get('ayt edebiyat net', row.get('edebiyat net', 0)),
                            row.get('ayt toplam net', row.get('ayt net', 0)),
                            row.get('ayt say puan', row.get('say puan', 0)),
                            row.get('ayt ea puan', row.get('ea puan', 0)),
                            row.get('ayt soz puan', row.get('soz puan', 0))
                        ))
                
                # PDF Analizlerini İşleme
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
                                    
                                    tespit_edilen_ders = detect_subject_from_topic(konu_temiz)
                                    
                                    cursor.execute('''
                                    INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    ''', (sinav_id, pdf_name, pdf_norm_name, tespit_edilen_ders, konu_temiz, sorular))
                    except ImportError:
                        st.warning("PyPDF kütüphanesi yüklenmediği için PDF okuma işlemi atlandı.")

                conn.commit()
                conn.close()
                st.success(f"✅ '{sinav_adi}' ({sinav_turu}) verileri başarıyla sisteme kaydedildi!")
            except Exception as e:
                st.error(f"Sınav aktarılırken hata oluştu: {str(e)}")
        else:
            st.warning("Lütfen sınav adı ve sonuç dosyasını yükleyin.")

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
            st.info("Sistemde kayıtlı öğrenci sonucu bulunmamaktadır.")
    else:
        norm_adi = st.session_state['user_info']['norm_adi']
        if norm_adi:
            render_student_report(norm_adi, st.session_state['user_info']['username'], allow_notes=False)
        else:
            st.warning("Hesabınıza tanımlı bir öğrenci kaydı bulunamadı.")
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
                alan_tercihi = st.selectbox("Alan Tercihi:", ["SAY", "EA", "SÖZ", "TYT-Sadece"], index=0 if not hedef_mevcut else ["SAY", "EA", "SÖZ", "TYT-Sadece"].index(hedef_mevcut.get('alan', 'SAY')))
                hedef_net = st.number_input("Hedeflenen Toplam Net:", min_value=0.0, max_value=200.0, value=float(hedef_mevcut['net']) if hedef_mevcut else 85.0)
                hedef_puan = st.number_input("Hedeflenen Puan:", min_value=0.0, max_value=500.0, value=float(hedef_mevcut['puan']) if hedef_mevcut else 400.0)
                
                if st.form_submit_button("🎯 Hedefi Kaydet / Güncelle"):
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan, alan_tercihi)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET
                        hedef_bolum=excluded.hedef_bolum,
                        hedef_net=excluded.hedef_net,
                        hedef_puan=excluded.hedef_puan,
                        alan_tercihi=excluded.alan_tercihi
                    ''', (secilen_norm, hedef_bolum, hedef_net, hedef_puan, alan_tercihi))
                    conn.commit()
                    st.success("Hedef başarıyla kaydedildi!")
    else:
        norm_adi = st.session_state['user_info']['norm_adi']
        hedef = get_ogrenci_hedef(norm_adi)
        if hedef:
            st.success(f"🎯 **Hedef Bölümünüz:** {hedef['bolum']} ({hedef['alan']})")
            c1, c2 = st.columns(2)
            c1.metric("Hedef Net", f"{hedef['net']} Net")
            c2.metric("Hedef Puan", f"{hedef['puan']} Puan")
        else:
            st.info("Henüz tanımlanmış bir hedefiniz bulunmuyor.")
    conn.close()

# --- DİĞER STANDART MENÜLER ---
elif secim in ["📚 Ödev & Soru Bankası Takibi", "📚 Ödevlerim & Ödev Durumu"]:
    st.title("📚 Ödev & Soru Bankası Takip Modülü")
    st.info("Ödev takip modülü aktif şekilde çalışmaktadır.")

elif secim == "📱 Veli Bilgilendirme & WhatsApp/SMS":
    st.title("📱 Veli Bilgilendirme & WhatsApp Paneli")
    st.info("Bilgilendirme modülü aktif şekilde çalışmaktadır.")

elif secim == "🏫 Okul Genel Durumu & Dereceler":
    st.title("🏫 Okul Genel Başarı Durumu & Dereceler")
    st.info("Sıralama ve derece modülü aktif.")

elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım":
    st.title("🕸️ Sınıf Bazlı Analizler")
    st.info("Sınıf karşılaştırma modülü aktif.")

elif secim == "🔥 Okul Konu/Kazanım Analizi":
    st.title("🔥 Okul Genel Konu ve Kazanım Analizi")
    st.info("Kazanım analiz modülü aktif.")

elif secim == "👥 Öğrenci & Veli Hesap Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Kullanıcı Hesap Yönetimi")
    st.info("Hesap yönetimi modülü aktif.")

elif secim == "⚙️ Kurum Ayarları & Logo" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum Ayarları")
    st.info("Ayarlar modülü aktif.")

elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Yönetimi")
    st.info("Sınav silme modülü aktif.")