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
    
    # Ana Öğrenci Listesi Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenciler (
        ogrenci_id INTEGER PRIMARY KEY AUTOINCREMENT,
        okul_no TEXT UNIQUE,
        ad_soyad TEXT,
        ad_soyad_norm TEXT UNIQUE,
        sinif TEXT,
        veli_telefon TEXT
    )''')

    # Sınavlar Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        tarih TEXT,
        sinav_turu TEXT DEFAULT 'TYT'
    )''')

    # Öğrenci Sonuçları Tablosu (TYT + AYT)
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
        ayt_mat_net REAL DEFAULT 0,
        ayt_fizik_net REAL DEFAULT 0,
        ayt_kimya_net REAL DEFAULT 0,
        ayt_biyoloji_net REAL DEFAULT 0,
        ayt_edebiyat_net REAL DEFAULT 0,
        ayt_tarih1_net REAL DEFAULT 0,
        ayt_cog1_net REAL DEFAULT 0,
        ayt_toplam_net REAL DEFAULT 0,
        ayt_say_puan REAL DEFAULT 0,
        ayt_ea_puan REAL DEFAULT 0,
        ayt_soz_puan REAL DEFAULT 0,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )''')

    # Tablo Güncellemeleri (Eski DB Uyumlu)
    cursor.execute("PRAGMA table_info(sinavlar)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'sinav_turu' not in cols:
        cursor.execute("ALTER TABLE sinavlar ADD COLUMN sinav_turu TEXT DEFAULT 'TYT'")

    cursor.execute("PRAGMA table_info(ogrenci_sonuclari)")
    os_cols = [col[1] for col in cursor.fetchall()]
    ayt_cols = [
        ('ayt_mat_net', 'REAL DEFAULT 0'), ('ayt_fizik_net', 'REAL DEFAULT 0'),
        ('ayt_kimya_net', 'REAL DEFAULT 0'), ('ayt_biyoloji_net', 'REAL DEFAULT 0'),
        ('ayt_edebiyat_net', 'REAL DEFAULT 0'), ('ayt_tarih1_net', 'REAL DEFAULT 0'),
        ('ayt_cog1_net', 'REAL DEFAULT 0'), ('ayt_toplam_net', 'REAL DEFAULT 0'),
        ('ayt_say_puan', 'REAL DEFAULT 0'), ('ayt_ea_puan', 'REAL DEFAULT 0'),
        ('ayt_soz_puan', 'REAL DEFAULT 0')
    ]
    for col_name, col_type in ayt_cols:
        if col_name not in os_cols:
            cursor.execute(f"ALTER TABLE ogrenci_sonuclari ADD COLUMN {col_name} {col_type}")

    # Eksik Konular Tablosu
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

    # Hedefler Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT UNIQUE,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL
    )''')

    # Ödevler Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinif TEXT,
        ders TEXT,
        konu_kaynak TEXT,
        son_tarih TEXT,
        eklenme_tarihi TEXT
    )''')

    # Ödev Takip Tablosu
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

# --- HTML KARNE RAPORU ---
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
        puan_display = r['tyt_puan'] if r['sinav_turu'] == 'TYT' else r['ayt_say_puan']
        table_rows += f"""
        <tr>
            <td>{r['sinav_adi']} ({r['sinav_turu']})</td><td>{r['tarih']}</td>
            <td style="font-weight:bold; color:#1a365d;">{r['toplam_net']:.2f}</td>
            <td style="font-weight:bold; color:#2b6cb0;">{puan_display:.2f}</td><td>{int(r['kurum_sirasi'])}</td>
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
                    <p>Deneme Sınavı Gelişim Karnesi | Sınıf: {last_row['sinif']}</p>
                </div>
            </div>
            {hedef_html}
            <div class="metrics">
                <div class="metric-box"><div class="metric-title">Son Sınav Neti</div><div class="metric-value">{last_row['toplam_net']:.2f}</div></div>
                <div class="metric-box"><div class="metric-title">Son Kurum Sırası</div><div class="metric-value">{int(last_row['kurum_sirasi'])}</div></div>
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
                        <tr><th>Sınav Adı</th><th>Tarih</th><th>Toplam Net</th><th>Puan</th><th>Sıra</th></tr>
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
    SELECT s.sinav_adi, s.tarih, s.sinav_turu, os.tyt_puan, os.kurum_sirasi, 
           os.turkce_net, os.sosyal_net, os.matematik_net, os.fen_net, os.toplam_net,
           os.ayt_mat_net, os.ayt_fizik_net, os.ayt_kimya_net, os.ayt_biyoloji_net,
           os.ayt_edebiyat_net, os.ayt_tarih1_net, os.ayt_cog1_net, os.ayt_toplam_net,
           os.ayt_say_puan, os.ayt_ea_puan, os.ayt_soz_puan, os.sinif
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
            st.info(f"🎯 **Hedeflanan Üniversite / Bölüm:** {hedef_info['bolum']} | **Hedef Net:** {hedef_info['net']} Net")
            c_h1, c_h2, c_h3 = st.columns(3)
            c_h1.metric("Son Sınav Neti", f"{last_row['toplam_net']:.2f}")
            c_h2.metric("Hedef Net", f"{hedef_info['net']:.2f}")
            c_h3.metric("Hedefe Kalan / Net Açığı", f"{net_fark:+.2f}", delta=f"{net_fark:.2f}", delta_color="normal")
            st.markdown("---")

        col1, col2, col3, col4 = st.columns(4)
        if last_row['sinav_turu'] == 'AYT':
            col1.metric("Son AYT SAY Puanı", f"{last_row['ayt_say_puan']:.2f}")
        else:
            col1.metric("Son TYT Puanı", f"{last_row['tyt_puan']:.2f}")

        col2.metric("Kurum Sırası", f"{int(last_row['kurum_sirasi'])}")
        col3.metric("Son Toplam Net", f"{last_row['toplam_net']:.2f}")
        col4.metric("Sınıfı", f"{last_row['sinif']}")

        st.markdown("---")
        
        c1, c2 = st.columns([1.1, 0.9])
        
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(df_ogr['sinav_adi'], df_ogr['toplam_net'], marker='o', color='#2b5797', linewidth=2.5, label="Öğrenci Neti")
        if hedef_info and hedef_info['net'] > 0:
            ax.axhline(y=hedef_info['net'], color='r', linestyle='--', label=f"Hedef ({hedef_info['net']} Net)")
        for i, txt in enumerate(df_ogr['toplam_net']):
            ax.annotate(f"{txt:.1f}", (df_ogr['sinav_adi'][i], df_ogr['toplam_net'][i]+1), ha='center', fontweight='bold')
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
        st.dataframe(df_ogr, use_container_width=True)
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

# --- ROL BAZLI MENÜ DÜZENLEMESİ ---
if st.session_state['role'] == 'admin':
    menu_options = [
        "📂 Sene Başı Öğrenci Listesi Yükle",
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

# --- 0. MENÜ: SENE BAŞI ÖĞRENCİ LİSTESİ YÜKLE ---
if secim == "📂 Sene Başı Öğrenci Listesi Yükle" and st.session_state["role"] == "admin":
    st.title("📂 Sene Başı Öğrenci Ana Listesi Yükleme Paneli")
    st.info("💡 **Önemli:** Sene başında tüm öğrencilerinizi içeren tek bir Excel dosyası yükleyin. Sistem öğrenci ve veli hesaplarını otomatik oluşturacaktır.")

    sablon_veri = {
        "Okul No": [917],
        "Adı Soyadı": ["ASLI ÇAĞLAR"],
        "öğrenci T.C. kimlik no": ["50383367498"],
        "Sınıfı": ["12-A"],
        "veli yakınlığı": ["Anne"],
        "veli adı": ["AYSEL"],
        "veli soyadı": ["ÇAĞLAR"],
        "Veli Telefon": ["5056344447"],
        "veli T.C. Kimlik no": ["50383367498"],
    }
    df_sablon = pd.DataFrame(sablon_veri)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_sablon.to_excel(writer, index=False, sheet_name="Ogrenci_Listesi")

    st.download_button(
        label="📥 Örnek Excel Şablonunu İndir",
        data=buffer.getvalue(),
        file_name="Ogrenci_Ana_Listesi_Sablonu.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Hata almamak için bu şablonu indirip verilerinizi yapıştırabilirsiniz.",
    )

    st.markdown("---")
    list_file = st.file_uploader("Öğrenci Ana Listesi Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])

    if st.button("🚀 Ana Öğrenci Listesini Yükle ve Hesapları Oluştur", type="primary"):
        if list_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()
                df = pd.read_excel(list_file)

                def get_val_from_row(row, possible_names, default=""):
                    for col in row.index:
                        col_norm = tr_normalize(str(col))
                        for p in possible_names:
                            if tr_normalize(p) in col_norm:
                                val = row[col]
                                if pd.notna(val) and str(val).strip() not in ["", "nan", "None", "NaN"]:
                                    return str(val).strip()
                    return default

                eklenen_sayisi = 0
                for _, row in df.iterrows():
                    raw_name = get_val_from_row(row, ["Adı Soyadı", "Ad Soyad", "Öğrenci", "Ogrenci", "İsim", "Isim", "AD SOYAD"])
                    if not raw_name or tr_normalize(raw_name) in ["NAN", "NONE", "", "OGRENCI", "ADI SOYADI"]:
                        continue

                    okul_no = get_val_from_row(row, ["Okul No", "Numara", "No", "Ogrenci No"])
                    sinif = get_val_from_row(row, ["Sınıfı", "Sınıf", "Sinif", "Grup", "Sınıf/Şube"])
                    veli_tel = get_val_from_row(row, ["Veli Telefon", "Telefon", "Tel", "GSM", "Veli Tel"])
                    norm_name = tr_normalize(raw_name)

                    cursor.execute('''
                    INSERT INTO ogrenciler (okul_no, ad_soyad, ad_soyad_norm, sinif, veli_telefon)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(ad_soyad_norm) DO UPDATE SET
                        okul_no=COALESCE(NULLIF(excluded.okul_no, ''), ogrenciler.okul_no),
                        sinif=COALESCE(NULLIF(excluded.sinif, ''), ogrenciler.sinif),
                        veli_telefon=COALESCE(NULLIF(excluded.veli_telefon, ''), ogrenciler.veli_telefon)
                    ''', (okul_no, raw_name, norm_name, sinif, veli_tel))

                    ogr_username = okul_no if okul_no else norm_name.lower().replace(" ", "")
                    veli_username = f"v_{ogr_username}"

                    cursor.execute("INSERT OR IGNORE INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, '123456', 'ogrenci', ?, '')", (ogr_username, norm_name))
                    cursor.execute("INSERT OR IGNORE INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, '123456', 'veli', ?, ?)", (veli_username, norm_name, veli_tel))
                    eklenen_sayisi += 1

                conn.commit()
                conn.close()
                st.success(f"🎉 Ana liste başarıyla işlendi! Toplam **{eklenen_sayisi}** öğrenci sisteme tanımlandı.")
            except Exception as e:
                st.error(f"Listeyi yüklerken hata oluştu: {e}")
        else:
            st.warning("Lütfen bir Excel dosyası seçin.")

    st.markdown("---")
    st.subheader("📋 Sistemde Kayıtlı Ana Öğrenci Listesi")
    conn = sqlite3.connect("sinav_takip.db")
    df_ana_liste = pd.read_sql_query("SELECT okul_no as 'Okul No', ad_soyad as 'Adı Soyadı', sinif as 'Sınıf', veli_telefon as 'Veli Telefon' FROM ogrenciler ORDER BY sinif, ad_soyad", conn)
    conn.close()
    if not df_ana_liste.empty:
        st.dataframe(df_ana_liste, use_container_width=True)

# --- 1. MENÜ: YENİ SINAV YÜKLE (TYT VE AYT DESTEKLİ) ---
elif secim == "📤 Yeni Sınav Yükle" and st.session_state['role'] == 'admin':
    st.title("📤 Yeni Deneme Sınavı Yükleme Paneli")
    
    c_t1, c_t2, c_t3 = st.columns(3)
    with c_t1:
        sinav_turu = st.selectbox("Sınav Türü Seçin:", ["TYT", "AYT"])
    with c_t2:
        sinav_adi = st.text_input("Sınav Adı", placeholder="Örn: 345 AYT Genel - Mart 2026")
    with c_t3:
        sinav_tarihi = st.date_input("Sınav Tarihi")

    excel_file = st.file_uploader("Toplu Sonuc Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])
    pdf_file = st.file_uploader("Yanlış Cevap Listesi PDF Dosyasını Yükleyin (.pdf)", type=["pdf"])

    if st.button("🚀 Sınavı Veritabanına İşle ve Analiz Et", type="primary"):
        if sinav_adi and excel_file and pdf_file:
            try:
                conn = sqlite3.connect("sinav_takip.db")
                cursor = conn.cursor()

                cursor.execute("INSERT OR IGNORE INTO sinavlar (sinav_adi, tarih, sinav_turu) VALUES (?, ?, ?)", (sinav_adi, str(sinav_tarihi), sinav_turu))
                cursor.execute("SELECT sinav_id FROM sinavlar WHERE sinav_adi = ?", (sinav_adi,))
                sinav_id = cursor.fetchone()[0]

                df_raw = pd.read_excel(excel_file)
                
                header_row_idx = None
                for idx, row in df_raw.iterrows():
                    row_str_values = [str(val).strip().upper() for val in row.values if pd.notna(val)]
                    if any("ÖĞRENCİ" in val or "OGRENCI" in val for val in row_str_values):
                        header_row_idx = idx
                        break

                if header_row_idx is not None:
                    headers = [str(c).strip() if pd.notna(c) else '' for c in df_raw.iloc[header_row_idx].values]
                    df = df_raw.iloc[header_row_idx + 1:].copy()
                    df.columns = headers
                else:
                    df = df_raw.copy()

                def get_val(row, possible_names, default=0.0):
                    for name in possible_names:
                        for col in row.index:
                            if name.upper() in str(col).strip().upper():
                                val = row[col]
                                if pd.notna(val) and str(val).strip() not in ['', 'nan', 'None']:
                                    return val
                    return default

                cursor.execute("SELECT okul_no, ad_soyad, ad_soyad_norm, sinif FROM ogrenciler")
                ana_ogrenciler = cursor.fetchall()
                dict_by_no = {str(o[0]): (o[1], o[2], o[3]) for o in ana_ogrenciler if o[0]}
                dict_by_norm = {o[2]: (o[1], o[2], o[3]) for o in ana_ogrenciler}

                for _, row in df.iterrows():
                    raw_name = get_val(row, ['Öğrenci', 'Ogrenci', 'Adı Soyadı', 'Ad Soyad'], default=None)
                    if not raw_name or str(raw_name).strip().upper() in ['NAN', 'NONE', '', 'ÖĞRENCİ']:
                        continue
                    
                    raw_name = str(raw_name).strip()
                    norm_name = tr_normalize(raw_name)
                    numara = str(get_val(row, ['Numara', 'No'], default='')).strip()

                    matched_name = raw_name
                    matched_norm = norm_name
                    grup = str(get_val(row, ['Grup', 'Sınıf', 'Sinif'], default=''))

                    if numara in dict_by_no:
                        matched_name, matched_norm, matched_sinif = dict_by_no[numara]
                        if matched_sinif: grup = matched_sinif
                    elif norm_name in dict_by_norm:
                        matched_name, matched_norm, matched_sinif = dict_by_norm[norm_name]
                        if matched_sinif: grup = matched_sinif

                    sira = int(float(get_val(row, ['YKS TYT K.B.', 'K.B.', 'Kurum Sıra', 'Sıra'], default=0)))

                    if sinav_turu == "TYT":
                        puan = float(get_val(row, ['YKS TYT', 'TYT Puan'], default=0.0))
                        turkce = float(get_val(row, ['Tür 05.N', 'Türkçe Net', 'Tür Net'], default=0.0))
                        sosyal = float(get_val(row, ['Sos 05.N', 'Sosyal Net', 'Sos Net'], default=0.0))
                        mat = float(get_val(row, ['Tem 05.N', 'Matematik Net', 'Mat Net'], default=0.0))
                        fen = float(get_val(row, ['Fen 05.N', 'Fen Net'], default=0.0))
                        toplam = float(get_val(row, ['TYT 05.N', 'Toplam Net', 'TYT Net'], default=0.0))

                        cursor.execute('''
                        INSERT INTO ogrenci_sonuclari 
                        (sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif, tyt_puan, kurum_sirasi, turkce_net, sosyal_net, matematik_net, fen_net, toplam_net)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (sinav_id, numara, matched_name, matched_norm, grup, puan, sira, turkce, sosyal, mat, fen, toplam))

                    ```python
                    else: # AYT SINAVI
                        # ==========================================================
                        # AYT EXCEL SÜTUNLARI
                        # Gerçek AYT Excel dosyasındaki sütun adlarına göre
                        # hazırlanmıştır.
                        # ==========================================================

                        # AYT SAYISAL DERSLER
                        ayt_mat = float(get_val(
                            row,
                            ['Mat 05.N', 'AYT Mat', 'Matematik Net'],
                            default=0.0
                        ))

                        ayt_geo = float(get_val(
                            row,
                            ['Geo 05.N (1)', 'Geo 05.N', 'Geometri Net'],
                            default=0.0
                        ))

                        ayt_fiz = float(get_val(
                            row,
                            ['Fiz 05.N (1)', 'Fiz 05.N', 'Fizik Net'],
                            default=0.0
                        ))

                        ayt_kim = float(get_val(
                            row,
                            ['Kim 05.N (1)', 'Kim 05.N', 'Kimya Net'],
                            default=0.0
                        ))

                        ayt_bio = float(get_val(
                            row,
                            ['Biy 05.N (1)', 'Biy 05.N', 'Biyoloji Net'],
                            default=0.0
                        ))

                        # ==========================================================
                        # AYT EŞİT AĞIRLIK / SÖZEL DERSLER
                        # ==========================================================

                        ayt_edeb = float(get_val(
                            row,
                            ['Tür 05.N (2)', 'Tür 05.N', 'Edebiyat Net', 'Edeb Net'],
                            default=0.0
                        ))

                        ayt_tar1 = float(get_val(
                            row,
                            ['Tar 05.N (1)', 'Tarih-1 Net', 'Tar1 Net'],
                            default=0.0
                        ))

                        ayt_cog1 = float(get_val(
                            row,
                            ['Coğ 05.N (1)', 'Coğ 05.N', 'Coğrafya-1 Net', 'Coğ1 Net'],
                            default=0.0
                        ))

                        # ==========================================================
                        # AYT TOPLAM NET
                        #
                        # Excel'de ayrıca tek bir "AYT Toplam Net" alanı olmadığı
                        # için ana AYT derslerinin netlerini topluyoruz.
                        #
                        # Matematik + Geometri + Fizik + Kimya + Biyoloji
                        # + Edebiyat + Tarih-1 + Coğrafya-1
                        # ==========================================================

                        ayt_toplam = (
                            ayt_mat +
                            ayt_geo +
                            ayt_fiz +
                            ayt_kim +
                            ayt_bio +
                            ayt_edeb +
                            ayt_tar1 +
                            ayt_cog1
                        )

                        # ==========================================================
                        # AYT PUANLARI
                        #
                        # Bu Excel dosyasında doğrudan AYT SAY / EA / SÖZ puan
                        # sütunları bulunmadığı için şimdilik 0 bırakıyoruz.
                        #
                        # Puan hesaplama aşamasında bunu ayrıca ele alacağız.
                        # ==========================================================

                        puan_say = 0.0
                        puan_ea = 0.0
                        puan_soz = 0.0

                        # ==========================================================
                        # VERİTABANINA KAYIT
                        # ==========================================================

                        cursor.execute('''
                        INSERT INTO ogrenci_sonuclari
                        (
                            sinav_id,
                            ogrenci_no,
                            ogrenci_adi,
                            ogrenci_adi_norm,
                            sinif,
                            kurum_sirasi,

                            ayt_mat_net,
                            ayt_fizik_net,
                            ayt_kimya_net,
                            ayt_biyoloji_net,
                            ayt_edebiyat_net,
                            ayt_tarih1_net,
                            ayt_cog1_net,
                            ayt_toplam_net,

                            ayt_say_puan,
                            ayt_ea_puan,
                            ayt_soz_puan,

                            toplam_net
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            sinav_id,
                            numara,
                            matched_name,
                            matched_norm,
                            grup,
                            sira,

                            ayt_mat,
                            ayt_fiz,
                            ayt_kim,
                            ayt_bio,
                            ayt_edeb,
                            ayt_tar1,
                            ayt_cog1,
                            ayt_toplam,

                            puan_say,
                            puan_ea,
                            puan_soz,

                            ayt_toplam
                        ))
```


                # PDF Okuma
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
                        
                        if pdf_norm_name in dict_by_norm:
                            pdf_name, pdf_norm_name, _ = dict_by_norm[pdf_norm_name]

                        matches = re.findall(r'\d+\s*-\s*([^(]+)\(([^)]+)\)', block)
                        for konu, sorular in matches:
                            konu_temiz = konu.strip()
                            if "ÜÇDÖRTBES" in konu_temiz or "TYT" in konu_temiz or "AYT" in konu_temiz or len(konu_temiz) < 2:
                                continue
                            
                            cursor.execute('''
                            INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim, soru_nolari)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ''', (sinav_id, pdf_name, pdf_norm_name, "Genel", konu_temiz, sorular.strip()))

                conn.commit()
                conn.close()
                st.success(f"🎉 [{sinav_turu}] '{sinav_adi}' sınavı başarıyla yüklendi ve işlendi!")

            except Exception as e:
                st.error(f"Hata oluştu: {e}")

