import streamlit as st
import pandas as pd
import sqlite3
import pypdf
import re
import os
import matplotlib.pyplot as plt

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Sınav Takip & Analiz Paneli", page_icon="🎓", layout="wide")

# ---------------------------------------------------------
# ÜST BAŞLIK (HEADER) & LOGO
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

# --- VERİTABANI OLUŞTURMA & OTOMATİK GÜNCELLEME ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    # 1. Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT
    )''')

    # 2. Öğrenci Sonuçları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_no TEXT,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        tyt_puan REAL DEFAULT 0,
        kurum_sirasi INTEGER DEFAULT 0,
        turkce_net REAL DEFAULT 0,
        sosyal_net REAL DEFAULT 0,
        matematik_net REAL DEFAULT 0,
        fen_net REAL DEFAULT 0,
        toplam_net REAL DEFAULT 0,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )''')

    # 3. Öğrenci Eksikleri Tablosu
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

    # 4. Kurum Ayarları Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kurum_adi TEXT,
        logo_base64 TEXT
    )''')

    # 5. Kullanıcılar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE,
        sifre TEXT,
        rol TEXT,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )''')

    # 6. Öğrenci Hedefleri Tablosu
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

    cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = 'ogretmen'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol) VALUES ('ogretmen', 'ogretmen123', 'ogretmen')")

    conn.commit()
    conn.close()

init_db()

# --- YARDIMCI SORGULAR & YAPAY ZEKA MODELİ ---
def get_ogrenci_hedef(ogrenci_norm_adi):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT hedef_bolum, hedef_net, hedef_puan FROM ogrenci_hedefleri WHERE ogrenci_adi_norm = ?", (ogrenci_norm_adi,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"bolum": row[0], "net": row[1], "puan": row[2]}
    return None

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

