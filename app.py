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

    cursor.execute("PRAGMA table_info(sinavlar)")
    s_cols = [c[1] for c in cursor.fetchall()]
    if 'sinav_turu' not in s_cols:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN sinav_turu TEXT DEFAULT 'TYT'")
    if 'yayin_evi' not in s_cols:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN yayin_evi TEXT")
    
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
        
        ayt_say_puan REAL DEFAULT 0,
        ayt_ea_puan REAL DEFAULT 0,
        ayt_soz_puan REAL DEFAULT 0,
        
        FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id) ON DELETE CASCADE
    )''')

    cursor.execute("PRAGMA table_info(ogrenci_sonuclari)")
    os_cols = [c[1] for c in cursor.fetchall()]
    ayt_fields = {
        'ayt_mat_net': 'REAL DEFAULT 0', 'ayt_fizik_net': 'REAL DEFAULT 0',
        'ayt_kimya_net': 'REAL DEFAULT 0', 'ayt_biyo_net': 'REAL DEFAULT 0',
        'ayt_edebiyat_net': 'REAL DEFAULT 0', 'ayt_tarih1_net': 'REAL DEFAULT 0',
        'ayt_cogr1_net': 'REAL DEFAULT 0', 'ayt_tarih2_net': 'REAL DEFAULT 0',
        'ayt_cogr2_net': 'REAL DEFAULT 0', 'ayt_felsefe_net': 'REAL DEFAULT 0',
        'ayt_din_net': 'REAL DEFAULT 0', 'ayt_toplam_net': 'REAL DEFAULT 0',
        'ayt_say_puan': 'REAL DEFAULT 0', 'ayt_ea_puan': 'REAL DEFAULT 0',
        'ayt_soz_puan': 'REAL DEFAULT 0'
    }
    for field, field_type in ayt_fields.items():
        if field not in os_cols:
            cursor.execute(f"ALTER TABLE ogrenci_sonuclari ADD COLUMN {field} {field_type}")
    
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
        sinif TEXT,
        ders TEXT,
        konu_kaynak TEXT,
        son_tarih DATE,
        eklenme_tarihi DATE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odev_takip (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        odev_id INTEGER,
        ogrenci_adi_norm TEXT,
        durum TEXT DEFAULT 'Bekliyor',
        aciklama TEXT,
        FOREIGN KEY (odev_id) REFERENCES odevler(odev_id) ON DELETE CASCADE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        ogrenci_adi_norm TEXT PRIMARY KEY,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL,
        alan_tercihi TEXT DEFAULT 'SAY'
    )''')

    cursor.execute("PRAGMA table_info(ogrenci_hedefleri)")
    h_cols = [c[1] for c in cursor.fetchall()]
    if 'alan_tercihi' not in h_cols:
        cursor.execute("ALTER TABLE ogrenci_hedefleri ADD COLUMN alan_tercihi TEXT DEFAULT 'SAY'")
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogretmen_notlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT,
        tarih DATE,
        not_metni TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY DEFAULT 1,
        kurum_adi TEXT,
        logo_base64 TEXT
    )''')
    
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

def detect_subject_from_topic(topic_str):
    t = topic_str.lower()
    if any(k in t for k in ['paragraf', 'sozcuk', 'cümle', 'yazim', 'noktalama', 'dil bilgisi', 'edebiyat', 'turkce', 'şiir', 'roman']):
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
        return {'bolum': res[0], 'net': res[1], 'puan': res[2], 'alan': res[3] or 'SAY'}
    return None

def render_student_report(norm_adi, ogr_adi, allow_notes=False):
    conn = sqlite3.connect("sinav_takip.db")
    
    st.header(f"👤 Öğrenci: {ogr_adi}")
    
    hedef = get_ogrenci_hedef(norm_adi)
    if hedef:
        st.info(f"🎯 **Hedef Bölüm:** {hedef['bolum']} | **Alan:** {hedef.get('alan', 'SAY')} | **Hedef Net:** {hedef['net']} | **Hedef Puan:** {hedef['puan']}")
    
    view_type = st.radio("İncelenecek Sınav Türünü Seçin:", ["Tümü", "TYT", "AYT"], horizontal=True)
    
    # DOĞRUDAN VE ESNEK SQL SOROUSU
    df_sonuc = pd.read_sql_query('''
        SELECT s.sinav_id, s.sinav_adi, s.tarih, 
               UPPER(TRIM(COALESCE(s.sinav_turu, 'TYT'))) as sinav_turu,
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
               os.kurum_sirasi
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE os.ogrenci_adi_norm LIKE ?
        ORDER BY s.tarih ASC, s.sinav_id ASC
    ''', conn, params=(f"%{norm_adi}%",))
    
    # ESNEK FİLTRELEME MANTIĞI
    if view_type != "Tümü":
        # Hem sinav_turu kolonunu kontrol et hem de sınav adında arat
        df_filtered = df_sonuc[
            (df_sonuc['sinav_turu'].str.contains(view_type, case=False, na=False)) | 
            (df_sonuc['sinav_adi'].str.contains(view_type, case=False, na=False))
        ].copy()
    else:
        df_filtered = df_sonuc.copy()

    if not df_filtered.empty:
        st.subheader(f"📈 Sınav Net Gelişimi ({view_type})")
        fig, ax = plt.subplots(figsize=(10, 4))
        
        if view_type == "AYT":
            ax.plot(df_filtered['sinav_adi'], df_filtered['ayt_toplam'], marker='s', color='#e53e3e', linewidth=2, label='AYT Toplam Net')
        elif view_type == "TYT":
            ax.plot(df_filtered['sinav_adi'], df_filtered['tyt_toplam'], marker='o', color='#3182ce', linewidth=2, label='TYT Toplam Net')
        else:
            ax.plot(df_filtered['sinav_adi'], df_filtered['tyt_toplam'], marker='o', color='#3182ce', linewidth=2, label='TYT Net')
            ax.plot(df_filtered['sinav_adi'], df_filtered['ayt_toplam'], marker='s', color='#e53e3e', linewidth=2, label='AYT Net')
            
        if hedef and hedef['net']:
            ax.axhline(y=hedef['net'], color='g', linestyle='--', label=f"Hedef Net ({hedef['net']})")
            
        ax.set_ylabel("Net")
        plt.xticks(rotation=45, ha='right')
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
            df_tum_eksikler['ders'] = df_tum_eksikler.apply(
                lambda r: detect_subject_from_topic(r['konu_kazanim']) if r['ders'] in ['Genel', 'Genel / Diğer', ''] else r['ders'],
                axis=1
            )

        with c_eksik:
            st.subheader("⚠️ Aktif Eksik / Çalışılması Gereken Konular")
            if not df_tum_eksikler.empty:
                df_son_eksik = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]
                if not df_son_eksik.empty:
                    df_eksik_ozet = df_son_eksik.groupby(['ders', 'konu_kazanim']).size().reset_index(name='Son Sınav Tekrarı')
                    df_eksik_ozet.columns = ['Ders', 'Konu / Kazanım', 'Tekrar Sayısı']
                    
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
        st.warning(f"Bu öğrenciye ait {view_type} türünde girilmiş bir sınav sonucu bulunamadı.")
        
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

# --- 1. MENÜ: SINAV YÜKLE & VERİ AKTARIMI ---
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
                
                cursor.execute("INSERT INTO sinavlar (sinav_adi, tarih, yayin_evi, sinav_turu) VALUES (?, ?, ?, ?)", (sinav_adi, str(sinav_tarihi), yayin_evi, sinav_turu))
                sinav_id = cursor.lastrowid
                
                if excel_file.name.endswith('.csv'):
                    df = pd.read_csv(excel_file)
                else:
                    df = pd.read_excel(excel_file)
                
                for _, row in df.iterrows():
                    ogr_adi = str(get_col_val(row, ['ad soyad', 'ogrenci adi', 'ad', 'isim'], default=""))
                    ogr_norm = normalize_name(ogr_adi)
                    sinif = str(get_col_val(row, ['sinif', 'sınıf'], default=""))
                    
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
                            
                            # AKILLI AYT SÜTUN OKUMA
                            get_col_val(row, ['ayt mat net', 'ayt matematik', 'ayt mat', 'mat2 net'], 0),
                            get_col_val(row, ['ayt fizik', 'fizik net', 'fiz net'], 0),
                            get_col_val(row, ['ayt kimya', 'kimya net', 'kim net'], 0),
                            get_col_val(row, ['ayt biyo', 'biyoloji net', 'bio net'], 0),
                            get_col_val(row, ['ayt edebiyat', 'edebiyat net', 'edb net'], 0),
                            get_col_val(row, ['ayt tarih1', 'tarih 1 net', 'tar1 net'], 0),
                            get_col_val(row, ['ayt cogr1', 'cografya 1 net', 'cog1 net'], 0),
                            get_col_val(row, ['ayt tarih2', 'tarih 2 net'], 0),
                            get_col_val(row, ['ayt cogr2', 'cografya 2 net'], 0),
                            get_col_val(row, ['ayt felsefe', 'fel net'], 0),
                            get_col_val(row, ['ayt din'], 0),
                            get_col_val(row, ['ayt toplam', 'ayt net', 'ayt top net'], 0),
                            get_col_val(row, ['ayt say puan', 'say puan', 'sayisal puan'], 0),
                            get_col_val(row, ['ayt ea puan', 'ea puan', 'esit agirlik'], 0),
                            get_col_val(row, ['ayt soz puan', 'soz puan'], 0)
                        ))
                
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
                        st.warning("PyPDF kütüphanesi eksik.")

                conn.commit()
                conn.close()
                st.success(f"✅ '{sinav_adi}' verileri başarıyla aktarıldı!")
            except Exception as e:
                st.error(f"Aktarım hatası: {str(e)}")
        else:
            st.warning("Lütfen dosya seçin ve sınav adını girin.")

# --- DİĞER MENÜLER (Karneler, Ödevler, Ayarlar, vb.) ---
elif secim in ["📊 Öğrenci Karneleri & Analiz", "🎓 Gelişim & Analiz Karnem"]:
    st.title("📑 Öğrenci Gelişim Karnesi")
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC", conn)
        if not df_ogrenciler.empty:
            ogr_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
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
                    cursor.execute("INSERT INTO odevler (sinif, ders, konu_kaynak, son_tarih, eklenme_tarihi) VALUES (?, ?, ?, ?, DATE('now'))", (sinif_secim, ders_secim, konu_kaynak, str(son_tarih)))
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
                    edited_df = st.data_editor(df_takip, column_config={"durum": st.column_config.SelectboxColumn("Ödev Durumu", options=["Bekliyor", "Tamamlandı", "Eksik Yapıldı", "Yapılmadı"], required=True)}, disabled=["id", "ogrenci_adi", "sinif"], use_container_width=True)
                    if st.button("💾 Kaydet"):
                        cursor = conn.cursor()
                        for _, row in edited_df.iterrows():
                            cursor.execute("UPDATE odev_takip SET durum = ?, aciklama = ? WHERE id = ?", (row['durum'], row['aciklama'], row['id']))
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
            ogr_dict = dict(zip(df_ogr['ogrenci_adi_norm'], df_ogr['ogrenci_adi']))
            secilen_norm = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            hedef_mevcut = get_ogrenci_hedef(secilen_norm)
            with st.form("hedef_form"):
                hedef_bolum = st.text_input("Hedef Bölüm:", value=hedef_mevcut['bolum'] if hedef_mevcut else "")
                alan_tercihi = st.selectbox("Alan:", ["SAY", "EA", "SÖZ", "DİL"])
                hedef_net = st.number_input("Hedef Net:", value=float(hedef_mevcut['net']) if hedef_mevcut else 75.0)
                hedef_puan = st.number_input("Hedef Puan:", value=float(hedef_mevcut['puan']) if hedef_mevcut else 350.0)
                if st.form_submit_button("🎯 Kaydet"):
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan, alan_tercihi) VALUES (?, ?, ?, ?, ?) ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET hedef_bolum=excluded.hedef_bolum, hedef_net=excluded.hedef_net, hedef_puan=excluded.hedef_puan, alan_tercihi=excluded.alan_tercihi", (secilen_norm, hedef_bolum, hedef_net, hedef_puan, alan_tercihi))
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
        secilen_sinav_id = st.selectbox("Sınav Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0])
        df_derece = pd.read_sql_query("SELECT kurum_sirasi as 'Sıra', ogrenci_adi as 'Öğrenci', sinif as 'Sınıf', toplam_net as 'TYT Toplam', ayt_toplam_net as 'AYT Toplam' FROM ogrenci_sonuclari WHERE sinav_id = ? ORDER BY kurum_sirasi ASC", conn, params=(secilen_sinav_id,))
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
        ogr_dict = dict(zip(df_ogrs['ogrenci_adi_norm'], df_ogrs['ogrenci_adi']))
        ogr_norm = st.selectbox("İlişkilendirilecek Öğrenci:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
    if st.button("➕ Oluştur"):
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, ?, ?, ?, ?)", (k_adi, sifre, rol, ogr_norm, telefon))
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
        cursor.execute("INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) VALUES (1, ?, ?)", (yeni_kurum_adi, b64_str))
        conn.commit()
        st.success("Ayarlar güncellendi.")
    conn.close()

elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT * FROM sinavlar ORDER BY sinav_id DESC", conn)
    if not df_sinavlar.empty:
        st.dataframe(df_sinavlar, use_container_width=True)
        silinecek_id = st.selectbox("Silinecek Sınavı Seçin:", df_sinavlar['sinav_id'].tolist(), format_func=lambda x: f"ID: {x} - {df_sinavlar[df_sinavlar['sinav_id']==x]['sinav_adi'].values[0]}")
        if st.button("🔴 Kalıcı Olarak Sil", type="primary"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (silinecek_id,))
            cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (silinecek_id,))
            conn.commit()
            st.success("Sınav ve bağlı tüm veriler silindi!")
            st.rerun()
    conn.close()