# --- 2. MENÜ: ÖĞRENCİ KARNELERİ ---
elif secim == "📊 Öğrenci Karneleri & Analiz" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🎓 Öğrenci Analiz Karnesi")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
    siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
    secilen_sinif = st.selectbox("Sınıf Seçin:", siniflar)

    if secilen_sinif == "Tüm Sınıflar":
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
    else:
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari WHERE sinif = ? ORDER BY ogrenci_adi ASC", (secilen_sinif,))
    
    ogrenciler = cursor.fetchall()
    conn.close()

    if ogrenciler:
        ogr_dict = {f"{o[0]}": o[1] for o in ogrenciler}
        secilen_ogr_adi = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()))
        secilen_norm = ogr_dict[secilen_ogr_adi]
        render_student_report(secilen_norm, secilen_ogr_adi, allow_notes=True)
    else:
        st.warning("Bu kriterlere uygun öğrenci bulunamadı.")

# --- 3. MENÜ: ÖDEV & SORU BANKASI TAKİBİ ---
elif secim == "📚 Ödev & Soru Bankası Takibi" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📚 Ödev & Soru Bankası Takip Paneli")
    
    tab1, tab2 = st.tabs(["➕ Yeni Ödev Tanımla", "📋 Ödev Takibi & Durum Güncelleme"])
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    with tab1:
        st.subheader("Sınıf/Grup İçin Yeni Ödev Ekle")
        cursor.execute("SELECT DISTINCT sinif FROM ogrenciler ORDER BY sinif ASC")
        sinif_list = [s[0] for s in cursor.fetchall() if s[0]]
        if not sinif_list:
            sinif_list = ["12-A", "12-B", "11-A", "Mezun"]
            
        with st.form("yeni_odev_form"):
            target_sinif = st.selectbox("Hedef Sınıf:", sinif_list)
            ders_adi = st.selectbox("Ders:", ["Matematik", "Fizik", "Kimya", "Biyoloji", "Türkçe/Edebiyat", "Tarih", "Coğrafya", "Felsefe/Din"])
            konu_kaynak = st.text_input("Ödev Konusu ve Kaynak Kitap / Sayfa:", placeholder="Örn: 3D Matematik SB - Türev Test 1-5")
            son_tarih = st.date_input("Son Teslim Tarihi:")
            btn_odev = st.form_submit_button("📢 Ödevi Tüm Sınıfa Tanımla", type="primary")
            
            if btn_odev:
                if konu_kaynak:
                    import datetime
                    bugun = str(datetime.date.today())
                    cursor.execute("INSERT INTO odevler (sinif, ders, konu_kaynak, son_tarih, eklenme_tarihi) VALUES (?, ?, ?, ?, ?)",
                                   (target_sinif, ders_adi, konu_kaynak, str(son_tarih), bugun))
                    odev_id = cursor.lastrowid
                    
                    cursor.execute("SELECT ad_soyad_norm FROM ogrenciler WHERE sinif = ?", (target_sinif,))
                    sinif_ogrencileri = cursor.fetchall()
                    for ogr in sinif_ogrencileri:
                        cursor.execute("INSERT OR IGNORE INTO odev_takip (odev_id, ogrenci_adi_norm, durum) VALUES (?, ?, 'Bekliyor')",
                                       (odev_id, ogr[0]))
                    conn.commit()
                    st.success(f"✅ Ödev {target_sinif} sınıfındaki {len(sinif_ogrencileri)} öğrenciye tanımlandı!")
                else:
                    st.warning("Lütfen ödev konusunu girin.")

    with tab2:
        st.subheader("📋 Verilen Ödevlerin Kontrolü")
        cursor.execute("SELECT odev_id, sinif, ders, konu_kaynak, son_tarih FROM odevler ORDER BY odev_id DESC")
        odevler = cursor.fetchall()
        
        if odevler:
            odev_options = {f"[{o[1]}] {o[2]} - {o[3]} (Son: {o[4]})": o[0] for o in odevler}
            secilen_odev_label = st.selectbox("Kontrol Edilecek Ödevi Seçin:", list(odev_options.keys()))
            secilen_odev_id = odev_options[secilen_odev_label]
            
            cursor.execute('''
                SELECT ot.id, o.ad_soyad, ot.durum, ot.aciklama 
                FROM odev_takip ot
                JOIN ogrenciler o ON ot.ogrenci_adi_norm = o.ad_soyad_norm
                WHERE ot.odev_id = ?
                ORDER BY o.ad_soyad ASC
            ''', (secilen_odev_id,))
            
            odev_durumlari = cursor.fetchall()
            if odev_durumlari:
                df_odev_takip = pd.DataFrame(odev_durumlari, columns=["ID", "Öğrenci Adı", "Ödev Durumu", "Açıklama/Not"])
                st.info("💡 Öğrencilerin ödev durumlarını aşağıdaki tablodan değiştirebilirsiniz:")
                
                edited_df = st.data_editor(
                    df_odev_takip,
                    column_config={
                        "Ödev Durumu": st.column_config.SelectboxColumn(
                            "Ödev Durumu",
                            options=["Tamamlandı", "Eksik Yapıldı", "Yapılmadı", "Bekliyor"],
                            required=True
                        )
                    },
                    disabled=["ID", "Öğrenci Adı"],
                    use_container_width=True,
                    key="odev_editor"
                )
                
                if st.button("💾 Ödev Durumlarını Kaydet", type="primary"):
                    for _, r in edited_df.iterrows():
                        cursor.execute("UPDATE odev_takip SET durum = ?, aciklama = ? WHERE id = ?", (r["Ödev Durumu"], str(r["Açıklama/Not"]), r["ID"]))
                    conn.commit()
                    st.success("✅ Ödev durumları başarıyla güncellendi!")
        else:
            st.info("Henüz sisteme tanımlanmış ödev bulunmuyor.")
    conn.close()

