import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re
import os
import base64
import matplotlib.pyplot as plt
import numpy as np
import io
import urllib.parse

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Sınav Takip & Analiz Paneli", page_icon="🎓", layout="wide")

# ---------------------------------------------------------
# ÜST BAŞLIK (HEADER)
# ---------------------------------------------------------
col_logo, col_slogan = st.columns([1, 4], vertical_alignment="center")

with col_logo:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)

with col_slogan:
    st.markdown(
        """
        <h2 style='margin:0; padding:0; color: #1F2937;'>Geleceğin Eğitimi, Bugünün Analizi</h2>
        <p style='margin:0; padding:0; color: #6B7280; font-size: 16px;'>Başarıya Giden Yolda Doğru Takip</p>
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
    
    # Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT,
        sinav_turu TEXT DEFAULT 'TYT' -- 'TYT' veya 'AYT'
    )''')

    # Sütun Var mı Kontrolü (Veritabanı Güncelleme Güvencesi)
    cursor.execute("PRAGMA table_info(sinavlar)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'sinav_turu' not in cols:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN sinav_turu TEXT DEFAULT 'TYT'")

    # Öğrenci Sonuçları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_no TEXT,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        alan TEXT DEFAULT 'SAY', -- 'SAY' veya 'EA'
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

    # Sütun Var mı Kontrolü
    cursor.execute("PRAGMA table_info(ogrenci_sonuclari)")
    cols = [col[1] for col in cursor.fetchall()]
    for new_col, col_type in [('alan', 'TEXT'), ('fizik_net', 'REAL'), ('kimya_net', 'REAL'), 
                              ('biyoloji_net', 'REAL'), ('edebiyat_net', 'REAL'), 
                              ('tarih1_net', 'REAL'), ('cografya1_net', 'REAL')]:
        if new_col not in cols:
            cursor.execute(f"ALTER TABLE ogrenci_sonuclari ADD COLUMN {new_col} {col_type} DEFAULT 0")

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

    # Kurum Bilgileri
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kurum_adi TEXT,
        logo_base64 TEXT
    )''')

    # Kullanıcılar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE,
        sifre TEXT,
        rol TEXT,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )''')

    # Öğrenci Hedefleri Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT UNIQUE,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL
    )''')

    # Varsayılan Hesaplar
    cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES ('admin', 'admin123', 'admin', NULL, '')")

    cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = 'ogretmen'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES ('ogretmen', 'ogretmen123', 'ogretmen', NULL, '')")

    conn.commit()
    conn.close()

init_db()

# --- KURUM BİLGİLERİ ---
def get_kurum_bilgileri():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kurum_adi, logo_base64 FROM kurum_ayarlari WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return "NAZİF TOKGÖZ BAŞARI KOLEJİ", None

# --- DİNAMİK EKSİK KONU SORGUSU ---
def get_ogrenci_eksik_durumu(conn, ogrenci_norm_adi):
    cursor = conn.cursor()
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

# --- HEDEF GETİRME ---
def get_ogrenci_hedef(ogrenci_norm_adi):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT hedef_bolum, hedef_net, hedef_puan FROM ogrenci_hedefleri WHERE ogrenci_adi_norm = ?", (ogrenci_norm_adi,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"bolum": row[0], "net": row[1], "puan": row[2]}
    return None

# --- AKILLI ÇALIŞMA PROGRAMI JENERATÖRÜ ---
def generate_ai_study_plan(aktif_eksikler):
    if not aktif_eksikler:
        return {
            "mesaj": "🎉 Harika durumdasın! Aktif eksik konun bulunmuyor. Mevcut netlerini korumak için Genel Deneme ve Soru Bankası tekrarı yapmalısın.",
            "program": []
        }
    
    sorted_eksikler = sorted(aktif_eksikler, key=lambda x: x[1], reverse=True)
    plan = []
    for idx, (konu, tekrar) in enumerate(sorted_eksikler[:4]):
        if tekrar >= 2:
            oncelik = "🔴 YÜKSEK ÖNCELİK (Kritik Eksik)"
            hedef_soru = 120
            tavsiye = "Konu anlatımını sıfırdan dinle + 3 farklı kaynaktan soru çöz."
        else:
            oncelik = "🟡 ORTA ÖNCELİK (Yeni Eksik)"
            hedef_soru = 75
            tavsiye = "Hızlı formül/özet tekrarı + Soru bankasından test çöz."
            
        plan.append({
            "konu": konu, "tekrar": tekrar, "oncelik": oncelik,
            "hedef_soru": hedef_soru, "tavsiye": tavsiye
        })
    return {"mesaj": "", "program": plan}

# --- ÖĞRENCİ KARNE BİLEŞENİ ---
def render_student_report(secilen_norm, secilen_ogr_adi, allow_notes=True):
    conn = sqlite3.connect("sinav_takip.db")
    query = '''
    SELECT s.sinav_adi, s.tarih, s.sinav_turu, os.alan, os.tyt_puan, os.kurum_sirasi, 
           os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.sinif,
           os.fizik_net, os.kimya_net, os.biyoloji_net, os.edebiyat_net, os.tarih1_net, os.cografya1_net
    FROM ogrenci_sonuclari os
    JOIN sinavlar s ON os.sinav_id = s.sinav_id
    WHERE os.ogrenci_adi_norm = ?
    ORDER BY s.tarih ASC
    '''
    df_ogr = pd.read_sql_query(query, conn, params=(secilen_norm,))

    if not df_ogr.empty:
        last_row = df_ogr.iloc[-1]
        ogrenci_alan = last_row.get('alan', 'SAY')
        
        st.markdown(f"### 📋 **{secilen_ogr_adi}** Karnesi (`Alan: {ogrenci_alan}`)")
        
        hedef_info = get_ogrenci_hedef(secilen_norm)
        if hedef_info and hedef_info['net'] > 0:
            net_fark = last_row['toplam_net'] - hedef_info['net']
            st.info(f"🎯 **Hedeflenen Bölüm:** {hedef_info['bolum']} | **Hedef Net:** {hedef_info['net']} Net")
            c_h1, c_h2, c_h3 = st.columns(3)
            c_h1.metric("Son Sınav Neti", f"{last_row['toplam_net']:.2f}")
            c_h2.metric("Hedef Net", f"{hedef_info['net']:.2f}")
            c_h3.metric("Hedefe Kalan / Net Açığı", f"{net_fark:+.2f}", delta=f"{net_fark:.2f}")
            st.markdown("---")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Son Sınav Puanı", f"{last_row['tyt_puan']:.2f}")
        col2.metric("Kurum Sırası", f"{int(last_row['kurum_sirasi'])}")
        col3.metric("Son Toplam Net", f"{last_row['toplam_net']:.2f}")
        col4.metric("Sınıfı", f"{last_row['sinif']}")

        st.markdown("---")
        
        c1, c2 = st.columns([1.1, 0.9])
        
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#2b5797', linewidth=2.5, label="Toplam Net")
        for i, txt in enumerate(df_ogr['toplam_net']):
            ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+1), ha='center', fontweight='bold')
        ax.set_ylabel("Net")
        ax.grid(True, linestyle='--', alpha=0.5)
        plt.xticks(rotation=15)

        with c1:
            st.subheader("📈 Net Gelişim Grafiği")
            st.pyplot(fig)

        with c2:
            aktif_eksikler, tamamlanan_konular = get_ogrenci_eksik_durumu(conn, secilen_norm)
            st.subheader("⚠️ Acil Müdahale Gereken Konular")
            if aktif_eksikler:
                for konu, tekrar in aktif_eksikler:
                    st.error(f"📌 **{konu}** ({tekrar} Sınavda Yanlış)")
            else:
                st.success("🎉 Aktif eksik konu bulunmuyor!")

            st.subheader("🎉 Başarıyla Halledilen Konular")
            if tamamlanan_konular:
                for konu in tamamlanan_konular:
                    st.success(f"✅ **{konu}** (Son sınavda başarıyla çözüldü)")

        st.markdown("---")
        st.subheader("📋 Sınav Geçmiş Tablosu")
        
        # Alan bazlı sütun gösterimi
        if ogrenci_alan == 'SAY':
            gosterilecek_sutunlar = ['sinav_adi', 'tarih', 'matematik_net', 'fizik_net', 'kimya_net', 'biyoloji_net', 'toplam_net', 'tyt_puan']
        else: # EA
            gosterilecek_sutunlar = ['sinav_adi', 'tarih', 'matematik_net', 'edebiyat_net', 'tarih1_net', 'cografya1_net', 'toplam_net', 'tyt_puan']
            
        st.dataframe(df_ogr[gosterilecek_sutunlar], use_container_width=True)
    else:
        st.warning("Bu öğrenciye ait herhangi bir sınav verisi bulunamadı.")
    conn.close()

# --- OTURUM YÖNETİMİ ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['role'] = None
    st.session_state['user_info'] = None

def login_screen():
    st.markdown("<h2 style='text-align: center;'>🏛️ Sınav Takip & Analiz Portalı Girişi</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
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
                    st.success("Giriş başarılı!")
                    st.rerun()
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")

if not st.session_state['logged_in']:
    login_screen()
    st.stop()

# --- YAN MENÜ ---
role_labels = {
    'admin': '👑 Yönetici (Admin)',
    'ogretmen': '👨‍🏫 Öğretmen',
    'ogrenci': '🎓 Öğrenci',
    'veli': '👨‍👩‍👦 Veli'
}

st.sidebar.markdown(f"### 👤 Kullanıcı: **{st.session_state['user_info']['username'].upper()}**")
st.sidebar.markdown(f"🔑 Rol: **{role_labels.get(st.session_state['role'], 'Kullanıcı')}**")

if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state['logged_in'] = False
    st.session_state['role'] = None
    st.session_state['user_info'] = None
    st.rerun()

st.sidebar.markdown("---")

# --- ROL BAZLI MENÜ ---
if st.session_state['role'] == 'admin':
    menu_options = [
        "📤 Yeni Sınav Yükle", 
        "📊 Öğrenci Karneleri & Analiz"
    ]
elif st.session_state['role'] == 'ogretmen':
    menu_options = [
        "📊 Öğrenci Karneleri & Analiz"
    ]
else:
    menu_options = ["🎓 Gelişim & Analiz Karnem"]

secim = st.sidebar.radio("Sistem Menüsü:", menu_options)

# --- 1. MENÜ: YENİ SINAV YÜKLE ---
if secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: 345 AYT Genel - Mart 2026")
    with col2:
        sinav_tarihi = st.date_input("Sınav Tarihi")
    with col3:
        sinav_turu = st.selectbox("Sınav Türü", ["TYT", "AYT (SAY)", "AYT (EA)"])

    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])

    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if sinav_adi and excel_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()

                cursor.execute("INSERT OR IGNORE INTO sinavlar (sinav_adi, tarih, sinav_turu) VALUES (?, ?, ?)", (sinav_adi, str(sinav_tarihi), sinav_turu))
                cursor.execute("SELECT sinav_id FROM sinavlar WHERE sinav_adi = ?", (sinav_adi,))
                sinav_id = cursor.fetchone()[0]

                df_raw = pd.read_excel(excel_file)
                headers = df_raw.iloc[7].values
                df = df_raw.iloc[8:].copy()
                df.columns = headers

                for _, row in df.iterrows():
                    raw_name = str(row.get('Öğrenci', '')).strip()
                    if pd.isna(raw_name) or raw_name in ['nan', 'None', '']:
                        continue
                    norm_name = tr_normalize(raw_name)

                    # TYT / AYT Ortak ve Esnek Değer Okuma
                    if "AYT (SAY)" in sinav_turu:
                        puan = float(row.get('YKS-SAY', 0)) if pd.notna(row.get('YKS-SAY', 0)) else 0.0
                        sira = int(row.get('YKS-SAY K.B.', 0)) if pd.notna(row.get('YKS-SAY K.B.', 0)) else 0
                        mat = float(row.get('Mat 05.N', 0)) if pd.notna(row.get('Mat 05.N', 0)) else 0.0
                        fizik = float(row.get('Fiz 05.N', 0)) if pd.notna(row.get('Fiz 05.N', 0)) else 0.0
                        kimya = float(row.get('Kim 05.N', 0)) if pd.notna(row.get('Kim 05.N', 0)) else 0.0
                        biyoloji = float(row.get('Biy 05.N', 0)) if pd.notna(row.get('Biy 05.N', 0)) else 0.0
                        fen = fizik + kimya + biyoloji
                        toplam = mat + fen
                        alan = 'SAY'
                        edebiyat = tarih1 = cografya1 = turkce = sosyal = 0.0

                    elif "AYT (EA)" in sinav_turu:
                        puan = float(row.get('YKS-EA', row.get('YKS-SAY', 0))) if pd.notna(row.get('YKS-EA', 0)) else 0.0
                        sira = int(row.get('YKS-EA K.B.', 0)) if pd.notna(row.get('YKS-EA K.B.', 0)) else 0
                        mat = float(row.get('Mat 05.N', 0)) if pd.notna(row.get('Mat 05.N', 0)) else 0.0
                        edebiyat = float(row.get('Tür 05.N (1)', 0)) if pd.notna(row.get('Tür 05.N (1)', 0)) else 0.0
                        tarih1 = float(row.get('Tar 05.N', 0)) if pd.notna(row.get('Tar 05.N', 0)) else 0.0
                        cografya1 = float(row.get('Coğ 05.N', 0)) if pd.notna(row.get('Coğ 05.N', 0)) else 0.0
                        toplam = mat + edebiyat + tarih1 + cografya1
                        alan = 'EA'
                        fizik = kimya = biyoloji = turkce = sosyal = fen = 0.0

                    else: # TYT
                        puan = float(row.get('YKS TYT', 0)) if pd.notna(row.get('YKS TYT', 0)) else 0.0
                        sira = int(row.get('YKS TYT K.B.', 0)) if pd.notna(row.get('YKS TYT K.B.', 0)) else 0
                        turkce = float(row.get('Tür 05.N', 0)) if pd.notna(row.get('Tür 05.N', 0)) else 0.0
                        sosyal = float(row.get('Sos 05.N', 0)) if pd.notna(row.get('Sos 05.N', 0)) else 0.0
                        mat = float(row.get('Tem 05.N', 0)) if pd.notna(row.get('Tem 05.N', 0)) else 0.0
                        fen = float(row.get('Fen 05.N', 0)) if pd.notna(row.get('Fen 05.N', 0)) else 0.0
                        toplam = float(row.get('TYT 05.N', turkce+sosyal+mat+fen)) if pd.notna(row.get('TYT 05.N', 0)) else 0.0
                        alan = 'TYT'
                        fizik = kimya = biyoloji = edebiyat = tarih1 = cografya1 = 0.0

                    cursor.execute('''
                    INSERT INTO ogrenci_sonuclari 
                    (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, alan, tyt_puan, kurum_sirasi, 
                     turkce_net, sosyal_net, matematik_net, fen_net, toplam_net, fizik_net, kimya_net, biyoloji_net, edebiyat_net, tarih1_net, cografya1_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (sinav_id, str(row.get('Numara', '')), raw_name, norm_name, str(row.get('Grup', '')), alan,
                          puan, sira, turkce, sosyal, mat, fen, toplam, fizik, kimya, biyoloji, edebiyat, tarih1, cografya1))

                # PDF İşleme (Varsa)
                if pdf_file:
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
                                if "ÜÇDÖRTBES" in konu_temiz or len(konu_temiz) < 2:
                                    continue
                                
                                cursor.execute('''
                                INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ''', (sinav_id, pdf_name, pdf_norm_name, "Genel", konu_temiz, sorular))

                conn.commit()
                conn.close()
                st.success(f"🎉 **{sinav_adi}** başarıyla veritabanına kaydedildi!")
            except Exception as e:
                st.error(f"Bir hata oluştu: {e}")
        else:
            st.warning("Lütfen Sınav Adı ve Excel dosyasını seçiniz.")

# --- 2. MENÜ: ÖĞRENCİ KARNELERİ ---
elif secim in ["📊 Öğrenci Karneleri & Analiz", "🎓 Gelişim & Analiz Karnem"]:
    conn = sqlite3.connect("sinav_takip.db")
    df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
    conn.close()
    
    if not df_ogrenciler.empty:
        ogrenci_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
        secilen_norm = st.selectbox("Öğrenci Seçiniz:", list(ogrenci_dict.keys()), format_func=lambda x: ogrenci_dict[x])
        render_student_report(secilen_norm, ogrenci_dict[secilen_norm])
    else:
        st.info("Sistemde henüz kayıtlı öğrenci verisi bulunmuyor.")