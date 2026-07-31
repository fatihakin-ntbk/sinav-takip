import streamlit as st



# 1. Sayfa genişliğini yaymak istersen (isteğe bağlı ama logoların daha şık durmasını sağlar)

# st.set_page_config(layout="wide") # Eğer kodunda zaten varsa tekrar ekleme



# ---------------------------------------------------------

# ÜST BAŞLIK (HEADER) - Tüm rollerde ve menülerde ortak görünür

# ---------------------------------------------------------

col_logo, col_slogan = st.columns([1, 4], vertical_alignment="center")



with col_logo:

    # Logo görseli (Local dosya yolu veya web URL'si verebilirsin)

    st.image("logo.png", width=750)  # Genişliği sayfanı rahatsız etmeyecek şekilde ayarlayabilirsin



with col_slogan:

    # Slogan metni

    st.markdown(

        """

        <h2 style='margin:0; padding:0; color: #1F2937;'>Geleceğin Eğitimi, Bugünün Analizi</h2>

        <p style='margin:0; padding:0; color: #6B7280; font-size: 16px;'>Başarıya Giden Yolda Doğru Takip</p>

        """, 

        unsafe_allow_html=True

    )



# İsteğe bağlı: Logo ile içerik arasına ince şık bir çizgi

st.divider()



# ---------------------------------------------------------

# BURADAN SONRA SENİN MEVCUT KODLARIN (Giriş kontrolü, Roller, Menüler vs.) BAŞLAR