# --- 4. MENÜ: VELİ BİLGİLENDİRME & WHATSAPP / SMS ---
elif secim == "📱 Veli Bilgilendirme & WhatsApp/SMS" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📱 Veli Bilgilendirme & Otomatik WhatsApp Mesaj Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT DISTINCT sinif FROM ogrenciler ORDER BY sinif ASC")
    siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
    secilen_sinif = st.selectbox("Filtrelenecek Sınıfı Seçin:", siniflar)
    
    if secilen_sinif == "Tüm Sınıflar":
        cursor.execute("SELECT ad_soyad, ad_soyad_norm, veli_telefon, sinif FROM ogrenciler WHERE veli_telefon IS NOT NULL AND veli_telefon != ''")
    else:
        cursor.execute("SELECT ad_soyad, ad_soyad_norm, veli_telefon, sinif FROM ogrenciler WHERE sinif = ? AND veli_telefon IS NOT NULL AND veli_telefon != ''", (secilen_sinif,))
        
    veli_list = cursor.fetchall()
    conn.close()

    if veli_list:
        st.subheader("📲 Tekli Veliye WhatsApp Karnesi Gönder")
        ogr_map = {f"{v[0]} ({v[3]} - Tel: {v[2]})": (v[1], v[2], v[0]) for v in veli_list}
        secilen_ogr_key = st.selectbox("Öğrenci Seçin:", list(ogr_map.keys()))
        secilen_norm, raw_tel, raw_name = ogr_map[secilen_ogr_key]

        # Son sınav neti ve eksikleri al
        conn = sqlite3.connect("sinav_takip.db")
        df_last = pd.read_sql_query("SELECT * FROM ogrenci_sonuclari WHERE ogrenci_adi_norm = ? ORDER BY id DESC LIMIT 1", conn, params=(secilen_norm,))
        aktif_eksikler, _ = get_ogrenci_eksik_durumu(conn, secilen_norm)
        conn.close()

        if not df_last.empty:
            last = df_last.iloc[0]
            eksik_str = ", ".join([e[0] for e in aktif_eksikler[:3]]) if aktif_eksikler else "Bulunmuyor"
            
            mesaj = f"Sayin Velimiz,\n\nOgrencimiz {raw_name}'in son deneme sinavi sonucu:\n"
            mesaj += f"📊 Toplam Net: {last['toplam_net']:.2f}\n"
            mesaj += f"🏆 Kurum Sirasi: {int(last['kurum_sirasi'])}\n"
            mesaj += f"⚠️ Acil Calisilmasi Gereken Konular: {eksik_str}\n\n"
            mesaj += "Detayli karneye sistemden ulasabilirsiniz.\nNazif Tokgoz Basari Koleji"
            
            st.text_area("Gönderilecek Mesaj Taslağı:", mesaj, height=130)
            
            clean_tel = re.sub(r'\D', '', str(raw_tel))
            if len(clean_tel) == 10:
                clean_tel = "90" + clean_tel
            elif len(clean_tel) == 11 and clean_tel.startswith("0"):
                clean_tel = "90" + clean_tel[1:]
                
            encoded_msg = urllib.parse.quote(mesaj)
            wa_link = f"https://api.whatsapp.com/send?phone={clean_tel}&text={encoded_msg}"
            
            st.markdown(f'<a href="{wa_link}" target="_blank" style="background-color:#25D366; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; font-weight:bold;">📲 WhatsApp Üzerinden Gönder</a>', unsafe_allow_html=True)
        else:
            st.warning("Bu öğrenciye ait herhangi bir sınav sonucu bulunamadı.")
    else:
        st.warning("Telefon numarası kayıtlı öğrenci/veli bulunamadı.")

