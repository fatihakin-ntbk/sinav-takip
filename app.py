import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re
import os
import matplotlib.pyplot as plt
import urllib.parse

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Sınav & Ödev Takip Portalı", page_icon="🎓", layout="wide")

# --- ÜST BAŞLIK (HEADER) & LOGO ---
col_logo, col_slogan = st.columns([1, 4], vertical_alignment="center")

with col_logo:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)

with col_slogan:
    st.markdown(
        """
        <h2 style='margin:0; padding:0; color: #1F2937;'>Geleceğin Eğitimi, Bugünün Analizi</h2>
        <p style='margin:0; padding:0; color: #6B7280; font-size: 16px;'>Nazif Tokgöz Başarı Koleji Sınav & Ödev Takip Sistemi</p>
        """, 
        unsafe_allow_html=True
    )

st.divider()

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
    
    # 1. Sınavlar
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT,
        sinav_turu TEXT DEFAULT 'TYT'
    )''')

    # 2. Öğrenci Sonuçları
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_no TEXT,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        alan TEXT DEFAULT 'TYT',
        tyt_puan REAL DEFAULT 0,
        kurum_sirasi INTEGER DEFAULT 0,
        turkce_net REAL DEFAULT 0,
        sosyal_net REAL DEFAULT 0,
        matematik_net REAL DEFAULT 0,
        fen_net REAL DEFAULT 0,
        toplam_net REAL DEFAULT 0,
        fizik_net REAL DEFAULT 0,
        kimya_net REAL DEFAULT 0,
        biyoloji_net REAL DEFAULT 0,
        edebiyat_net REAL DEFAULT 0,
        tarih1_net REAL DEFAULT 0,
        cografya1_net REAL DEFAULT 0,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )''')

    # 3. Öğrenci Eksikleri
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

    # 4. Ödev Takip Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT,
        ders TEXT,
        odev_konusu TEXT,
        verilis_tarihi TEXT,
        teslim_tarihi TEXT,
        durum TEXT DEFAULT 'Bekliyor',
        aciklama TEXT
    )''')

    # 5. Kullanıcılar
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE,
        sifre TEXT,
        rol TEXT,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )''')

    # 6. Öğrenci Hedefleri
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT UNIQUE,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL
    )''')

    # Varsayılan Kullanıcılar
    cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol) VALUES ('admin', 'admin123', 'admin')")

    conn.commit()
    conn.close()

init_db()

# --- OTURUM YÖNETİMİ ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['role'] = None
    st.session_state['user_info'] = None

if not st.session_state['logged_in']:
    st.markdown("<h2 style='text-align: center;'>🏛️ Sınav & Ödev Takip Portalı Girişi</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Kullanıcı Adı:")
            password = st.text_input("Şifre:", type="password")
            submit = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)

            if submit:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()
                cursor.execute("SELECT rol, ogrenci_adi_norm, kullanici_adi FROM kullanicilar WHERE kullanici_adi = ? AND sifre = ?", (username.strip(), password.strip()))
                user = cursor.fetchone()
                conn.close()

                if user:
                    st.session_state['logged_in'] = True
                    st.session_state['role'] = user[0] 
                    st.session_state['user_info'] = {'username': user[2], 'norm_adi': user[1]}
                    st.rerun()
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")
    st.stop()

# --- YAN MENÜ ---
role_labels = {'admin': '👑 Yönetici (Admin)', 'ogretmen': '👨‍🏫 Öğretmen', 'ogrenci': '🎓 Öğrenci', 'veli': '👨‍👩‍👦 Veli'}
st.sidebar.markdown(f"🔑 Rol: **{role_labels.get(st.session_state['role'], 'Kullanıcı')}**")

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state['logged_in'] = False
    st.session_state['role'] = None
    st.rerun()

st.sidebar.markdown("---")

# FULL MENÜ SEÇENEKLERİ (ÖDEV VE WHATSAPP EKLENDİ)
if st.session_state['role'] == 'admin':
    menu_options = [
        "📊 Genel Bakış",
        "📤 Yeni Sınav Yükle", 
        "📑 Öğrenci Karneleri & Analiz",
        "📚 Ödev Takip Sistemi",
        "💬 WhatsApp Bildirim Paneli",
        "🗂️ Sınav Yönetimi",
        "👥 Kullanıcı Yönetimi",
        "🎯 Hedef Yönetimi",
        "⚙️ Kurum Ayarları"
    ]
elif st.session_state['role'] == 'ogretmen':
    menu_options = [
        "📊 Genel Bakış",
        "📑 Öğrenci Karneleri & Analiz",
        "📚 Ödev Takip Sistemi",
        "💬 WhatsApp Bildirim Paneli",
        "🎯 Hedef Yönetimi"
    ]
else:
    menu_options = ["🎓 Gelişim & Analiz Karnem", "📚 Ödevlerim"]

secim = st.sidebar.radio("Sistem Menüsü:", menu_options)

# ---------------------------------------------------------
# MENÜ İÇERİKLERİ
# ---------------------------------------------------------

# --- 1. GENEL BAKIŞ ---
if secim == "📊 Genel Bakış":
    st.title("📊 Genel Bakış ve Kurum İstatistikleri")
    conn = sqlite3.connect("sinav_takip.db")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kayıtlı Sınav", pd.read_sql_query("SELECT COUNT(*) as c FROM sinavlar", conn).iloc[0]['c'])
    c2.metric("Öğrenci Sayısı", pd.read_sql_query("SELECT COUNT(DISTINCT ogrenci_adi_norm) as c FROM ogrenci_sonuclari", conn).iloc[0]['c'])
    c3.metric("Aktif Ödevler", pd.read_sql_query("SELECT COUNT(*) as c FROM odevler WHERE durum != 'Tamamlandı'", conn).iloc[0]['c'])
    c4.metric("Kullanıcı Sayısı", pd.read_sql_query("SELECT COUNT(*) as c FROM kullanicilar", conn).iloc[0]['c'])
    conn.close()

# --- 2. ÖDEV TAKİP SİSTEMİ ---
elif secim == "📚 Ödev Takip Sistemi":
    st.title("📚 Ödev Takip ve Kontrol Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    
    tab1, tab2 = st.tabs(["➕ Yeni Ödev Ver", "📋 Ödev Listesi & Durum Güncelle"])
    
    with tab1:
        df_ogr = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
        if not df_ogr.empty:
            ogr_dict = dict(zip(df_ogr['ogrenci_adi_norm'], df_ogr['ogrenci_adi']))
            secilen_ogr = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            
            c1, c2 = st.columns(2)
            ders = c1.selectbox("Ders:", ["Matematik", "Fizik", "Kimya", "Biyoloji", "Türkçe", "Tarih", "Coğrafya", "Felsefe"])
            odev_konusu = c2.text_input("Ödev Konusu / Sayfa Aralığı:")
            
            d1, d2 = st.columns(2)
            v_tarihi = d1.date_input("Veriliş Tarihi")
            t_tarihi = d2.date_input("Teslim Tarihi")
            aciklama = st.text_area("Ödev Açıklaması / Notlar:")
            
            if st.button("🚀 Ödevi Kaydet ve Atan"):
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO odevler (ogrenci_adi_norm, ders, odev_konusu, verilis_tarihi, teslim_tarihi, aciklama)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (secilen_ogr, ders, odev_konusu, str(v_tarihi), str(t_tarihi), aciklama))
                conn.commit()
                st.success("Ödev başarıyla kaydedildi!")
        else:
            st.info("Kayıtlı öğrenci bulunamadı.")
            
    with tab2:
        df_odevler = pd.read_sql_query("SELECT * FROM odevler ORDER BY teslim_tarihi DESC", conn)
        if not df_odevler.empty:
            st.dataframe(df_odevler, use_container_width=True)
            
            st.subheader("✏️ Ödev Durumu Güncelle")
            odev_id = st.selectbox("Ödev ID Seçin:", df_odevler['odev_id'].tolist())
            yeni_durum = st.selectbox("Yeni Durum:", ["Bekliyor", "Tamamlandı", "Eksik Yapıldı", "Yapılmadı"])
            
            if st.button("Durumu Güncelle"):
                cursor = conn.cursor()
                cursor.execute("UPDATE odevler SET durum = ? WHERE odev_id = ?", (yeni_durum, odev_id))
                conn.commit()
                st.success("Ödev durumu güncellendi!")
                st.rerun()
        else:
            st.info("Henüz verilmiş ödev bulunmuyor.")
    conn.close()

# --- 3. WHATSAPP BİLDİRİM PANELİ ---
elif secim == "💬 WhatsApp Bildirim Paneli":
    st.title("💬 WhatsApp Otomatik Bildirim Paneli")
    st.info("Bu ekrandan veli/öğrencilere doğrudan WhatsApp mesajı yönlendirebilirsiniz.")
    
    conn = sqlite3.connect("sinav_takip.db")
    df_users = pd.read_sql_query("SELECT kullanici_adi, telefon, ogrenci_adi_norm FROM kullanicilar WHERE telefon IS NOT NULL AND telefon != ''", conn)
    
    if not df_users.empty:
        secilen_user = st.selectbox("Mesaj Gönderilecek Kişi/Veli:", df_users['kullanici_adi'].tolist())
        user_row = df_users[df_users['kullanici_adi'] == secilen_user].iloc[0]
        tel_no = user_row['telefon']
        
        mesaj_turu = st.radio("Mesaj Şablonu Seçin:", ["Son Sınav Karnesi Bildirimi", "Eksik Ödev Uyarısı", "Özel Mesaj"])
        
        if mesaj_turu == "Son Sınav Karnesi Bildirimi":
            mesaj = f"Sayın Velimiz, öğrencimiz {secilen_user}'in son deneme sınavı sonuçları sistemimize yüklenmiştir. Detaylı karnesini sınav portalından inceleyebilirsiniz."
        elif mesaj_turu == "Eksik Ödev Uyarısı":
            mesaj = f"Sayın Velimiz, öğrencimiz {secilen_user}'in teslim tarihi geçen eksik ödevleri bulunmaktadır. Bilginize."
        else:
            mesaj = st.text_area("Özel Mesajınız:")
            
        encoded_msg = urllib.parse.quote(mesaj)
        whatsapp_url = f"https://wa.me/{tel_no}?text={encoded_msg}"
        
        st.markdown(f'<a href="{whatsapp_url}" target="_blank"><button style="background-color:#25D366; color:white; border:none; padding:10px 20px; font-size:16px; border-radius:5px; cursor:pointer;">📲 WhatsApp ile Gönder</button></a>', unsafe_allow_html=True)
    else:
        st.warning("Telefon numarası kayıtlı kullanıcı bulunamadı. 'Kullanıcı Yönetimi' ekranından telefon numarası ekleyebilirsiniz.")
    conn.close()

# --- 4. ÖĞRENCİ KARNELERİ ---
elif secim == "📑 Öğrenci Karneleri & Analiz":
    st.title("📑 Öğrenci Karneleri ve Analiz")
    conn = sqlite3.connect("sinav_takip.db")
    df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
    if not df_ogrenciler.empty:
        ogrenci_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
        secilen_norm = st.selectbox("Öğrenci Seçiniz:", list(ogrenci_dict.keys()), format_func=lambda x: ogrenci_dict[x])
        
        df_ogr = pd.read_sql_query("SELECT s.sinav_adi, s.tarih, os.toplam_net, os.tyt_puan FROM ogrenci_sonuclari os JOIN sinavlar s ON os.sinav_id = s.sinav_id WHERE os.ogrenci_adi_norm = ?", conn, params=(secilen_norm,))
        st.dataframe(df_ogr, use_container_width=True)
    conn.close()

# --- 5. YENİ SINAV YÜKLE ---
elif secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    c1, c2, c3 = st.columns([2, 1, 1])
    sinav_adi = c1.text_input("Sınav Adı")
    sinav_tarihi = c2.date_input("Sınav Tarihi")
    sinav_turu = c3.selectbox("Sınav Türü", ["TYT", "AYT (SAY)", "AYT (EA)"])
    excel_file = st.file_uploader("Excel Dosyası (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF (.pdf)", type=["pdf"])

# --- OTHER MENUS ---
elif secim == "🗂️ Sınav Yönetimi":
    st.title("🗂️ Sınav Yönetimi")
elif secim == "👥 Kullanıcı Yönetimi":
    st.title("👥 Kullanıcı Yönetimi")
elif secim == "🎯 Hedef Yönetimi":
    st.title("🎯 Hedef Yönetimi")
elif secim == "⚙️ Kurum Ayarları":
    st.title("⚙️ Kurum Ayarları")