# ---------------------------------------------------------

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

        tarih TEXT

    )''')



    # Öğrenci Sonuçları Tablosu

    cursor.execute('''

    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sinav_id INTEGER,

        ogrenci_no TEXT,

        ogrenci_adi TEXT,

        ogrenci_adi_norm TEXT,

        sinif TEXT,

        tyt_puan REAL,

        kurum_sirasi INTEGER,

        turkce_net REAL,

        sosyal_net REAL,

        matematik_net REAL,

        fen_net REAL,

        toplam_net REAL,

        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE

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

        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE

    )''')



    # Kurum Bilgileri ve Logo Tablosu

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



    # Ödevler Genel Tablosu (YENİ)

    cursor.execute('''

    CREATE TABLE IF NOT EXISTS odevler (

        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,

        sinif TEXT,

        ders TEXT,

        konu_kaynak TEXT,

        son_tarih TEXT,

        eklenme_tarihi TEXT

    )''')



    # Ödev Takip / Durum Tablosu (YENİ)

    cursor.execute('''

    CREATE TABLE IF NOT EXISTS odev_takip (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        odev_id INTEGER,

        ogrenci_adi_norm TEXT,

        durum TEXT DEFAULT 'Bekliyor',

        aciklama TEXT,

        FOREIGN KEY (odev_id) REFERENCES odevler (odev_id) ON DELETE CASCADE,

        UNIQUE(odev_id, ogrenci_adi_norm)

    )''')



    # Varsayılan Admin ve Öğretmen Hesapları

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



# --- HTML REPORT ---

def generate_student_html_report(df_ogr, aktif_eksikler, tamamlanan_konular, student_name, fig_img_base64, veli_notu="", hedef_info=None):

    last_row = df_ogr.iloc[-1]

    kurum_adi, logo_base64 = get_kurum_bilgileri()

    

    logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="max-height: 70px; object-fit: contain;">' if logo_base64 else f'<div style="font-size:20px; font-weight:bold; color:#1a365d;">🏛️ {kurum_adi}</div>'



    hedef_html = ""

    if hedef_info and hedef_info['net'] > 0:

        net_fark = last_row['toplam_net'] - hedef_info['net']

        durum_renk = "#276749" if net_fark >= 0 else "#c53030"

        durum_text = f"🎯 HEDEF BÖLÜM: <b>{hedef_info['bolum']}</b> | Hedef Net: <b>{hedef_info['net']}</b> | Mevcut Fark: <b style='color:{durum_renk};'>{net_fark:+.2f} Net</b>"

        hedef_html = f"""

        <div style="background:#edf2f7; border-left:4px solid #3182ce; padding:8px 12px; margin-bottom:12px; border-radius:4px; font-size:12px;">

            {durum_text}

        </div>

        """



    ai_plan = generate_ai_study_plan(aktif_eksikler)

    ai_program_html = ""

    if ai_plan["program"]:

        ai_rows = ""

        for p in ai_plan["program"]:

            ai_rows += f"""

            <tr style="font-size:11px;">

                <td style="font-weight:bold; color:#2d3748;">{p['konu']}</td>

                <td style="color:#c53030; font-weight:bold;">{p['oncelik']}</td>

                <td style="text-align:center; font-weight:bold; color:#2b6cb0;">{p['hedef_soru']} Soru</td>

                <td style="color:#4a5568;">{p['tavsiye']}</td>

            </tr>

            """

        ai_program_html = f"""

        <div style="margin-top:15px; background:#f7fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px;">

            <div style="font-size:12px; font-weight:bold; color:#2b6cb0; margin-bottom:6px;">🤖 AKILLI ÖNERİ: HAFTALIK ÖZEL ÇALIŞMA ROTASI</div>

            <table style="width:100%; border-collapse:collapse;">

                <thead>

                    <tr style="background:#edf2f7; font-size:10px; text-align:left;">

                        <th>Odak Konu</th><th>Öncelik</th><th style="text-align:center;">Haftalık Hedef</th><th>Çalışma Stratejisi</th>

                    </tr>

                </thead>

                <tbody>{ai_rows}</tbody>

            </table>

        </div>

        """



    not_html = ""

    if veli_notu.strip():

        not_html = f"""

        <div style="margin-top: 15px; background: #f7fafc; border: 1px solid #cbd5e0; border-left: 5px solid #3182ce; border-radius: 8px; padding: 12px;">

            <div style="font-size: 13px; font-weight: bold; color: #2b6cb0; margin-bottom: 4px;">✍️ REHBERLİK & ÖĞRETMEN DEĞERLENDİRME NOTU:</div>

            <div style="font-size: 12px; color: #2d3748; line-height: 1.4; white-space: pre-wrap;">{veli_notu}</div>

        </div>

        """



    table_rows = ""

    for _, r in df_ogr.iterrows():

        table_rows += f"""

        <tr>

            <td>{r['sinav_adi']}</td><td>{r['tarih']}</td><td>{r['turkce_net']:.2f}</td><td>{r['sosyal_net']:.2f}</td>

            <td>{r['matematik_net']:.2f}</td><td>{r['fen_net']:.2f}</td><td style="font-weight:bold; color:#1a365d;">{r['toplam_net']:.2f}</td>

            <td style="font-weight:bold; color:#2b6cb0;">{r['tyt_puan']:.2f}</td><td>{int(r['kurum_sirasi'])}</td>

        </tr>

        """

        

    eksik_rows = ""

    if aktif_eksikler:

        for konu, tekrar in aktif_eksikler:

            badge_color = "#e53e3e" if tekrar > 1 else "#dd6b20"

            eksik_rows += f"""

            <div style="background:#fff5f5; border-left:4px solid {badge_color}; padding:6px 10px; margin-bottom:6px; border-radius:4px; display:flex; justify-content:space-between; align-items:center;">

                <span style="font-weight:600; color:#2d3748; font-size:11px;">📌 {konu}</span>

                <span style="background:{badge_color}; color:white; font-size:9px; padding:2px 6px; border-radius:10px; font-weight:bold;">{tekrar} Sınavda Yanlış</span>

            </div>

            """

    else:

        eksik_rows = "<p style='color:#38a169; font-weight:bold; font-size:12px;'>🎉 Aktif eksik konu bulunmuyor!</p>"



    tamamlanan_rows = ""

    if tamamlanan_konular:

        for konu in tamamlanan_konular:

            tamamlanan_rows += f"""

            <div style="background:#f0fff4; border-left:4px solid #38a169; padding:6px 10px; margin-bottom:6px; border-radius:4px; font-size:11px; color:#276749; font-weight:600;">

                ✅ {konu}

            </div>

            """

    else:

        tamamlanan_rows = "<p style='color:#718096; font-size:11px;'>Henüz kazanılan konu kaydı yok.</p>"



    html_content = f"""

    <!DOCTYPE html>

    <html lang="tr">

    <head>

        <meta charset="UTF-8">

        <title>{student_name} - Öğrenci Analiz Karnesi</title>

        <style>

            @page {{ size: A4 portrait; margin: 10mm; }}

            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #fff; color: #2d3748; margin: 0; padding: 0; }}

            .card {{ background: white; border-radius: 8px; padding: 10px; }}

            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #3182ce; padding-bottom: 10px; margin-bottom: 12px; }}

            .header-info h1 {{ margin: 0; color: #1a365d; font-size: 20px; }}

            .header-info p {{ margin: 2px 0 0 0; color: #718096; font-size: 12px; }}

            .metrics {{ display: flex; gap: 10px; margin-bottom: 12px; }}

            .metric-box {{ flex: 1; background: #ebf8ff; border: 1px solid #bee3f8; border-radius: 6px; padding: 8px; text-align: center; }}

            .metric-title {{ font-size: 10px; color: #2b6cb0; font-weight: bold; text-transform: uppercase; }}

            .metric-value {{ font-size: 16px; font-weight: bold; color: #2c5282; margin-top: 2px; }}

            .section-title {{ font-size: 13px; font-weight: bold; color: #2d3748; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}

            table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; }}

            th {{ background-color: #2b6cb0; color: white; padding: 6px; text-align: left; }}

            td {{ padding: 6px; border-bottom: 1px solid #e2e8f0; }}

            tr:nth-child(even) {{ background-color: #f7fafc; }}

            .grafik-container {{ width: 100%; margin-bottom: 12px; text-align: center; }}

            .listeler-container {{ display: flex; gap: 15px; margin-bottom: 12px; }}

            .sutun {{ flex: 1; }}

            @media print {{ body {{ background: white; padding: 0; }} .no-print {{ display: none; }} }}

        </style>

    </head>

    <body>

        <div class="no-print" style="text-align:right; margin-bottom:10px;">

            <button onclick="window.print()" style="background:#3182ce; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:bold;">🖨️ Yazdır / PDF Olarak Kaydet</button>

        </div>

        <div class="card">

            <div class="header">

                <div>{logo_html}</div>

                <div class="header-info" style="text-align:right;">

                    <h1>🎓 {student_name.upper()}</h1>

                    <p>TYT Deneme Sınavı Gelişim & Analiz Karnesi | Sınıf: {last_row['sinif']}</p>

                </div>

            </div>

            {hedef_html}

            <div class="metrics">

                <div class="metric-box"><div class="metric-title">Son TYT Puanı</div><div class="metric-value">{last_row['tyt_puan']:.2f}</div></div>

                <div class="metric-box"><div class="metric-title">Son Kurum Sırası</div><div class="metric-value">{int(last_row['kurum_sirasi'])}</div></div>

                <div class="metric-box"><div class="metric-title">Son Toplam Net</div><div class="metric-value">{last_row['toplam_net']:.2f}</div></div>

                <div class="metric-box"><div class="metric-title">Girdiği Sınav Sayısı</div><div class="metric-value">{len(df_ogr)}</div></div>

            </div>

            <div class="grafik-container">

                <div class="section-title">📈 Net Gelişim Grafiği</div>

                <img src="data:image/png;base64,{fig_img_base64}" style="width:100%; max-height:200px; object-fit:contain; border-radius:6px; border:1px solid #e2e8f0;">

            </div>

            <div class="listeler-container">

                <div class="sutun"><div class="section-title">⚠️ Aktif Eksik Konular</div>{eksik_rows}</div>

                <div class="sutun"><div class="section-title">🎉 Başarıyla Halledilen Konular</div>{tamamlanan_rows}</div>

            </div>

            {ai_program_html}

            {not_html}

            <div style="margin-top:12px;">

                <div class="section-title">📋 Sınav Katılım & Geçmiş Tablosu</div>

                <table>

                    <thead>

                        <tr><th>Sınav Adı</th><th>Tarih</th><th>Türkçe</th><th>Sosyal</th><th>Matematik</th><th>Fen</th><th>Toplam Net</th><th>TYT Puanı</th><th>Sıra</th></tr>

                    </thead>

                    <tbody>{table_rows}</tbody>

                </table>

            </div>

        </div>

    </body>

    </html>

    """

    return html_content



# --- ÖĞRENCİ KARNE BİLEŞENİ ---

def render_student_report(secilen_norm, secilen_ogr_adi, allow_notes=True):

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

        hedef_info = get_ogrenci_hedef(secilen_norm)

        

        if hedef_info and hedef_info['net'] > 0:

            net_fark = last_row['toplam_net'] - hedef_info['net']

            st.info(f"🎯 **Hedeflenen Üniversite / Bölüm:** {hedef_info['bolum']} | **Hedef Net:** {hedef_info['net']} Net")

            c_h1, c_h2, c_h3 = st.columns(3)

            c_h1.metric("Son Sınav Neti", f"{last_row['toplam_net']:.2f}")

            c_h2.metric("Hedef Net", f"{hedef_info['net']:.2f}")

            c_h3.metric("Hedefe Kalan / Net Açığı", f"{net_fark:+.2f}", delta=f"{net_fark:.2f}", delta_color="normal")

            st.markdown("---")



        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Son TYT Puanı", f"{last_row['tyt_puan']:.2f}")

        col2.metric("Kurum Sırası", f"{int(last_row['kurum_sirasi'])}")

        col3.metric("Son Toplam Net", f"{last_row['toplam_net']:.2f}")

        col4.metric("Sınıfı", f"{last_row['sinif']}")



        st.markdown("---")

        grafik_turu = st.radio("Grafik Türü:", ["Toplam Net Gelişimi", "Ders Bazlı Net Dağılımı"], horizontal=True)

        c1, c2 = st.columns([1.1, 0.9])

        

        fig, ax = plt.subplots(figsize=(7, 3.5))

        if grafik_turu == "Toplam Net Gelişimi":

            ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#2b5797', linewidth=2.5, label="Öğrenci Neti")

            if hedef_info and hedef_info['net'] > 0:

                ax.axhline(y=hedef_info['net'], color='r', linestyle='--', label=f"Hedef ({hedef_info['net']} Net)")

            for i, txt in enumerate(df_ogr['toplam_net']):

                ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+2), ha='center', fontweight='bold')

            ax.set_ylim(0, 120)

            ax.legend(loc="upper left")

        else:

            ax.plot(df_ogr['sinav_adi'], df_ogr['turkce_net'], marker='s', color='#e74c3c', label="Türkçe")

            ax.plot(df_ogr['sinav_adi'], df_ogr['matematik_net'], marker='^', color='#27ae60', label="Matematik")

            ax.plot(df_ogr['sinav_adi'], df_ogr['fen_net'], marker='o', color='#f39c12', label="Fen")

            ax.plot(df_ogr['sinav_adi'], df_ogr['sosyal_net'], marker='d', color='#8e44ad', label="Sosyal")

            ax.legend(loc="upper left")

            ax.set_ylim(0, 42)



        ax.set_ylabel("Net")

        ax.grid(True, linestyle='--', alpha=0.5)

        plt.xticks(rotation=15)



        buf = io.BytesIO()

        plt.savefig(buf, format='png', bbox_inches='tight')

        buf.seek(0)

        fig_img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')



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

            else:

                st.info("Henüz kazanılan konu kaydı bulunmuyor.")



        st.markdown("---")

        st.subheader("🤖 Yapay Zeka / Akıllı Sistem Haftalık Çalışma Önerisi")

        ai_plan = generate_ai_study_plan(aktif_eksikler)

        

        if ai_plan["mesaj"]:

            st.success(ai_plan["mesaj"])

        else:

            cols = st.columns(len(ai_plan["program"]))

            for idx, p in enumerate(ai_plan["program"]):

                with cols[idx]:

                    st.markdown(f"**📌 Odak Konu:** {p['konu']}")

                    st.caption(f"{p['oncelik']}")

                    st.metric("Haftalık Hedef", f"{p['hedef_soru']} Soru")

                    st.write(f"💡 *{p['tavsiye']}*")



        st.markdown("---")

        veli_notu = ""

        if allow_notes:

            veli_notu = st.text_area("✍️ Rehberlik / Öğretmen Veli Değerlendirme Notu (Karnede Görünür):", height=80)



        html_report = generate_student_html_report(df_ogr, aktif_eksikler, tamamlanan_konular, secilen_ogr_adi, fig_img_base64, veli_notu, hedef_info)

        

        st.download_button(

            label=f"📄 {secilen_ogr_adi} Karne Raporunu İndir (PDF/HTML)",

            data=html_report,

            file_name=f"{secilen_norm}_Gelisim_Karnesi.html",

            mime="text/html",

            type="primary",

            use_container_width=True

        )



        st.subheader("📋 Sınav Geçmiş Tablosu")

        st.dataframe(df_ogr[['sinav_adi', 'tarih', 'turkce_net', 'sosyal_net', 'matematik_net', 'fen_net', 'toplam_net', 'tyt_puan']], use_container_width=True)

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



with st.sidebar.expander("🔒 Şifremi Değiştir"):

    with st.form("change_password_form"):

        old_pass = st.text_input("Mevcut Şifre:", type="password")

        new_pass = st.text_input("Yeni Şifre:", type="password")

        confirm_pass = st.text_input("Yeni Şifre (Tekrar):", type="password")

        submit_pass = st.form_submit_button("Şifreyi Güncelle")



        if submit_pass:

            if not old_pass or not new_pass:

                st.error("Lütfen alanları doldurun.")

            elif new_pass != confirm_pass:

                st.error("Yeni şifreler eşleşmiyor!")

            else:

                conn = sqlite3.connect("sinav_takip.db")

                cursor = conn.cursor()

                cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ? AND sifre = ?", 

                               (st.session_state['user_info']['username'], old_pass.strip()))

                usr = cursor.fetchone()

                if usr:

                    cursor.execute("UPDATE kullanicilar SET sifre = ? WHERE id = ?", (new_pass.strip(), usr[0]))

                    conn.commit()

                    st.success("✅ Şifreniz başarıyla değiştirildi!")

                else:

                    st.error("Mevcut şifreniz yanlış.")

                conn.close()



st.sidebar.markdown("---")



# --- ROL BAZLI MENÜ ---

if st.session_state['role'] == 'admin':

    menu_options = [

        "📤 Yeni Sınav Yükle", 

        "📊 Öğrenci Karneleri & Analiz", 

        "📚 Ödev & Soru Bankası Takibi",

        "📱 Veli Bilgilendirme & WhatsApp/SMS",

        "🎯 Hedef Belirleme & Takip",

        "🏫 Okul Genel Durumu & Dereceler", 

        "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım",

        "🔥 Okul Konu/Kazanım Analizi", 

        "👥 Öğrenci & Veli Hesap Yönetimi",

        "⚙️ Kurum Ayarları & Logo",

        "🗑️ Sınav Yönetimi & Silme"

    ]

elif st.session_state['role'] == 'ogretmen':

    menu_options = [

        "📊 Öğrenci Karneleri & Analiz", 

        "📚 Ödev & Soru Bankası Takibi",

        "📱 Veli Bilgilendirme & WhatsApp/SMS",

        "🎯 Hedef Belirleme & Takip",

        "🏫 Okul Genel Durumu & Dereceler", 

        "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım",

        "🔥 Okul Konu/Kazanım Analizi"

    ]

else:

    menu_options = ["🎓 Gelişim & Analiz Karnem", "📚 Ödevlerim & Ödev Durumu", "🎯 Üniversite / Hedefim"]



secim = st.sidebar.radio("Sistem Menüsü:", menu_options)



# --- 1. MENÜ: YENİ SINAV YÜKLE ---

if secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':

    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")

    col1, col2 = st.columns(2)

    with col1:

        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: 345 TYT Genel - Mart 2026")

    with col2:

        sinav_tarihi = st.date_input("Sınav Tarihi")



    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])

    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])



    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):

        if sinav_adi and excel_file and pdf_file:

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

                    raw_name = str(row['Öğrenci']).strip()

                    if pd.isna(raw_name) or raw_name in ['nan', 'None', '']:

                        continue

                    norm_name = tr_normalize(raw_name)



                    puan = float(row['YKS TYT']) if pd.notna(row['YKS TYT']) else 0.0

                    sira = int(row['YKS TYT K.B.']) if pd.notna(row['YKS TYT K.B.']) else 0

                    turkce = float(row['Tür 05.N']) if pd.notna(row['Tür 05.N']) else 0.0

                    sosyal = float(row['Sos 05.N']) if pd.notna(row['Sos 05.N']) else 0.0

                    mat = float(row['Tem 05.N']) if pd.notna(row['Tem 05.N']) else 0.0

                    fen = float(row['Fen 05.N']) if pd.notna(row['Fen 05.N']) else 0.0

                    toplam = float(row['TYT 05.N']) if pd.notna(row['TYT 05.N']) else 0.0



                    cursor.execute('''

                    INSERT INTO ogrenci_sonuclari 

                    (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, tyt_puan, kurum_sirasi, turkce_net, sosyal_net, matematik_net, fen_net, toplam_net)

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                    ''', (sinav_id, str(row['Numara']), raw_name, norm_name, str(row['Grup']), puan, sira, turkce, sosyal, mat, fen, toplam))



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

                            if "ÜÇDÖRTBES" in konu_temiz or "TYT" in konu_temiz or len(konu_temiz) < 2:

                                continue

                            

                            cursor.execute('''

                            INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)

                            VALUES (?, ?, ?, ?, ?, ?)

                            ''', ( 