# --- 5. MENÜ: HEDEF BELİRLEME & TAKİP ---
elif secim == "🎯 Hedef Belirleme & Takip" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🎯 Öğrenci Hedef Belirleme & Net Takip Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT ad_soyad, ad_soyad_norm, sinif FROM ogrenciler ORDER BY ad_soyad ASC")
    ogr_list = cursor.fetchall()
    
    if ogr_list:
        ogr_dict = {f"{o[0]} ({o[2]})": o[1] for o in ogr_list}
        secilen_label = st.selectbox("Öğrenci Seçin:", list(ogr_dict.keys()))
        secilen_norm = ogr_dict[secilen_label]
        
        m_hedef = get_ogrenci_hedef(secilen_norm)
        m_bolum = m_hedef['bolum'] if m_hedef else ""
        m_net = m_hedef['net'] if m_hedef else 0.0
        m_puan = m_hedef['puan'] if m_hedef else 0.0
        
        with st.form("hedef_form"):
            hedef_bolum = st.text_input("Hedeflenen Üniversite / Bölüm:", value=m_bolum, placeholder="Örn: İTÜ Bilgisayar Mühendisliği")
            col_h1, col_h2 = st.columns(2)
            with col_h1:
                hedef_net = st.number_input("Hedef Net (TYT veya AYT Toplam):", value=float(m_net), step=1.0)
            with col_h2:
                hedef_puan = st.number_input("Hedef Puan:", value=float(m_puan), step=5.0)
                
            btn_hedef = st.form_submit_button("🎯 Hedefi Kaydet / Güncelle", type="primary")
            if btn_hedef:
                cursor.execute('''
                    INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET
                        hedef_bolum=excluded.hedef_bolum,
                        hedef_net=excluded.hedef_net,
                        hedef_puan=excluded.hedef_puan
                ''', (secilen_norm, hedef_bolum, hedef_net, hedef_puan))
                conn.commit()
                st.success("✅ Öğrenci hedefi başarıyla kaydedildi!")
    conn.close()