def generate_ai_study_plan(aktif_eksikler):
    if not aktif_eksikler:
        return {
            "mesaj": "🎉 Harika durumdasın! Aktif eksik konun bulunmuyor. Mevcut netlerini korumak için Genel Deneme çözebilirsin.",
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
def render_student_report(secilen_norm, secilen_ogr_adi):
    conn = sqlite3.connect("sinav_takip.db")
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
        
        st.markdown(f"### 📋 **{secilen_ogr_adi}** Karnesi")
        
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
            ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+0.5), ha='center', fontweight='bold')
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
        st.subheader("🤖 Akıllı Çalışma Programı Tavsiyesi")
        ai_plan = generate_ai_study_plan(aktif_eksikler)
        if ai_plan["mesaj"]:
            st.info(ai_plan["mesaj"])
        else:
            for item in ai_plan["program"]:
                with st.expander(f"{item['oncelik']} - {item['konu']}"):
                    st.write(f"• **Haftalık Soru Hedefi:** {item['hedef_soru']} Soru")
                    st.write(f"• **Çalışma Tavsiyesi:** {item['tavsiye']}")

        st.markdown("---")
        st.subheader("📋 Sınav Geçmiş Tablosu")
        gosterilecek_sutunlar = ['sinav_adi', 'tarih', 'turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'toplam_net', 'tyt_puan']
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

# --- YAN MENÜ VE ROL TANIMLARI ---
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

# --- TÜM MENÜ SEÇENEKLERİ ---
if st.session_state['role'] == 'admin':
    menu_options = [
        "📊 Genel Bakış",
        "📤 Yeni Sınav Yükle", 
        "📑 Öğrenci Karneleri & Analiz",
        "🗂️ Sınav Yönetimi",
        "👥 Kullanıcı Yönetimi",
        "🎯 Hedef Yönetimi",
        "⚙️ Kurum Ayarları"
    ]
elif st.session_state['role'] == 'ogretmen':
    menu_options = [
        "📊 Genel Bakış",
        "📑 Öğrenci Karneleri & Analiz",
        "🎯 Hedef Yönetimi"
    ]
else:
    menu_options = ["🎓 Gelişim & Analiz Karnem"]

secim = st.sidebar.radio("Sistem Menüsü:", menu_options)

# ---------------------------------------------------------
# MENÜ İÇERİKLERİ
# ---------------------------------------------------------

# --- 1. GENEL BAKIŞ ---
if secim == "📊 Genel Bakış":
    st.title("📊 Genel Bakış ve Kurum İstatistikleri")
    conn = sqlite3.connect("sinav_takip.db")
    
    col1, col2, col3 = st.columns(3)
    s_count = pd.read_sql_query("SELECT COUNT(*) as c FROM sinavlar", conn).iloc[0]['c']
    o_count = pd.read_sql_query("SELECT COUNT(DISTINCT ogrenci_adi_norm) as c FROM ogrenci_sonuclari", conn).iloc[0]['c']
    u_count = pd.read_sql_query("SELECT COUNT(*) as c FROM kullanicilar", conn).iloc[0]['c']
    
    col1.metric("Kayıtlı Sınav Sayısı", s_count)
    col2.metric("Sistemdeki Öğrenci Sayısı", o_count)
    col3.metric("Kayıtlı Kullanıcı Sayısı", u_count)
    
    st.markdown("---")
    st.subheader("📌 Son Yüklenen Sınavlar")
    df_last_exams = pd.read_sql_query("SELECT sinav_adi, tarih FROM sinavlar ORDER BY tarih DESC LIMIT 5", conn)
    st.dataframe(df_last_exams, use_container_width=True)
    conn.close()

# --- 2. YENİ SINAV YÜKLE ---
elif secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: Özdebir TYT 1")
    with col2:
        sinav_tarihi = st.date_input("Sınav Tarihi")

    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])

    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if sinav_adi and excel_file:
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
                    raw_name = str(row.get('Öğrenci', '')).strip()
                    if pd.isna(raw_name) or raw_name in ['nan', 'None', '']:
                        continue
                    norm_name = tr_normalize(raw_name)

                    puan = float(row.get('YKS TYT', 0)) if pd.notna(row.get('YKS TYT', 0)) else 0.0
                    sira = int(row.get('YKS TYT K.B.', 0)) if pd.notna(row.get('YKS TYT K.B.', 0)) else 0
                    turkce = float(row.get('Tür 05.N', 0)) if pd.notna(row.get('Tür 05.N', 0)) else 0.0
                    sosyal = float(row.get('Sos 05.N', 0)) if pd.notna(row.get('Sos 05.N', 0)) else 0.0
                    mat = float(row.get('Tem 05.N', 0)) if pd.notna(row.get('Tem 05.N', 0)) else 0.0
                    fen = float(row.get('Fen 05.N', 0)) if pd.notna(row.get('Fen 05.N', 0)) else 0.0
                    toplam = float(row.get('TYT 05.N', turkce+sosyal+mat+fen)) if pd.notna(row.get('TYT 05.N', 0)) else 0.0

                    cursor.execute('''
                    INSERT INTO ogrenci_sonuclari 
                    (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, tyt_puan, kurum_sirasi, 
                     turkce_net, sosyal_net, matematik_net, fen_net, toplam_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (sinav_id, str(row.get('Numara', '')), raw_name, norm_name, str(row.get('Grup', '')),
                          puan, sira, turkce, sosyal, mat, fen, toplam))

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
                st.success(f"🎉 **{sinav_adi}** başarıyla yüklendi!")
            except Exception as e:
                st.error(f"Bir hata oluştu: {e}")
        else:
            st.warning("Lütfen Sınav Adı ve Excel dosyasını seçiniz.")

# --- 3. ÖĞRENCİ KARNELERİ ---
elif secim in ["📑 Öğrenci Karneleri & Analiz", "🎓 Gelişim & Analiz Karnem"]:
    conn = sqlite3.connect("sinav_takip.db")
    
    if st.session_state['role'] in ['admin', 'ogretmen']:
        df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
        conn.close()
        if not df_ogrenciler.empty:
            ogrenci_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
            secilen_norm = st.selectbox("Öğrenci Seçiniz:", list(ogrenci_dict.keys()), format_func=lambda x: ogrenci_dict[x])
            render_student_report(secilen_norm, ogrenci_dict[secilen_norm])
        else:
            st.info("Sistemde henüz kayıtlı öğrenci verisi bulunmuyor.")
    else:
        # Öğrenci veya Veli Girişi
        secilen_norm = st.session_state['user_info']['norm_adi']
        conn.close()
        if secilen_norm:
            render_student_report(secilen_norm, st.session_state['user_info']['username'])
        else:
            st.warning("Hesabınıza tanımlı öğrenci eşleşmesi bulunamadı.")

# --- 4. SINAV YÖNETİMİ ---
elif secim == "🗂️ Sınav Yönetimi" and st.session_state['role'] == 'admin':
    st.title("🗂️ Sınav Yönetimi ve Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT sinav_id, sinav_adi, tarih FROM sinavlar ORDER BY tarih DESC", conn)
    
    if not df_sinavlar.empty:
        st.dataframe(df_sinavlar, use_container_width=True)
        sinav_to_delete = st.selectbox("Silinecek Sınavı Seçin:", df_sinavlar['sinav_adi'].tolist())
        
        if st.button("🗑️ Seçilen Sınavı Veritabanından Sil", type="primary"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sinavlar WHERE sinav_adi = ?", (sinav_to_delete,))
            conn.commit()
            st.success(f"'{sinav_to_delete}' başarıyla silindi.")
            st.rerun()
    else:
        st.info("Kayıtlı sınav bulunmuyor.")
    conn.close()

# --- 5. KULLANICI YÖNETİMİ ---
elif secim == "👥 Kullanıcı Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Kullanıcı Hesap Yönetimi")
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    st.subheader("➕ Yeni Kullanıcı Ekle")
    col_u1, col_u2, col_u3 = st.columns(3)
    with col_u1:
        new_username = st.text_input("Kullanıcı Adı")
    with col_u2:
        new_password = st.text_input("Şifre")
    with col_u3:
        new_role = st.selectbox("Rol", ["admin", "ogretmen", "ogrenci", "veli"])
        
    if st.button("Kullanıcı Oluştur"):
        if new_username and new_password:
            try:
                cursor.execute("INSERT INTO kullanicilar (kullanici_adi, sifre, rol) VALUES (?, ?, ?)", 
                               (new_username.strip(), new_password.strip(), new_role))
                conn.commit()
                st.success("Kullanıcı başarıyla eklendi!")
                st.rerun()
            except Exception as e:
                st.error("Bu kullanıcı adı zaten mevcut!")
        else:
            st.warning("Eksik alanları doldurun.")
            
    st.markdown("---")
    st.subheader("📋 Kayıtlı Kullanıcılar")
    df_users = pd.read_sql_query("SELECT id, kullanici_adi, rol, telefon FROM kullanicilar", conn)
    st.dataframe(df_users, use_container_width=True)
    conn.close()

# --- 6. HEDEF YÖNETİMİ ---
elif secim == "🎯 Hedef Yönetimi":
    st.title("🎯 Öğrenci Hedef Belirleme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    df_ogr = pd.read_sql_query("SELECT DISTINCT ogrenci_adi_norm, ogrenci_adi FROM ogrenci_sonuclari", conn)
    
    if not df_ogr.empty:
        ogr_map = dict(zip(df_ogr['ogrenci_adi_norm'], df_ogr['ogrenci_adi']))
        secilen_ogr = st.selectbox("Hedef Girilecek Öğrenci:", list(ogr_map.keys()), format_func=lambda x: ogr_map[x])
        
        c1, c2, c3 = st.columns(3)
        with c1:
            h_bolum = st.text_input("Hedeflenen Bölüm / Üniversite", placeholder="Örn: İTÜ Bilgisayar Müh.")
        with c2:
            h_net = st.number_input("Hedef Toplam Net", min_value=0.0, max_value=500.0, step=0.5)
        with c3:
            h_puan = st.number_input("Hedef Puan", min_value=0.0, max_value=500.0, step=1.0)
            
        if st.button("Hedef Kaydet / Güncelle", type="primary"):
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET
                    hedef_bolum=excluded.hedef_bolum,
                    hedef_net=excluded.hedef_net,
                    hedef_puan=excluded.hedef_puan
            ''', (secilen_ogr, h_bolum, h_net, h_puan))
            conn.commit()
            st.success(f"{ogr_map[secilen_ogr]} için hedef başarıyla kaydedildi!")
    else:
        st.info("Kayıtlı öğrenci verisi bulunmuyor.")
    conn.close()

# --- 7. KURUM AYARLARI ---
elif secim == "⚙️ Kurum Ayarları" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum Ayarları ve Görsel Yönetimi")
    st.info("Bu ekrandan kurum adı ve logo yükleme işlemlerini gerçekleştirebilirsiniz.")
    
    k_adi = st.text_input("Kurum / Okul Adı", value="NAZİF TOKGÖZ BAŞARI KOLEJİ")
    if st.button("Ayarları Kaydet"):
        st.success("Kurum ayarları güncellendi!")