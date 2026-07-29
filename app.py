import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Sayfa Konfigürasyonu ---
st.set_page_config(page_title="Sınav Takip Sistemi", page_icon="📊", layout="wide")

# Session State Başlatma (Giriş/Rol Yönetimi)
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'role' not in st.session_state:
    st.session_state['role'] = None
if 'username' not in st.session_state:
    st.session_state['username'] = None

# --- Veritabanı Bağlantısı ve Tablo Oluşturma ---
def init_db():
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    # Kullanıcılar Tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            sinif TEXT
        )
    ''')
    
    # Sınavlar Tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sinavlar (
            sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT,
            tarih DATE
        )
    ''')
    
    # Öğrenci Sonuçları Tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_id INTEGER,
            ogrenci_no TEXT,
            ogrenci_adi TEXT,
            sinif TEXT,
            turkce_net REAL,
            sosyal_net REAL,
            matematik_net REAL,
            fen_net REAL,
            toplam_net REAL,
            tyt_puan REAL,
            FOREIGN KEY (sinav_id) REFERENCES sinavlar(sinav_id)
        )
    ''')
    
    # Varsayılan Admin Hesabı (Eğer yoksa ekler)
    cursor.execute("SELECT * FROM kullanicilar WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO kullanicilar (username, password, role, sinif) VALUES ('admin', 'admin123', 'admin', 'TÜMÜ')")
    
    conn.commit()
    conn.close()

init_db()

# --- GİRİŞ EKRANI ---
if not st.session_state['logged_in']:
    st.title("🔐 Sınav Takip Sistemi - Giriş")
    
    username_input = st.text_input("Kullanıcı Adı")
    password_input = st.text_input("Şifre", type="password")
    
    if st.button("Giriş Yap", type="primary"):
        conn = sqlite3.connect("sinav_takip.db")
        cursor = conn.cursor()
        cursor.execute("SELECT username, role, sinif FROM kullanicilar WHERE username = ? AND password = ?", (username_input, password_input))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            st.session_state['logged_in'] = True
            st.session_state['username'] = user[0]
            st.session_state['role'] = user[1]
            st.session_state['sinif'] = user[2]
            st.success("Giriş başarılı! Sayfa yükleniyor...")
            st.rerun()
        else:
            st.error("Kullanıcı adı veya şifre hatalı!")

# --- ANA UYGULAMA ---
else:
    # Sol Yan Menü (Sidebar)
    st.sidebar.title(f"👤 {st.session_state['username']} ({st.session_state['role'].upper()})")
    
    # Menü Seçenekleri
    menu_options = [
        "📊 Genel Özet & İstatistikler",
        "👨‍🎓 Öğrenci Bazlı İnceleme",
        "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım"
    ]
    
    if st.session_state['role'] == 'admin':
        menu_options.extend([
            "📥 Sınav Sonucu Yükle (Excel/CSV)",
            "👥 Kullanıcı Yönetimi"
        ])
        
    secim = st.sidebar.radio("Menü Seçiniz:", menu_options)
    
    if st.sidebar.button("🚪 Çıkış Yap"):
        st.session_state['logged_in'] = False
        st.session_state['role'] = None
        st.session_state['username'] = None
        st.rerun()

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    # --- 1. MENÜ: GENEL ÖZET & İSTATİSTİKLER ---
    if secim == "📊 Genel Özet & İstatistikler":
        st.title("📊 Genel Özet & İstatistikler")
        
        cursor.execute("SELECT sinav_adi FROM sinavlar ORDER BY tarih DESC")
        sinavlar = [s[0] for s in cursor.fetchall()]
        
        if sinavlar:
            secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
            
            query = '''
            SELECT os.ogrenci_no, os.ogrenci_adi, os.sinif, os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.tyt_puan
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ?
            '''
            df_sonuc = pd.read_sql_query(query, conn, params=(secilen_sinav,))
            
            if st.session_state['role'] == 'ogretmen' and st.session_state['sinif'] != 'TÜMÜ':
                df_sonuc = df_sonuc[df_sonuc['sinif'] == st.session_state['sinif']]

            st.dataframe(df_sonuc, use_container_width=True)
        else:
            st.info("Sistemde henüz kayıtlı bir sınav bulunmamaktadır.")

    # --- 2. MENÜ: ÖĞRENCİ BAZLI İNCELEME ---
    elif secim == "👨‍🎓 Öğrenci Bazlı İnceleme":
        st.title("👨‍🎓 Öğrenci Bazlı İnceleme & Gelişim")
        
        cursor.execute("SELECT DISTINCT ogrenci_adi FROM ogrenci_sonuclari ORDER BY ogrenci_adi")
        ogrenciler = [o[0] for o in cursor.fetchall()]
        
        if ogrenciler:
            secilen_ogrenci = st.selectbox("Öğrenci Seçiniz:", ogrenciler)
            
            query = '''
            SELECT s.sinav_adi, s.tarih, os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net, os.tyt_puan
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE os.ogrenci_adi = ?
            ORDER BY s.tarih ASC
            '''
            df_ogr = pd.read_sql_query(query, conn, params=(secilen_ogrenci,))
            
            st.write(f"### {secilen_ogrenci} - Sınav Gelişim Tablosu")
            st.dataframe(df_ogr, use_container_width=True)
            
            if not df_ogr.empty:
                st.line_chart(df_ogr.set_index('sinav_adi')[['toplam_net', 'tyt_puan']])
        else:
            st.info("Kayıtlı öğrenci verisi bulunamadı.")

    # --- 3. MENÜ: RADAR & DAĞILIM (DÜZELTİLEN KISIM) ---
    elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım" and st.session_state['role'] in ['admin', 'ogretmen']:
        st.title("🕸️ Sınıf Bazlı Karşılaştırmalı Radar & Net Dağılım Analizi")

        cursor.execute("SELECT sinav_adi FROM sinavlar ORDER BY tarih DESC")
        sinavlar = [s[0] for s in cursor.fetchall()]

        if sinavlar:
            secilen_sinav = st.selectbox("Analiz Edilecek Deneme Sınavını Seçiniz:", sinavlar)
            
            query = '''
            SELECT os.sinif, 
                   AVG(os.turkce_net) as turkce, 
                   AVG(os.sosyal_net) as sosyal, 
                   AVG(os.matematik_net) as mat, 
                   AVG(os.fen_net) as fen,
                   AVG(os.toplam_net) as toplam,
                   AVG(os.tyt_puan) as puan,
                   COUNT(*) as ogr_sayisi
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ?
            GROUP BY os.sinif
            '''
            df_sinif_ort = pd.read_sql_query(query, conn, params=(secilen_sinav,))

            if not df_sinif_ort.empty:
                st.markdown("### 📋 Sınıf Ortalamaları Özet Tablosu")
                df_display = df_sinif_ort.rename(columns={
                    'sinif': 'Sınıf', 'turkce': 'Türkçe Net', 'sosyal': 'Sosyal Net', 
                    'mat': 'Matematik Net', 'fen': 'Fen Net', 'toplam': 'Toplam Net', 
                    'puan': 'TYT Puanı', 'ogr_sayisi': 'Öğrenci Sayısı'
                })
                st.dataframe(df_display.style.highlight_max(axis=0, color='#c6f6d5', subset=['Türkçe Net', 'Sosyal Net', 'Matematik Net', 'Fen Net', 'Toplam Net', 'TYT Puanı']), use_container_width=True)

                st.markdown("---")

                # Karşılaştırılacak Sınıfları Seçme
                tum_siniflar = df_sinif_ort['sinif'].tolist()
                secilen_siniflar = st.multiselect("Radar Grafikte Karşılaştırılacak Sınıfları Seçin:", tum_siniflar, default=tum_siniflar[:3] if len(tum_siniflar)>=3 else tum_siniflar)

                if secilen_siniflar:
                    c_rad1, c_rad2 = st.columns([1.1, 0.9])

                    with c_rad1:
                        st.subheader("🕸️ Ders Bazlı Radar (Örümcek) Grafiği")
                        
                        categories = ['Türkçe', 'Sosyal', 'Matematik', 'Fen']
                        N = len(categories)
                        
                        angles = [n / float(N) * 2 * np.pi for n in range(N)]
                        angles += angles[:1]

                        fig_radar, ax_radar = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
                        
                        ax_radar.set_theta_offset(np.pi / 2)
                        ax_radar.set_theta_direction(-1)

                        plt.xticks(angles[:-1], categories, color='grey', size=11, fontweight='bold')
                        ax_radar.set_rlabel_position(0)
                        plt.yticks([10, 20, 30, 40], ["10 Net", "20 Net", "30 Net", "40 Net"], color="grey", size=8)
                        plt.ylim(0, 40)

                        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

                        for i, s_adi in enumerate(secilen_siniflar):
                            row = df_sinif_ort[df_sinif_ort['sinif'] == s_adi].iloc[0]
                            values = [row['turkce'], row['sosyal'], row['mat'], row['fen']]
                            values += values[:1]
                            
                            color = colors[i % len(colors)]
                            ax_radar.plot(angles, values, linewidth=2, linestyle='solid', label=f"Sınıf: {s_adi}", color=color)
                            ax_radar.fill(angles, values, color=color, alpha=0.15)

                        plt.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
                        st.pyplot(fig_radar)

                    with c_rad2:
                        st.subheader("📦 Sınıf Toplam Net Dağılımı (Boxplot)")
                        st.caption("Çizgi: Medyan (Orta değer) | Kutu: Öğrenci Yoğunluğu")

                        # Detay Öğrenci Verilerini Çek
                        query_detay = '''
                        SELECT os.sinif, os.toplam_net
                        FROM ogrenci_sonuclari os
                        JOIN sinavlar s ON os.sinav_id = s.sinav_id
                        WHERE s.sinav_adi = ? AND os.sinif IN ({})
                        '''.format(','.join(['?']*len(secilen_siniflar)))

                        df_detay = pd.read_sql_query(query_detay, conn, params=[secilen_sinav] + secilen_siniflar)

                        fig_box, ax_box = plt.subplots(figsize=(6, 5.5))
                        
                        data_to_plot = [df_detay[df_detay['sinif'] == s]['toplam_net'].dropna().values for s in secilen_siniflar]
                        
                        # Matplotlib uyumluluğu için tick_labels eklendi
                        box = ax_box.boxplot(data_to_plot, patch_artist=True, tick_labels=secilen_siniflar)

                        for patch, color in zip(box['boxes'], colors[:len(secilen_siniflar)]):
                            patch.set_facecolor(color)
                            patch.set_alpha(0.6)

                        ax_box.set_ylabel("Toplam Net")
                        ax_box.set_title(f"{secilen_sinav} - Net Dağılımı", fontsize=11, fontweight='bold')
                        ax_box.grid(True, linestyle='--', alpha=0.5)
                        st.pyplot(fig_box)

                else:
                    st.warning("Lütfen grafik oluşturmak için en az bir sınıf seçin.")

            else:
                st.warning("Bu sınava ait veriler okunamadı.")
        else:
            st.warning("Sistemde henüz kayıtlı sınav bulunmuyor.")

    # --- 4. MENÜ: YÜKLEME EKRANI (ADMIN) ---
    elif secim == "📥 Sınav Sonucu Yükle (Excel/CSV)" and st.session_state['role'] == 'admin':
        st.title("📥 Sınav Sonucu Yükleme Ekranı")
        
        sinav_adi = st.text_input("Sınav Adı (Örn: TYT Deneme - 1)")
        sinav_tarihi = st.date_input("Sınav Tarihi")
        
        uploaded_file = st.file_uploader("Excel veya CSV Dosyası Yükleyin", type=['xlsx', 'xls', 'csv'])
        
        if uploaded_file and sinav_adi:
            if st.button("Verileri Kaydet"):
                try:
                    if uploaded_file.name.endswith('.csv'):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)
                        
                    cursor.execute("INSERT INTO sinavlar (sinav_adi, tarih) VALUES (?, ?)", (sinav_adi, str(sinav_tarihi)))
                    sinav_id = cursor.lastrowid
                    
                    for _, row in df.iterrows():
                        cursor.execute('''
                            INSERT INTO ogrenci_sonuclari 
                            (sinav_id, ogrenci_no, ogrenci_adi, sinif, turkce_net, sosyal_net, matematik_net, fen_net, toplam_net, tyt_puan)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            sinav_id, str(row.get('No', '')), str(row.get('Ad Soyad', '')), str(row.get('Sınıf', '')),
                            float(row.get('Türkçe Net', 0)), float(row.get('Sosyal Net', 0)),
                            float(row.get('Matematik Net', 0)), float(row.get('Fen Net', 0)),
                            float(row.get('Toplam Net', 0)), float(row.get('Puan', 0))
                        ))
                    
                    conn.commit()
                    st.success("Sınav sonuçları başarıyla yüklendi!")
                except Exception as e:
                    st.error(f"Hata oluştu: {e}")

    # --- 5. MENÜ: KULLANICI YÖNETİMİ (ADMIN) ---
    elif secim == "👥 Kullanıcı Yönetimi" and st.session_state['role'] == 'admin':
        st.title("👥 Kullanıcı Yönetimi")
        
        st.subheader("Yeni Kullanıcı Ekle")
        new_user = st.text_input("Kullanıcı Adı")
        new_pass = st.text_input("Şifre")
        new_role = st.selectbox("Rol", ["admin", "ogretmen"])
        new_sinif = st.text_input("Sınıf Yetkisi (Örn: 12/A veya TÜMÜ)")
        
        if st.button("Kullanıcı Oluştur"):
            try:
                cursor.execute("INSERT INTO kullanicilar (username, password, role, sinif) VALUES (?, ?, ?, ?)",
                               (new_user, new_pass, new_role, new_sinif))
                conn.commit()
                st.success(f"{new_user} kullanıcısı oluşturuldu.")
            except Exception as e:
                st.error(f"Kullanıcı oluşturulamadı: {e}")

    conn.close()