# --- 6. MENÜ: OKUL GENEL DURUMU & DERECELER ---
elif secim == "🏫 Okul Genel Durumu & Dereceler" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🏫 Okul / Kurum Genel Derece & Başarı Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT sinav_id, sinav_adi, sinav_turu FROM sinavlar ORDER BY sinav_id DESC", conn)
    
    if not df_sinavlar.empty:
        sinav_dict = {f"{r['sinav_adi']} ({r['sinav_turu']})": r['sinav_id'] for _, r in df_sinavlar.iterrows()}
        secilen_sinav_label = st.selectbox("Sınav Seçin:", list(sinav_dict.keys()))
        secilen_sinav_id = sinav_dict[secilen_sinav_label]
        
        df_res = pd.read_sql_query('''
            SELECT kurum_sirasi as 'Sıra', ogrenci_no as 'No', ogrenci_adi as 'Ad Soyad', sinif as 'Sınıf',
                   toplam_net as 'Toplam Net', tyt_puan as 'TYT Puan', ayt_say_puan as 'AYT SAY Puan'
            FROM ogrenci_sonuclari
            WHERE sinav_id = ?
            ORDER BY kurum_sirasi ASC
        ''', conn, params=(secilen_sinav_id,))
        
        if not df_res.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Sınava Giren Öğrenci", f"{len(df_res)}")
            c2.metric("En Yüksek Net", f"{df_res['Toplam Net'].max():.2f}")
            c3.metric("Ortalama Net", f"{df_res['Toplam Net'].mean():.2f}")
            
            st.markdown("---")
            st.subheader("🏆 Sınav Derece Listesi")
            st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Bu sınava ait sonuç bulunamadı.")
    else:
        st.info("Henüz sisteme sınav yüklenmemiş.")
    conn.close()

