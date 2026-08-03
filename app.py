import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import streamlit as st
import io

# PDF Kütüphane Kontrolü
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="Öğrenci Sınav Takip & Analiz Sistemi",
    page_icon="🎓",
    layout="wide"
)

# --- YARDIMCI FONKSİYONLAR ---
def tr_clean(text):
    if not isinstance(text, str):
        return text
    replacements = {'I': 'I', 'ı': 'i', 'İ': 'I', 'Ş': 'S', 'ş': 's', 'Ğ': 'G', 'ğ': 'g', 'Ü': 'U', 'ü': 'u', 'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()

def normalize_name(text):
    if not isinstance(text, str):
        return ""
    text = tr_clean(text).lower()
    return "".join(e for e in text if e.isalnum())

# --- VERİTABANI BAŞLATMA VE OTOMATİK MİGRASYON ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sinavlar (
            sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT UNIQUE,
            tarih TEXT,
            sinav_turu TEXT DEFAULT 'TYT'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_id INTEGER,
            ogrenci_adi TEXT,
            ogrenci_adi_norm TEXT,
            turkce_net REAL DEFAULT 0,
            sosyal_net REAL DEFAULT 0,
            matematik_net REAL DEFAULT 0,
            fen_net REAL DEFAULT 0,
            toplam_net REAL DEFAULT 0,
            tyt_puan REAL DEFAULT 0,
            ayt_mat_net REAL DEFAULT 0,
            ayt_fizik_net REAL DEFAULT 0,
            ayt_kimya_net REAL DEFAULT 0,
            ayt_biyo_net REAL DEFAULT 0,
            ayt_edebiyat_net REAL DEFAULT 0,
            ayt_tarih1_net REAL DEFAULT 0,
            ayt_cogr1_net REAL DEFAULT 0,
            ayt_toplam_net REAL DEFAULT 0,
            ayt_say_puan REAL DEFAULT 0,
            ayt_ea_puan REAL DEFAULT 0,
            kurum_sirasi INTEGER DEFAULT 0,
            FOREIGN KEY(sinav_id) REFERENCES sinavlar(sinav_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ogrenci_eksikleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_id INTEGER,
            ogrenci_adi_norm TEXT,
            ders TEXT,
            konu_kazanim TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hedefler (
            ogrenci_adi_norm TEXT PRIMARY KEY,
            bolum TEXT,
            alan TEXT,
            net REAL,
            puan REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ogretmen_notlari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ogrenci_adi_norm TEXT,
            tarih TEXT,
            not_metni TEXT
        )
    ''')

    # Otomatik Sütun Onarma (Migration)
    cursor.execute("PRAGMA table_info(ogrenci_sonuclari)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    
    req_cols = {
        'ayt_mat_net': 'REAL DEFAULT 0', 'ayt_fizik_net': 'REAL DEFAULT 0',
        'ayt_kimya_net': 'REAL DEFAULT 0', 'ayt_biyo_net': 'REAL DEFAULT 0',
        'ayt_edebiyat_net': 'REAL DEFAULT 0', 'ayt_tarih1_net': 'REAL DEFAULT 0',
        'ayt_cogr1_net': 'REAL DEFAULT 0', 'ayt_toplam_net': 'REAL DEFAULT 0',
        'ayt_say_puan': 'REAL DEFAULT 0', 'ayt_ea_puan': 'REAL DEFAULT 0',
        'kurum_sirasi': 'INTEGER DEFAULT 0', 'tyt_puan': 'REAL DEFAULT 0'
    }
    
    for col, col_type in req_cols.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE ogrenci_sonuclari ADD COLUMN {col} {col_type}")

    cursor.execute("PRAGMA table_info(sinavlar)")
    if 'sinav_turu' not in [row[1] for row in cursor.fetchall()]:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN sinav_turu TEXT DEFAULT 'TYT'")

    conn.commit()
    conn.close()

init_db()

# --- YARDIMCI MOTOR FONKSİYONLAR ---
def get_ogrenci_hedef(norm_adi):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bolum, alan, net, puan FROM hedefler WHERE ogrenci_adi_norm = ?", (norm_adi,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {'bolum': res[0], 'alan': res[1], 'net': res[2], 'puan': res[3]}
    return None

def generate_ai_study_plan(eksik_listesi):
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    plan = {day: [] for day in days}
    if not eksik_listesi:
        return plan
    
    for idx, item in enumerate(eksik_listesi):
        day = days[idx % 7]
        plan[day].append(f"📌 {item['ders']}: {item['konu']}")
    return plan

# --- PDF KARNE OLUŞTURMA FONKSİYONU (TÜRKÇE KARAKTER TEMİZLEME GÜVENLİĞİ İLE) ---
def generate_pdf_report(ogr_adi, hedef, df_sonuc, eksik_listesi, halledilen_listesi, ai_plan, notlar):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def pdf_safe(text):
        if text is None:
            return ""
        return tr_clean(str(text))

    # Başlık
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, pdf_safe(f"SINAV GELISIM KARNESI - {ogr_adi.upper()}"))
    
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 65, "-" * 85)

    y = height - 90

    # Hedef Bilgisi
    if hedef:
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "HEDEF BILGILERI:")
        y -= 15
        p.setFont("Helvetica", 10)
        hedef_str = f"Bolum: {hedef.get('bolum', '-')} | Alan: {hedef.get('alan', '-')} | Hedef Net: {hedef.get('net', '-')} | Hedef Puan: {hedef.get('puan', '-')}"
        p.drawString(60, y, pdf_safe(hedef_str))
        y -= 25

    # Genel Sınav Özeti
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "SINAV OZETI:")
    y -= 15
    p.setFont("Helvetica", 10)
    p.drawString(60, y, pdf_safe(f"Toplam Katilinan Sinav Sayisi: {len(df_sonuc)}"))
    y -= 25

    # Aktif Eksik Konular
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "AKTIF EKSIK / CALISILMASI GEREKEN KONULAR:")
    y -= 15
    p.setFont("Helvetica", 10)
    if eksik_listesi:
        for item in eksik_listesi[:8]:
            ders = pdf_safe(item.get('ders', ''))
            konu = pdf_safe(item.get('konu', ''))
            p.drawString(60, y, f"- {ders}: {konu}")
            y -= 14
    else:
        p.drawString(60, y, pdf_safe("Aktif eksik konu bulunmamaktadir."))
        y -= 14
    
    y -= 10

    # Başarıyla Halledilen Konular
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "BASARIYLA HALLEDILEN KONULAR:")
    y -= 15
    p.setFont("Helvetica", 10)
    if halledilen_listesi:
        for item in halledilen_listesi[:6]:
            ders = pdf_safe(item.get('ders', ''))
            konu = pdf_safe(item.get('konu', ''))
            p.drawString(60, y, f"- {ders}: {konu}")
            y -= 14
    else:
        p.drawString(60, y, pdf_safe("Henuz duzeltilmis konu kaydi yok."))
        y -= 14

    y -= 10

    # Çalışma Programı Özet
    if ai_plan:
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "HAFTALIK CALISMA PROGRAMI ONERISI:")
        y -= 15
        p.setFont("Helvetica", 9)
        for gun, gorevler in ai_plan.items():
            gun_str = pdf_safe(gun)
            if gorevler:
                gorev_str = ", ".join([pdf_safe(g) for g in gorevler])
                p.drawString(60, y, f"{gun_str}: {gorev_str}")
            else:
                p.drawString(60, y, f"{gun_str}: Genel Tekrar / Serbest")
            y -= 12
            if y < 50:
                break

    # Öğretmen Notları
    if notlar and y > 60:
        y -= 10
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, "OGRETMEN NOTLARI:")
        y -= 15
        p.setFont("Helvetica", 9)
        for n in notlar[:3]:
            p.drawString(60, y, f"* {pdf_safe(n)}")
            y -= 12

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.getvalue()

# --- EKRAN SUNUMU VE RAPORLAMA ---
def render_student_report(norm_adi, ogr_adi, allow_notes=False):
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    st.header(f"👤 Öğrenci: {tr_clean(ogr_adi)}")
    
    hedef = get_ogrenci_hedef(norm_adi)
    if hedef:
        st.info(f"🎯 **Hedef Bölüm:** {hedef['bolum']} | **Alan:** {hedef.get('alan', 'SAY')} | **Hedef Net:** {hedef['net']} | **Hedef Puan:** {hedef['puan']}")
    
    view_type = st.radio("İncelenecek Sınav Türünü Seçin:", ["Tümü", "TYT", "AYT"], horizontal=True)

    query = '''
        SELECT s.sinav_id, 
               s.sinav_adi, 
               s.tarih,
               COALESCE(s.sinav_turu, 'TYT') as sinav_turu,
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
               COALESCE(os.kurum_sirasi, 0) as kurum_sirasi
        FROM ogrenci_sonuclari os
        JOIN sinavlar s ON os.sinav_id = s.sinav_id
        WHERE os.ogrenci_adi_norm LIKE ?
        ORDER BY s.tarih ASC, s.sinav_id ASC
    '''
    
    df_sonuc = pd.read_sql_query(query, conn, params=(f"%{norm_adi}%",))
    
    if view_type != "Tümü":
        df_filtered = df_sonuc[
            (df_sonuc['sinav_turu'].str.upper() == view_type) | 
            (df_sonuc['sinav_adi'].str.contains(view_type, case=False, na=False))
        ]
    else:
        df_filtered = df_sonuc.copy()

    eksik_konu_listesi = []
    halledilen_konu_listesi = []

    if not df_filtered.empty:
        st.subheader(f"📈 Sınav Net Gelişimi ({view_type})")
        fig, ax = plt.subplots(figsize=(10, 3.5))
        
        df_tyt = df_filtered[(df_filtered['sinav_turu'] == 'TYT') | (df_filtered['sinav_adi'].str.contains('TYT', case=False, na=False))]
        df_ayt = df_filtered[(df_filtered['sinav_turu'] == 'AYT') | (df_filtered['sinav_adi'].str.contains('AYT', case=False, na=False))]
        
        if view_type in ["Tümü", "TYT"] and not df_tyt.empty:
            ax.plot(df_tyt['sinav_adi'].apply(tr_clean), df_tyt['tyt_toplam'], marker='o', color='#3182ce', linewidth=2, label='TYT Toplam Net')
        if view_type in ["Tümü", "AYT"] and not df_ayt.empty:
            ax.plot(df_ayt['sinav_adi'].apply(tr_clean), df_ayt['ayt_toplam'], marker='s', color='#e53e3e', linewidth=2, label='AYT Toplam Net')
            
        if hedef and hedef['net']:
            ax.axhline(y=hedef['net'], color='g', linestyle='--', label=f"Hedef Net ({hedef['net']})")
            
        ax.set_ylabel("Net")
        plt.xticks(rotation=30, ha='right')
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
            df_tum_eksikler['ders'] = df_tum_eksikler['ders'].apply(tr_clean)
            df_tum_eksikler['konu_kazanim'] = df_tum_eksikler['konu_kazanim'].apply(tr_clean)

        with c_eksik:
            st.subheader("⚠️ Aktif Eksik / Çalışılması Gereken Konular")
            if not df_tum_eksikler.empty:
                df_son_eksik = df_tum_eksikler[df_tum_eksikler['sinav_id'] == son_sinav_id]
                if not df_son_eksik.empty:
                    for _, row in df_son_eksik.iterrows():
                        eksik_konu_listesi.append({'ders': tr_clean(row['ders']), 'konu': tr_clean(row['konu_kazanim'])})
                    
                    df_eksik_ozet = df_son_eksik.groupby(['ders', 'konu_kazanim']).size().reset_index(name='Tekrar Sayısı')
                    df_eksik_ozet.columns = ['Ders', 'Konu / Kazanım', 'Tekrar Sayısı']
                    st.dataframe(df_eksik_ozet, use_container_width=True)
                else:
                    st.success("🎉 Son sınavda tespit edilen yeni bir konu eksiği yok.")
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
                    for _, row in df_halledilen.iterrows():
                        halledilen_konu_listesi.append({'ders': tr_clean(row['ders']), 'konu': tr_clean(row['konu_kazanim'])})
                    df_halledilen.columns = ['Ders', 'Konu / Kazanım']
                    st.dataframe(df_halledilen, use_container_width=True)
                else:
                    st.info("Henüz düzeltilmiş bir konu kaydı bulunmuyor.")
            else:
                st.info("Henüz karşılaştırma yapılacak eksik veri yok.")
    else:
        st.warning(f"Bu öğrenciye ait {view_type} türünde girilmiş bir sınav sonucu bulunamadı.")
        
    st.markdown("---")
    st.subheader("🤖 Yapay Zeka Destekli Kişiselleştirilmiş Çalışma Programı")
    ai_study_plan = generate_ai_study_plan(eksik_konu_listesi)
    
    col_days = st.columns(len(ai_study_plan))
    for i, (day, tasks) in enumerate(ai_study_plan.items()):
        with col_days[i]:
            st.markdown(f"**{day}**")
            if tasks:
                for t in tasks:
                    st.caption(t)
            else:
                st.caption("Genel Tekrar / Serbest")

    df_notlar = pd.read_sql_query("SELECT tarih, not_metni FROM ogretmen_notlari WHERE ogrenci_adi_norm = ? ORDER BY id DESC", conn, params=(norm_adi,))
    notlar_list = [tr_clean(n) for n in df_notlar['not_metni'].tolist()] if not df_notlar.empty else []

    if allow_notes:
        st.markdown("---")
        st.subheader("📝 Öğretmen Görüş ve Notları")
        with st.form("ogretmen_not_form"):
            yeni_not = st.text_area("Öğrenci Hakkında Not Ekleyin:")
            if st.form_submit_button("Notu Kaydet"):
                if yeni_not.strip():
                    cursor.execute("INSERT INTO ogretmen_notlari (ogrenci_adi_norm, tarih, not_metni) VALUES (?, DATE('now'), ?)", (norm_adi, tr_clean(yeni_not.strip())))
                    conn.commit()
                    st.success("Not kaydedildi!")
                    st.rerun()

    st.markdown("---")
    st.subheader("📄 PDF Karne & Analiz Raporu İndir")
    if REPORTLAB_AVAILABLE:
        pdf_file = generate_pdf_report(ogr_adi, hedef, df_filtered, eksik_konu_listesi, halledilen_konu_listesi, ai_study_plan, notlar_list)
        if pdf_file:
            st.download_button(
                label="📥 PDF Karneyi İndir",
                data=pdf_file,
                file_name=f"{norm_adi}_Gelisim_Karnesi.pdf",
                mime="application/pdf",
                type="primary"
            )

    conn.close()

# --- ANA UYGULAMA VE NAVİGASYON ---
def main():
    st.sidebar.title("📌 Navigasyon")
    page = st.sidebar.radio("Sayfa Seçin:", ["Öğrenci Paneli", "Öğretmen / Yönetici Paneli", "Veri Yükleme (Excel)"])
    
    conn = sqlite3.connect("sinav_takip.db")
    df_ogrenciler = pd.read_sql_query("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari", conn)
    conn.close()

    if page == "Öğrenci Paneli":
        st.title("🎓 Öğrenci Sınav Takip & Analiz Portalı")
        if not df_ogrenciler.empty:
            ogr_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
            secilen_norm = st.selectbox("İsminizi Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            if secilen_norm:
                render_student_report(secilen_norm, ogr_dict[secilen_norm], allow_notes=False)
        else:
            st.warning("Veritabanında henüz kayıtlı öğrenci bulunamadı.")

    elif page == "Öğretmen / Yönetici Paneli":
        st.title("👨‍🏫 Öğretmen ve Yönetici Takip Ekranı")
        if not df_ogrenciler.empty:
            ogr_dict = dict(zip(df_ogrenciler['ogrenci_adi_norm'], df_ogrenciler['ogrenci_adi']))
            secilen_norm = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()), format_func=lambda x: ogr_dict[x])
            
            with st.expander("🎯 Öğrenciye Hedef Tanımla / Güncelle"):
                with st.form("hedef_form"):
                    bolum = st.text_input("Hedef Bölüm (Örn: Bilgisayar Müh.)")
                    alan = st.selectbox("Alan", ["SAY", "EA", "SÖZ", "DİL"])
                    net = st.number_input("Hedef Net", min_value=0.0, max_value=500.0, step=1.0)
                    puan = st.number_input("Hedef Puan", min_value=0.0, max_value=500.0, step=5.0)
                    if st.form_submit_button("Hedefi Kaydet"):
                        conn = sqlite3.connect("sinav_takip.db")
                        cursor = conn.cursor()
                        cursor.execute("REPLACE INTO hedefler (ogrenci_adi_norm, bolum, alan, net, puan) VALUES (?, ?, ?, ?, ?)",
                                       (secilen_norm, bolum, alan, net, puan))
                        conn.commit()
                        conn.close()
                        st.success("Hedef başarıyla güncellendi!")
                        st.rerun()

            if secilen_norm:
                render_student_report(secilen_norm, ogr_dict[secilen_norm], allow_notes=True)
        else:
            st.warning("Veritabanında kayıtlı öğrenci yok.")

    elif page == "Veri Yükleme (Excel)":
        st.title("📤 Sınav ve Eksik Konu Verisi Yükleme")
        st.info("Lütfen hazırladığınız Excel dosyasını yükleyin.")
        uploaded_file = st.file_uploader("Excel Dosyası Seçin (.xlsx)", type=["xlsx"])
        
        if uploaded_file:
            try:
                xls = pd.ExcelFile(uploaded_file)
                st.success(f"Yüklenen Dosya Sayfaları: {xls.sheet_names}")
            except Exception as e:
                st.error(f"Dosya okuma hatası: {e}")

if __name__ == "__main__":
    main()