# --- 7. MENÜ: RADAR & SINIF DAĞILIMI ---
elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🕸️ Sınıf Karşılaştırmalı Ders Analiz Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT sinav_id, sinav_adi FROM sinavlar ORDER BY sinav_id DESC", conn)
    
    if not df_sinavlar.empty:
        sinav_dict = {r['sinav_adi']: r['sinav_id'] for _, r in df_sinavlar.iterrows()}
        secilen_sinav_label = st.selectbox("Analiz Edilecek Sınavı Seçin:", list(sinav_dict.keys()))
        secilen_sinav_id = sinav_dict[secilen_sinav_label]
        
        df_s = pd.read_sql_query('''
            SELECT sinif, AVG(turkce_net) as Türkçe, AVG(sosyal_net) as Sosyal, 
                   AVG(matematik_net) as Matematik, AVG(fen_net) as Fen
            FROM ogrenci_sonuclari
            WHERE sinav_id = ? AND sinif IS NOT NULL AND sinif != ''
            GROUP BY sinif
        ''', conn, params=(secilen_sinav_id,))
        
        if not df_s.empty:
            st.subheader("📊 Sınıflara Göre Ders Net Ortalamaları")
            st.dataframe(df_s, use_container_width=True)
            
            categories = ['Türkçe', 'Sosyal', 'Matematik', 'Fen']
            N = len(categories)
            angles = [n / float(N) * 2 * np.pi for n in range(N)]
            angles += angles[:1]
            
            fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
            
            for _, r in df_s.iterrows():
                values = [r['Türkçe'], r['Sosyal'], r['Matematik'], r['Fen']]
                values += values[:1]
                ax.plot(angles, values, linewidth=2, label=r['sinif'])
                ax.fill(angles, values, alpha=0.1)
                
            plt.xticks(angles[:-1], categories)
            plt.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
            st.pyplot(fig)
        else:
            st.warning("Sınıf verisi bulunamadı.")
    else:
        st.info("Henüz sınav verisi yüklenmemiş.")
    conn.close()

# --- 8. MENÜ: OKUL KONU/KAZANIM ANALİZİ ---
elif secim == "🔥 Okul Konu/Kazanım Analizi" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🔥 Okul Genel Konu / Kazanım Eksik Analizi")
    
    conn = sqlite3.connect("sinav_takip.db")
    df_sinavlar = pd.read_sql_query("SELECT sinav_id, sinav_adi FROM sinavlar ORDER BY sinav_id DESC", conn)
    
    if not df_sinavlar.empty:
        sinav_dict = {"Tüm Sınavlar Geneli": 0}
        for _, r in df_sinavlar.iterrows():
            sinav_dict[r['sinav_adi']] = r['sinav_id']
            
        secilen_s_label = st.selectbox("Sınav Filtresi:", list(sinav_dict.keys()))
        s_id = sinav_dict[secilen_s_label]
        
        if s_id == 0:
            query = "SELECT konu_kazanim, COUNT(*) as 'Yanlış Yapan Öğrenci Sayısı' FROM ogrenci_eksikleri GROUP BY konu_kazanim ORDER BY COUNT(*) DESC LIMIT 20"
            df_eksik = pd.read_sql_query(query, conn)
        else:
            query = "SELECT konu_kazanim, COUNT(*) as 'Yanlış Yapan Öğrenci Sayısı' FROM ogrenci_eksikleri WHERE sinav_id = ? GROUP BY konu_kazanim ORDER BY COUNT(*) DESC LIMIT 20"
            df_eksik = pd.read_sql_query(query, conn, params=(s_id,))
            
        if not df_eksik.empty:
            st.subheader("⚠️ Okul Genelinde En Çok Yanlış Yapılan İlk 20 Konu")
            
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.barh(df_eksik['konu_kazanim'], df_eksik['Yanlış Yapan Öğrenci Sayısı'], color='#e53e3e')
            ax.invert_yaxis()
            ax.set_xlabel("Öğrenci Sayısı")
            ax.set_title("En Kritik Konu Eksikleri")
            st.pyplot(fig)
            
            st.dataframe(df_eksik, use_container_width=True)
        else:
            st.info("Eksik konu kaydı bulunamadı.")
    else:
        st.info("Henüz sınav yüklenmemiş.")
    conn.close()

# --- 9. MENÜ: ÖĞRENCİ & VELİ HESAP YÖNETİMİ ---
elif secim == "👥 Öğrenci & Veli Hesap Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Öğrenci & Veli Kullanıcı Hesap Yönetimi")
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    df_users = pd.read_sql_query("SELECT id, kullanici_adi as 'Kullanıcı Adı', sifre as 'Şifre', rol as 'Rol', ogrenci_adi_norm as 'İlişkili Öğrenci' FROM kullanicilar ORDER BY rol, kullanici_adi", conn)
    st.dataframe(df_users, use_container_width=True)
    
    st.markdown("---")
    st.subheader("🔑 Şifre Sıfırla / Güncelle")
    with st.form("reset_pass_form"):
        user_to_reset = st.selectbox("Kullanıcı Seçin:", df_users['Kullanıcı Adı'].tolist())
        new_password_input = st.text_input("Yeni Şifre:", value="123456")
        btn_reset = st.form_submit_button("🔑 Şifreyi Güncelle", type="primary")
        
        if btn_reset:
            cursor.execute("UPDATE kullanicilar SET sifre = ? WHERE kullanici_adi = ?", (new_password_input.strip(), user_to_reset))
            conn.commit()
            st.success(f"✅ '{user_to_reset}' kullanıcısının şifresi '{new_password_input}' olarak güncellendi!")
    conn.close()

# --- 10. MENÜ: KURUM AYARLARI & LOGO ---
elif secim == "⚙️ Kurum Ayarları & Logo" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum Ayarları & Logo Yönetimi")
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    mevcut_adi, mevcut_logo = get_kurum_bilgileri()
    
    with st.form("kurum_form"):
        yeni_kurum_adi = st.text_input("Kurum / Okul Adı:", value=mevcut_adi)
        logo_file = st.file_uploader("Kurum Logosu Yükleyin (PNG/JPG):", type=["png", "jpg", "jpeg"])
        btn_kurum = st.form_submit_button("💾 Ayarları Kaydet", type="primary")
        
        if btn_kurum:
            logo_b64 = mevcut_logo
            if logo_file:
                bytes_data = logo_file.read()
                logo_b64 = base64.b64encode(bytes_data).decode('utf-8')
                
            cursor.execute("DELETE FROM kurum_ayarlari")
            cursor.execute("INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) VALUES (1, ?, ?)", (yeni_kurum_adi, logo_b64))
            conn.commit()
            st.success("✅ Kurum bilgileri başarıyla güncellendi!")
            st.rerun()
    conn.close()

# --- 11. MENÜ: SINAV YÖNETİMİ & SİLME ---
elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Yönetimi & Silme Paneli")
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    df_sinavlar = pd.read_sql_query("SELECT sinav_id, sinav_adi, tarih, sinav_turu FROM sinavlar ORDER BY sinav_id DESC", conn)
    
    if not df_sinavlar.empty:
        st.dataframe(df_sinavlar, use_container_width=True)
        st.markdown("---")
        
        sinav_dict = {f"{r['sinav_adi']} ({r['tarih']})": r['sinav_id'] for _, r in df_sinavlar.iterrows()}
        secilen_del_label = st.selectbox("Silinecek Sınavı Seçin:", list(sinav_dict.keys()))
        secilen_del_id = sinav_dict[secilen_del_label]
        
        if st.button("❌ Seçilen Sınavı ve Tüm Verilerini Sil", type="primary"):
            cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (secilen_del_id,))
            cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (secilen_del_id,))
            cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (secilen_del_id,))
            conn.commit()
            st.success("✅ Sınav ve ilgili tüm analiz verileri başarıyla silindi!")
            st.rerun()
    else:
        st.info("Sistemde silinecek sınav bulunmuyor.")
    conn.close()

# --- ÖĞRENCİ & VELİ ÖZEL EKRANLARI ---
elif secim == "🎓 Gelişim & Analiz Karnem":
    st.title("🎓 Gelişim & Analiz Karnem")
    norm_name = st.session_state['user_info']['norm_adi']
    if norm_name:
        render_student_report(norm_name, st.session_state['user_info']['username'], allow_notes=False)
    else:
        st.error("Kullanıcı hesabınıza atanmış bir öğrenci bulunamadı.")

elif secim == "📚 Ödevlerim & Ödev Durumu":
    st.title("📚 Ödevlerim & Ödev Takip Ekranım")
    norm_name = st.session_state['user_info']['norm_adi']
    
    if norm_name:
        conn = sqlite3.connect("sinav_takip.db")
        df_my_odev = pd.read_sql_query('''
            SELECT o.ders as 'Ders', o.konu_kaynak as 'Ödev Konusu / Kaynak', 
                   o.son_tarih as 'Son Teslim Tarihi', ot.durum as 'Durum', ot.aciklama as 'Öğretmen Notu'
            FROM odev_takip ot
            JOIN odevler o ON ot.odev_id = o.odev_id
            WHERE ot.ogrenci_adi_norm = ?
            ORDER BY o.odev_id DESC
        ''', conn, params=(norm_name,))
        conn.close()
        
        if not df_my_odev.empty:
            st.dataframe(df_my_odev, use_container_width=True)
        else:
            st.info("Henüz tarafınıza tanımlanmış bir ödev bulunmamaktadır.")
    else:
        st.error("Öğrenci kaydı bulunamadı.")

elif secim == "🎯 Üniversite / Hedefim":
    st.title("🎯 Üniversite / Hedef Durumum")
    norm_name = st.session_state['user_info']['norm_adi']
    
    if norm_name:
        hedef_info = get_ogrenci_hedef(norm_name)
        if hedef_info and hedef_info['net'] > 0:
            st.success(f"🎯 **Hedeflenen Bölüm:** {hedef_info['bolum']}")
            col1, col2 = st.columns(2)
            col1.metric("Hedeflenen Net", f"{hedef_info['net']:.2f}")
            col2.metric("Hedeflenen Puan", f"{hedef_info['puan']:.2f}")
        else:
            st.info("Henüz rehberlik servisi / öğretmeniniz tarafından bir hedef girilmemiş.")
    else:
        st.error("Öğrenci kaydı bulunamadı.")