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

    # Ödevler Genel Tablosu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinif TEXT,
        ders TEXT,
        konu_kaynak TEXT,
        son_tarih TEXT,
        eklenme_tarihi TEXT
    )''')

    # Ödev Takip / Durum Tablosu
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
                            ''', (sinav_id, pdf_name, pdf_norm_name, "Genel", konu_temiz, sorular.strip()))

                conn.commit()
                conn.close()
                st.success(f"🎉 '{sinav_adi}' başarıyla yüklendi!")

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

# --- 3. MENÜ: ÖDEV & SORU BANKASI TAKİBİ (ADMİN & ÖĞRETMEN) ---
elif secim == "📚 Ödev & Soru Bankası Takibi" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📚 Ödev & Soru Bankası Takip Modülü")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    tab_o1, tab_o2, tab_o3 = st.tabs(["➕ Yeni Ödev Tanımla", "📋 Sınıf Ödev Kontrolü / İşaretleme", "📊 Ödev İstatistikleri & Analiz"])

    # --- TAB 1: YENİ ÖDEV TANIMLA ---
    with tab_o1:
        st.subheader("📝 Yeni Sınıf Ödevi Oluştur")
        
        cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
        sinif_list = [s[0] for s in cursor.fetchall() if s[0]]

        if sinif_list:
            with st.form("yeni_odev_form"):
                co1, co2 = st.columns(2)
                with co1:
                    o_sinif = st.selectbox("Ödev Verilecek Sınıf:", sinif_list)
                    o_ders = st.selectbox("Ders:", ["Matematik", "Geometri", "Türkçe", "Fizik", "Kimya", "Biyoloji", "Tarih", "Coğrafya", "Felsefe", "Din Kültürü", "Genel / Rehberlik"])
                with co2:
                    o_kaynak = st.text_input("Ödev Tanımı / Kitap - Sayfa - Test:", placeholder="Örn: 345 Mat Soru B. Sayfa 110-125 (Türev Test 1-4)")
                    o_tarih = st.date_input("Son Teslim Tarihi:")

                submit_odev = st.form_submit_button("➕ Ödevi Sınıfa Ata", type="primary")

                if submit_odev:
                    if o_kaynak.strip():
                        cursor.execute("INSERT INTO odevler (sinif, ders, konu_kaynak, son_tarih, eklenme_tarihi) VALUES (?, ?, ?, ?, DATE('now'))",
                                       (o_sinif, o_ders, o_kaynak.strip(), str(o_tarih)))
                        new_odev_id = cursor.lastrowid

                        # Sınıftaki tüm öğrencilere varsayılan 'Bekliyor' durumunu ekle
                        cursor.execute("SELECT DISTINCT ogrenci_adi_norm FROM ogrenci_sonuclari WHERE sinif = ?", (o_sinif,))
                        sinif_ogrencileri = cursor.fetchall()

                        for (o_norm,) in sinif_ogrencileri:
                            cursor.execute("INSERT OR IGNORE INTO odev_takip (odev_id, ogrenci_adi_norm, durum) VALUES (?, ?, 'Bekliyor')",
                                           (new_odev_id, o_norm))

                        conn.commit()
                        st.success(f"✅ Ödev {o_sinif} sınıfı için başarıyla tanımlandı! ({len(sinif_ogrencileri)} öğrenciye atandı)")
                    else:
                        st.warning("Lütfen ödev/kaynak detayını giriniz.")
        else:
            st.warning("Henüz sistemde sınıf kaydı bulunmuyor.")

    # --- TAB 2: SINIF ÖDEV KONTROLÜ ---
    with tab_o2:
        st.subheader("📋 Ödev Kontrol ve Durum Güncelleme")

        cursor.execute("SELECT odev_id, sinif, ders, konu_kaynak, son_tarih FROM odevler ORDER BY odev_id DESC")
        odev_rows = cursor.fetchall()

        if odev_rows:
            odev_dict = {f"[{o[1]}] {o[2]} - {o[3]} (Son Tarih: {o[4]})": o[0] for o in odev_rows}
            secilen_odev_label = st.selectbox("Kontrol Edilecek Ödevi Seçin:", list(odev_dict.keys()))
            secilen_odev_id = odev_dict[secilen_odev_label]

            # Ödeve ait öğrenci durumlarını getir
            q_durum = '''
            SELECT os.ogrenci_adi, os.ogrenci_adi_norm, ot.durum, ot.aciklama, ot.id as takip_id
            FROM odev_takip ot
            JOIN ogrenci_sonuclari os ON ot.ogrenci_adi_norm = os.ogrenci_adi_norm
            JOIN odevler o ON ot.odev_id = o.odev_id
            WHERE ot.odev_id = ? AND os.sinif = o.sinif
            GROUP BY os.ogrenci_adi_norm
            ORDER BY os.ogrenci_adi ASC
            '''
            df_kontrol = pd.read_sql_query(q_durum, conn, params=(secilen_odev_id,))

            if not df_kontrol.empty:
                st.info("💡 Her öğrencinin ödev durumunu aşağıdan seçip güncelleyebilirsiniz:")
                
                with st.form("odev_kontrol_form"):
                    durum_secimleri = {}
                    aciklama_inputs = {}

                    for idx, r in df_kontrol.iterrows():
                        c1, c2, c3 = st.columns([2, 1.5, 2.5])
                        with c1:
                            st.write(f"👤 **{r['ogrenci_adi']}**")
                        with c2:
                            current_idx = ["Yaptı", "Eksik Yaptı", "Yapmadı", "Bekliyor"].index(r['durum']) if r['durum'] in ["Yaptı", "Eksik Yaptı", "Yapmadı", "Bekliyor"] else 3
                            durum_secimleri[r['takip_id']] = st.selectbox(
                                "Durum", ["Yaptı", "Eksik Yaptı", "Yapmadı", "Bekliyor"], 
                                index=current_idx, key=f"d_{r['takip_id']}", label_visibility="collapsed"
                            )
                        with c3:
                            aciklama_inputs[r['takip_id']] = st.text_input(
                                "Not", value=r['aciklama'] if r['aciklama'] else "", 
                                placeholder="Not / Açıklama...", key=f"a_{r['takip_id']}", label_visibility="collapsed"
                            )
                        st.markdown("<hr style='margin:2px 0;'>", unsafe_allow_html=True)

                    if st.form_submit_button("💾 Tüm Sınıf Ödev Durumlarını Kaydet", type="primary"):
                        for t_id, d_val in durum_secimleri.items():
                            a_val = aciklama_inputs[t_id]
                            cursor.execute("UPDATE odev_takip SET durum = ?, aciklama = ? WHERE id = ?", (d_val, a_val, t_id))
                        conn.commit()
                        st.success("✅ Ödev durumları başarıyla güncellendi!")
                        st.rerun()
            else:
                st.warning("Bu ödeve kayıtlı öğrenci bulunamadı.")
        else:
            st.warning("Henüz tanımlanmış bir ödev bulunmuyor.")

    # --- TAB 3: İSTATİSTİKLER & ANALİZ ---
    with tab_o3:
        st.subheader("📊 Sınıf & Öğrenci Ödev Başarı İstatistikleri")

        cursor.execute("SELECT DISTINCT sinif FROM odevler ORDER BY sinif ASC")
        o_siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall()]
        sec_o_sinif = st.selectbox("İstatistik İçin Sınıf Seçin:", o_siniflar)

        if sec_o_sinif == "Tüm Sınıflar":
            q_stat = '''
            SELECT ot.durum, COUNT(*) as sayi
            FROM odev_takip ot
            GROUP BY ot.durum
            '''
            df_stat = pd.read_sql_query(q_stat, conn)
        else:
            q_stat = '''
            SELECT ot.durum, COUNT(*) as sayi
            FROM odev_takip ot
            JOIN odevler o ON ot.odev_id = o.odev_id
            WHERE o.sinif = ?
            GROUP BY ot.durum
            '''
            df_stat = pd.read_sql_query(q_stat, conn, params=(sec_o_sinif,))

        if not df_stat.empty:
            c_s1, c_s2 = st.columns([1, 1])
            with c_s1:
                fig_o, ax_o = plt.subplots(figsize=(5, 5))
                colors_o = {'Yaptı': '#27ae60', 'Eksik Yaptı': '#f39c12', 'Yapmadı': '#e74c3c', 'Bekliyor': '#95a5a6'}
                c_list = [colors_o.get(d, '#3498db') for d in df_stat['durum']]
                
                ax_o.pie(df_stat['sayi'], labels=df_stat['durum'], autopct='%1.1f%%', startangle=90, colors=c_list)
                ax_o.set_title(f"{sec_o_sinif} Ödev Tamamlama Oranları")
                st.pyplot(fig_o)

            with c_s2:
                st.subheader("🔴 En Çok Ödev Aksaması Olan Öğrenciler")
                q_top_unpaid = '''
                SELECT os.ogrenci_adi as 'Öğrenci', os.sinif as 'Sınıf', COUNT(*) as 'Yapılmayan Ödev Sayısı'
                FROM odev_takip ot
                JOIN ogrenci_sonuclari os ON ot.ogrenci_adi_norm = os.ogrenci_adi_norm
                WHERE ot.durum = 'Yapmadı'
                GROUP BY os.ogrenci_adi_norm
                ORDER BY COUNT(*) DESC LIMIT 10
                '''
                df_unpaid = pd.read_sql_query(q_top_unpaid, conn)
                if not df_unpaid.empty:
                    st.dataframe(df_unpaid, use_container_width=True)
                else:
                    st.success("🎉 Harika! Ödevini yapmayan öğrenci bulunmuyor.")

    conn.close()

# --- 4. MENÜ: ÖĞRENCİ ÖDEVLERİ & DURUMU (ÖĞRENCİ & VELİ) ---
elif secim == "📚 Ödevlerim & Ödev Durumu" and st.session_state['role'] in ['ogrenci', 'veli']:
    st.title("📚 Ödevlerim ve Soru Bankası Takibim")

    secilen_norm = st.session_state['user_info']['norm_adi']

    if secilen_norm:
        conn = sqlite3.connect("sinav_takip.db")
        
        q_my_odev = '''
        SELECT o.ders as 'Ders', o.konu_kaynak as 'Ödev / Kaynak / Test', o.son_tarih as 'Son Teslim Tarihi',
               ot.durum as 'Durum', ot.aciklama as 'Öğretmen Notu'
        FROM odev_takip ot
        JOIN odevler o ON ot.odev_id = o.odev_id
        WHERE ot.ogrenci_adi_norm = ?
        ORDER BY o.odev_id DESC
        '''
        df_my_odev = pd.read_sql_query(q_my_odev, conn, params=(secilen_norm,))

        if not df_my_odev.empty:
            yapti_s = len(df_my_odev[df_my_odev['Durum'] == 'Yaptı'])
            eksik_s = len(df_my_odev[df_my_odev['Durum'] == 'Eksik Yaptı'])
            yapmadi_s = len(df_my_odev[df_my_odev['Durum'] == 'Yapmadı'])
            bekliyor_s = len(df_my_odev[df_my_odev['Durum'] == 'Bekliyor'])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🟢 Tamamlanan", f"{yapti_s}")
            m2.metric("🟡 Eksik Yapılan", f"{eksik_s}")
            m3.metric("🔴 Yapılmayan", f"{yapmadi_s}")
            m4.metric("⚪ Kontrol Bekleyen", f"{bekliyor_s}")

            st.markdown("---")
            st.subheader("📋 Ödev Listesi ve Detayları")

            def highlight_durum(val):
                color = ''
                if val == 'Yaptı':
                    color = 'background-color: #c6f6d5; color: #22543d; font-weight: bold;'
                elif val == 'Eksik Yaptı':
                    color = 'background-color: #feebc8; color: #744210; font-weight: bold;'
                elif val == 'Yapmadı':
                    color = 'background-color: #fed7d7; color: #742a2a; font-weight: bold;'
                return color

            st.dataframe(df_my_odev.style.applymap(highlight_durum, subset=['Durum']), use_container_width=True)
        else:
            st.info("Henüz tarafınıza atanmış bir ödev bulunmuyor.")
        conn.close()
    else:
        st.error("Hesabınızla eşleşen öğrenci kaydı bulunamadı.")

# --- 5. MENÜ: VELİ BİLGİLENDİRME & TOPLU WHATSAPP/SMS ---
elif secim == "📱 Veli Bilgilendirme & WhatsApp/SMS" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("📱 Veli Bilgilendirme ve Toplu Gönderim Paneli")
    
    tab1, tab2 = st.tabs(["👤 Bireysel Gönderim", "🚀 Sınıf / Okul Geneli Toplu Gönderim"])
    
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    kurum_adi, _ = get_kurum_bilgileri()

    with tab1:
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
        ogrenciler = cursor.fetchall()
        
        if ogrenciler:
            ogr_dict = {f"{o[0]}": o[1] for o in ogrenciler}
            secilen_ogr = st.selectbox("Bilgilendirme Yapılacak Öğrenciyi Seçin:", list(ogr_dict.keys()))
            secilen_norm = ogr_dict[secilen_ogr]
            
            query = '''
            SELECT s.sinav_adi, os.tyt_puan, os.kurum_sirasi, os.toplam_net
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE os.ogrenci_adi_norm = ?
            ORDER BY s.tarih DESC, s.sinav_id DESC LIMIT 1
            '''
            cursor.execute(query, (secilen_norm,))
            last_exam = cursor.fetchone()
            
            cursor.execute("SELECT telefon FROM kullanicilar WHERE ogrenci_adi_norm = ? AND rol = 'veli' LIMIT 1", (secilen_norm,))
            tel_row = cursor.fetchone()
            default_tel = tel_row[0] if tel_row and tel_row[0] else ""
            
            if last_exam:
                sinav_adi, puan, sira, net = last_exam
                aktif_eksikler, _ = get_ogrenci_eksik_durumu(conn, secilen_norm)
                
                eksik_str = ""
                if aktif_eksikler:
                    eksik_list = [f"• {k} ({t} kez)" for k, t in aktif_eksikler[:2]]
                    eksik_str = "\n📌 Acil Müdahale Konuları:\n" + "\n".join(eksik_list)
                else:
                    eksik_str = "\n📌 Kritik eksik konusu bulunmuyor."

                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    phone_num = st.text_input("📱 Veli Telefon Numarası (Başında 90 ile):", value=default_tel, placeholder="905xxxxxxxxx")
                with col_t2:
                    mesaj_turu = st.selectbox("Mesaj Şablonu Seçin:", ["Özet Sınav Sonucu & Eksik Analizi", "Karne Giriş Bilgilendirmesi"])

                if mesaj_turu == "Özet Sınav Sonucu & Eksik Analizi":
                    default_msg = f"Sayın Velimiz,\n\n{kurum_adi} bünyesinde gerçekleştirilen *{sinav_adi}* denemesinde öğrencimiz *{secilen_ogr}*;\n\n📊 TYT Neti: *{net:.2f}*\n🎯 TYT Puanı: *{puan:.2f}*\n🏆 Kurum Sırası: *{sira}*{eksik_str}\n\nDetaylı gelişim karnesi için öğretmeninizle iletişime geçebilirsiniz."
                else:
                    default_msg = f"Sayın Velimiz,\n\nÖğrencimiz *{secilen_ogr}*'in *{sinav_adi}* deneme sınavı ve acil konu çalışma rotasını içeren güncel gelişim karnesi sistemimize yüklenmiştir.\n\nSisteme giriş yaparak gelişim grafiğini inceleyebilirsiniz.\n\nSaygılarımızla,\n*{kurum_adi}*"

                final_msg = st.text_area("✍️ Gönderilecek Mesaj Metni:", value=default_msg, height=180)
                encoded_msg = urllib.parse.quote(final_msg)
                clean_tel = re.sub(r'\D', '', phone_num)
                wa_url = f"https://wa.me/{clean_tel}?text={encoded_msg}" if clean_tel else f"https://wa.me/?text={encoded_msg}"

                st.markdown(f'''
                <a href="{wa_url}" target="_blank" style="text-decoration:none;">
                    <button style="width:100%; background-color:#25D366; color:white; border:none; padding:12px; font-size:16px; border-radius:8px; font-weight:bold; cursor:pointer;">
                        📲 WhatsApp İle Velisine Gönder
                    </button>
                </a>
                ''', unsafe_allow_html=True)

    with tab2:
        st.subheader("🚀 Sınıf / Okul Geneli Seri WhatsApp Gönderim Modülü")
        st.info("💡 **Nasıl Çalışır?** Filtrelediğiniz sınıftaki velilerin mesajları sırayla hazırlanır. Butonlara sırayla tıklayarak WhatsApp Web üzerinden saniyeler içinde tüm sınıfa gönderim yapabilirsiniz.")

        cursor.execute("SELECT sinav_adi FROM sinavlar ORDER BY tarih DESC")
        sinav_list = [s[0] for s in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
        sinif_list = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]

        if sinav_list:
            c_top1, c_top2 = st.columns(2)
            with c_top1:
                toplu_sinav = st.selectbox("Gönderilecek Sınavı Seçin:", sinav_list)
            with c_top2:
                toplu_sinif = st.selectbox("Gönderilecek Sınıfı Seçin:", sinif_list)

            if toplu_sinif == "Tüm Sınıflar":
                q_toplu = '''
                SELECT os.ogrenci_adi, os.ogrenci_adi_norm, os.sinif, os.toplam_net, os.tyt_puan, os.kurum_sirasi, k.telefon
                FROM ogrenci_sonuclari os
                JOIN sinavlar s ON os.sinav_id = s.sinav_id
                LEFT JOIN kullanicilar k ON (os.ogrenci_adi_norm = k.ogrenci_adi_norm AND k.rol = 'veli')
                WHERE s.sinav_adi = ?
                ORDER BY os.ogrenci_adi ASC
                '''
                df_toplu = pd.read_sql_query(q_toplu, conn, params=(toplu_sinav,))
            else:
                q_toplu = '''
                SELECT os.ogrenci_adi, os.ogrenci_adi_norm, os.sinif, os.toplam_net, os.tyt_puan, os.kurum_sirasi, k.telefon
                FROM ogrenci_sonuclari os
                JOIN sinavlar s ON os.sinav_id = s.sinav_id
                LEFT JOIN kullanicilar k ON (os.ogrenci_adi_norm = k.ogrenci_adi_norm AND k.rol = 'veli')
                WHERE s.sinav_adi = ? AND os.sinif = ?
                ORDER BY os.ogrenci_adi ASC
                '''
                df_toplu = pd.read_sql_query(q_toplu, conn, params=(toplu_sinav, toplu_sinif))

            st.write(f"📊 **Seçilen Kriterde Bulunan Öğrenci Sayısı:** {len(df_toplu)}")
            st.markdown("---")

            for idx, r in df_toplu.iterrows():
                norm_adi = r['ogrenci_adi_norm']
                ogr_adi = r['ogrenci_adi']
                tel = r['telefon'] if r['telefon'] else ""
                net = r['toplam_net']
                puan = r['tyt_puan']
                sira = int(r['kurum_sirasi'])

                aktif_eksikler, _ = get_ogrenci_eksik_durumu(conn, norm_adi)
                eksik_str = ""
                if aktif_eksikler:
                    eksik_list = [f"• {k} ({t} kez)" for k, t in aktif_eksikler[:2]]
                    eksik_str = "\n📌 Acil Müdahale Konuları:\n" + "\n".join(eksik_list)

                msg = f"Sayın Velimiz,\n\n{kurum_adi} bünyesinde gerçekleştirilen *{toplu_sinav}* denemesinde öğrencimiz *{ogr_adi}*;\n\n📊 TYT Neti: *{net:.2f}*\n🎯 TYT Puanı: *{puan:.2f}*\n🏆 Kurum Sırası: *{sira}*{eksik_str}\n\nDetaylı gelişim karnesini incelemek için portalımıza giriş yapabilirsiniz."
                
                enc_msg = urllib.parse.quote(msg)
                clean_t = re.sub(r'\D', '', str(tel))
                wa_link = f"https://wa.me/{clean_t}?text={enc_msg}" if clean_t else f"https://wa.me/?text={enc_msg}"

                c1, c2, c3, c4 = st.columns([2, 1.5, 2, 1.5])
                with c1:
                    st.write(f"👤 **{ogr_adi}** ({r['sinif']})")
                with c2:
                    st.write(f"📞 {tel if tel else '⚠️ Tel Yok'}")
                with c3:
                    st.caption(f"Net: {net:.2f} | Puan: {puan:.2f} | Sıra: {sira}")
                with c4:
                    st.markdown(f'''
                    <a href="{wa_link}" target="_blank" style="text-decoration:none;">
                        <button style="background-color:#25D366; color:white; border:none; padding:6px 12px; border-radius:6px; font-weight:bold; cursor:pointer; font-size:12px;">
                            📲 WhatsApp Aç
                        </button>
                    </a>
                    ''', unsafe_allow_html=True)
                st.markdown("<hr style='margin:4px 0;'>", unsafe_allow_html=True)

        else:
            st.warning("Henüz sistemde kayıtlı sınav bulunmuyor.")

    conn.close()

# --- 6. MENÜ: HEDEF BELİRLEME & TAKİP ---
elif secim in ["🎯 Hedef Belirleme & Takip", "🎯 Üniversite / Hedefim"]:
    st.title("🎯 Hedef Belirleme ve Net Projeksiyonu")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    if st.session_state['role'] in ['ogrenci', 'veli']:
        secilen_norm = st.session_state['user_info']['norm_adi']
        cursor.execute("SELECT ogrenci_adi FROM ogrenci_sonuclari WHERE ogrenci_adi_norm = ? LIMIT 1", (secilen_norm,))
        row = cursor.fetchone()
        secilen_ogr_adi = row[0] if row else "Öğrenci"
    else:
        cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
        ogrenciler = cursor.fetchall()
        if ogrenciler:
            ogr_dict = {f"{o[0]}": o[1] for o in ogrenciler}
            secilen_ogr_adi = st.selectbox("Hedefi Belirlenecek Öğrenciyi Seçin:", list(ogr_dict.keys()))
            secilen_norm = ogr_dict[secilen_ogr_adi]
        else:
            st.warning("Henüz sistemde öğrenci bulunmuyor.")
            secilen_norm = None

    if secilen_norm:
        hedef_data = get_ogrenci_hedef(secilen_norm)
        default_bolum = hedef_data['bolum'] if hedef_data else ""
        default_net = hedef_data['net'] if hedef_data else 85.0
        default_puan = hedef_data['puan'] if hedef_data else 420.0

        st.subheader(f"📌 {secilen_ogr_adi} - Hedef Tanımlama")
        
        with st.form("hedef_form"):
            c_h1, c_h2, c_h3 = st.columns(3)
            with c_h1:
                h_bolum = st.text_input("Hedef Üniversite & Bölüm:", value=default_bolum, placeholder="Örn: İTÜ Bilgisayar Müh.")
            with c_h2:
                h_net = st.number_input("Hedef TYT Toplam Net:", min_value=0.0, max_value=120.0, value=float(default_net), step=1.0)
            with c_h3:
                h_puan = st.number_input("Hedef TYT Puanı:", min_value=0.0, max_value=500.0, value=float(default_puan), step=5.0)

            submit_hedef = st.form_submit_button("🎯 Hedefi Kaydet", type="primary")

            if submit_hedef:
                cursor.execute('''
                INSERT INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ogrenci_adi_norm) DO UPDATE SET
                    hedef_bolum=excluded.hedef_bolum,
                    hedef_net=excluded.hedef_net,
                    hedef_puan=excluded.hedef_puan
                ''', (secilen_norm, h_bolum.strip(), h_net, h_puan))
                conn.commit()
                st.success("✅ Hedefler başarıyla güncellendi!")
                st.rerun()

        cursor.execute("SELECT toplam_net, tyt_puan FROM ogrenci_sonuclari WHERE ogrenci_adi_norm = ? ORDER BY id DESC LIMIT 1", (secilen_norm,))
        last_exam = cursor.fetchone()

        if last_exam and h_net > 0:
            st.markdown("---")
            st.subheader("📊 Hedef Projeksiyon Analizi")
            son_net = last_exam[0]
            son_puan = last_exam[1]
            fark_net = son_net - h_net

            m1, m2, m3 = st.columns(3)
            m1.metric("Son Sınav Netiniz", f"{son_net:.2f}")
            m2.metric("Hedeflenen Net", f"{h_net:.2f}")
            m3.metric("Net Açığı / Durum", f"{fark_net:+.2f}", delta=f"{fark_net:.2f}")

            if fark_net >= 0:
                st.balloons()
                st.success(f"🎉 Harika gidiyorsun! Son sınav netin ({son_net:.2f}), hedefin olan {h_net:.2f} netin üzerinde!")
            else:
                st.warning(f"💡 Hedefe ulaşmak için **{abs(fark_net):.2f} net** daha artırman gerekiyor. Eksik konularına odaklanarak bu farkı kapatabilirsin!")

    conn.close()

# --- 7. MENÜ: ÖĞRENCİ KENDİ KARNESİ ---
elif secim == "🎓 Gelişim & Analiz Karnem" and st.session_state['role'] in ['ogrenci', 'veli']:
    st.title(f"🎓 Öğrenci Gelişim Karnesi")
    secilen_norm = st.session_state['user_info']['norm_adi']
    if secilen_norm:
        conn = sqlite3.connect("sinav_takip.db")
        cursor = conn.cursor()
        cursor.execute("SELECT ogrenci_adi FROM ogrenci_sonuclari WHERE ogrenci_adi_norm = ? LIMIT 1", (secilen_norm,))
        row = cursor.fetchone()
        conn.close()
        ogr_display_name = row[0] if row else "Öğrenci"
        render_student_report(secilen_norm, ogr_display_name, allow_notes=False)
    else:
        st.error("Hesabınızla eşleşen öğrenci kaydı bulunamadı. Lütfen yönetimle iletişime geçin.")

# --- 8. MENÜ: GENEL OKUL DURUMU ---
elif secim == "🏫 Okul Genel Durumu & Dereceler" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🏫 Okul Genel Başarı Analizi ve Derece Listeleri")
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT sinav_adi FROM sinavlar")
    sinavlar = [s[0] for s in cursor.fetchall()]

    if sinavlar:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
        with col_s2:
            cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
            siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
            secilen_sinif = st.selectbox("Sınıf Filtresi:", siniflar)
        
        if secilen_sinif == "Tüm Sınıflar":
            query = '''
            SELECT os.kurum_sirasi as 'Sıra', os.ogrenci_no as 'No', os.ogrenci_adi as 'Öğrenci Adı', os.sinif as 'Sınıf',
                   os.turkce_net as 'Türkçe', os.sosyal_net as 'Sosyal', os.matematik_net as 'Matematik', os.fen_net as 'Fen',
                   os.toplam_net as 'Toplam Net', os.tyt_puan as 'TYT Puanı'
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ?
            ORDER BY os.kurum_sirasi ASC
            '''
            df_genel = pd.read_sql_query(query, conn, params=(secilen_sinav,))
        else:
            query = '''
            SELECT os.kurum_sirasi as 'Sıra', os.ogrenci_no as 'No', os.ogrenci_adi as 'Öğrenci Adı', os.sinif as 'Sınıf',
                   os.turkce_net as 'Türkçe', os.sosyal_net as 'Sosyal', os.matematik_net as 'Matematik', os.fen_net as 'Fen',
                   os.toplam_net as 'Toplam Net', os.tyt_puan as 'TYT Puanı'
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE s.sinav_adi = ? AND os.sinif = ?
            ORDER BY os.kurum_sirasi ASC
            '''
            df_genel = pd.read_sql_query(query, conn, params=(secilen_sinav, secilen_sinif))

        st.write(f"### 🏆 {secilen_sinav} Derece Listesi ({secilen_sinif})")
        st.dataframe(df_genel, use_container_width=True)

        excel_data = df_genel.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 Derece Listesini Excel/CSV Olarak İndir",
            data=excel_data,
            file_name=f"{secilen_sinav}_{secilen_sinif}_Derece_Listesi.csv",
            mime="text/csv"
        )
    conn.close()

# --- 9. MENÜ: RADAR VE DAĞILIM GRAFİKLERİ ---
elif secim == "🕸️ Sınıf Karşılaştırmalı Radar & Dağılım" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🕸️ Sınıf Bazlı Karşılaştırmalı Radar & Net Dağılım Analizi")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

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

                    query_detay = '''
                    SELECT os.sinif, os.toplam_net
                    FROM ogrenci_sonuclari os
                    JOIN sinavlar s ON os.sinav_id = s.sinav_id
                    WHERE s.sinav_adi = ? AND os.sinif IN ({})
                    '''.format(','.join(['?']*len(secilen_siniflar)))

                    df_detay = pd.read_sql_query(query_detay, conn, params=[secilen_sinav] + secilen_siniflar)

                    fig_box, ax_box = plt.subplots(figsize=(6, 5.5))
                    data_to_plot = [df_detay[df_detay['sinif'] == s]['toplam_net'].dropna().values for s in secilen_siniflar]
                    
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

    conn.close()

# --- 10. MENÜ: OKUL KONU ANALİZİ ---
elif secim == "🔥 Okul Konu/Kazanım Analizi" and st.session_state['role'] in ['admin', 'ogretmen']:
    st.title("🔥 Okul & Sınıf Geneli En Çok Yanlış Yapılan Konular")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT sinav_adi FROM sinavlar")
    sinavlar = ["Tüm Sınıvlar"] + [s[0] for s in cursor.fetchall()]

    col1, col2 = st.columns(2)
    with col1:
        secilen_sinav = st.selectbox("Sınav Seçiniz:", sinavlar)
    with col2:
        cursor.execute("SELECT DISTINCT sinif FROM ogrenci_sonuclari ORDER BY sinif ASC")
        siniflar = ["Tüm Sınıflar"] + [s[0] for s in cursor.fetchall() if s[0]]
        secilen_sinif = st.selectbox("Sınıf Seçiniz:", siniflar)

    if secilen_sinav == "Tüm Sınıvlar" and secilen_sinif == "Tüm Sınıflar":
        query = '''
        SELECT konu_kazanim as 'Konu / Kazanım', COUNT(*) as 'Yanlış/Boş Sayısı'
        FROM ogrenci_eksikleri
        GROUP BY konu_kazanim
        ORDER BY COUNT(*) DESC LIMIT 10
        '''
        df_konu = pd.read_sql_query(query, conn)
    else:
        query = '''
        SELECT oe.konu_kazanim as 'Konu / Kazanım', COUNT(*) as 'Yanlış/Boş Sayısı'
        FROM ogrenci_eksikleri oe
        JOIN sinavlar s ON oe.sinav_id = s.sinav_id
        JOIN ogrenci_sonuclari os ON (os.sinav_id = oe.sinav_id AND os.ogrenci_adi_norm = oe.ogrenci_adi_norm)
        WHERE (s.sinav_adi = ? OR ? = 'Tüm Sınıvlar') AND (os.sinif = ? OR ? = 'Tüm Sınıflar')
        GROUP BY oe.konu_kazanim
        ORDER BY COUNT(*) DESC LIMIT 10
        '''
        df_konu = pd.read_sql_query(query, conn, params=(secilen_sinav, secilen_sinav, secilen_sinif, secilen_sinif))

    if not df_konu.empty:
        c1, c2 = st.columns([1.2, 0.8])
        with c1:
            st.subheader("📊 En Çok Yanlış Yapılan İlk 10 Konu")
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.barh(df_konu['Konu / Kazanım'], df_konu['Yanlış/Boş Sayısı'], color='#e74c3c')
            ax.invert_yaxis()
            ax.set_xlabel("Yanlış/Boş Yapan Öğrenci Sayısı")
            ax.grid(True, linestyle='--', alpha=0.5)
            st.pyplot(fig)

        with c2:
            st.subheader("📋 Detaylı Konu Listesi")
            st.dataframe(df_konu, use_container_width=True)

    conn.close()

# --- 11. MENÜ: ÖĞRENCİ & VELİ HESAP YÖNETİMİ ---
elif secim == "👥 Öğrenci & Veli Hesap Yönetimi" and st.session_state['role'] == 'admin':
    st.title("👥 Öğrenci & Veli Hesap Tanımlama Paneli")

    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT ogrenci_adi, ogrenci_adi_norm FROM ogrenci_sonuclari ORDER BY ogrenci_adi ASC")
    ogrenciler = cursor.fetchall()

    if ogrenciler:
        ogr_dict = {f"{o[0]}": o[1] for o in ogrenciler}
        
        st.subheader("➕ Yeni Öğrenci veya Veli Hesabı Oluştur")
        col1, col2 = st.columns(2)
        
        with col1:
            secilen_ogr = st.selectbox("Hesabın Bağı / İlişkili Olduğu Öğrenci:", list(ogr_dict.keys()))
            hesap_turu = st.selectbox("Hesap Türü / Rol:", ["ogrenci", "veli"])
            telefon_no = st.text_input("Veli Telefon Numarası (Başında 90 ile):", placeholder="Örn: 905321234567")

        with col2:
            yeni_username = st.text_input("Kullanıcı Adı:", placeholder="Örn: ahmet123 veya ahmet_veli")
            yeni_password = st.text_input("Şifre:", type="password", value="123456")

        if st.button("➕ Hesabı Oluştur", type="primary"):
            if yeni_username and yeni_password:
                try:
                    norm_adi = ogr_dict[secilen_ogr]
                    cursor.execute(
                        "INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon) VALUES (?, ?, ?, ?, ?)",
                        (yeni_username.strip(), yeni_password.strip(), hesap_turu, norm_adi, telefon_no.strip())
                    )
                    conn.commit()
                    st.success(f"✅ '{secilen_ogr}' öğrencisi için **{hesap_turu.upper()}** hesabı başarıyla oluşturuldu!")
                except sqlite3.IntegrityError:
                    st.error("⚠️ Bu kullanıcı adı zaten kullanılıyor! Lütfen başka bir kullanıcı adı girin.")
            else:
                st.warning("Lütfen kullanıcı adı ve şifre alanlarını doldurun.")

        st.markdown("---")
        st.subheader("🔑 Unutulan Şifreyi Sıfırlama / Güncelleme")
        
        cursor.execute("SELECT kullanici_adi, rol FROM kullanicilar WHERE rol IN ('ogrenci', 'veli') ORDER BY kullanici_adi ASC")
        kayitli_kullanicilar = cursor.fetchall()
        
        if kayitli_kullanicilar:
            c_u1, c_u2 = st.columns(2)
            with c_u1:
                sifre_reset_user = st.selectbox("Şifresi Değiştirilecek Kullanıcı:", [f"{k[0]} ({k[1]})" for k in kayitli_kullanicilar])
            with c_u2:
                sifre_reset_newpass = st.text_input("Yeni Şifre Belirle:", type="password", key="reset_pass")

            if st.button("🔄 Şifreyi Güncelle", type="primary"):
                if sifre_reset_newpass:
                    target_username = sifre_reset_user.split(" (")[0]
                    cursor.execute("UPDATE kullanicilar SET sifre = ? WHERE kullanici_adi = ?", (sifre_reset_newpass.strip(), target_username))
                    conn.commit()
                    st.success(f"✅ **{target_username}** kullanıcısının şifresi başarıyla güncellendi!")
                else:
                    st.warning("Lütfen yeni şifreyi girin.")

        st.markdown("---")
        st.subheader("📋 Sistemde Kayıtlı Kullanıcı Hesapları")
        
        users_df = pd.read_sql_query("SELECT id, kullanici_adi, rol, ogrenci_adi_norm, telefon FROM kullanicilar WHERE rol IN ('ogrenci', 'veli')", conn)
        st.dataframe(users_df, use_container_width=True)

        silinecek_user_id = st.number_input("Silmek İstediğiniz Kullanıcı ID (Hesap ID):", min_value=1, step=1)
        if st.button("🗑️ Hesabı Sil"):
            cursor.execute("DELETE FROM kullanicilar WHERE id = ?", (silinecek_user_id,))
            conn.commit()
            st.success("Hesap silindi.")
            st.rerun()

    else:
        st.warning("Sistemde henüz kayıtlı öğrenci verisi yok. Önce bir sınav yüklemelisiniz.")
    
    conn.close()

# --- 12. MENÜ: KURUM AYARLARI VE LOGO ---
elif secim == "⚙️ Kurum Ayarları & Logo" and st.session_state['role'] == 'admin':
    st.title("⚙️ Kurum ve Logo Ayarları")

    mevcut_adi, mevcut_logo = get_kurum_bilgileri()
    col1, col2 = st.columns([1, 1])

    with col1:
        yeni_kurum_adi = st.text_input("Kurum Adı:", value=mevcut_adi)
        uploaded_logo = st.file_uploader("Okul/Kurum Logosu Yükleyin (PNG veya JPG):", type=["png", "jpg", "jpeg"])

        if st.button("💾 Kurum Bilgilerini ve Logoyu Kaydet", type="primary"):
            conn = sqlite3.connect("sinav_takip.db")
            cursor = conn.cursor()

            if uploaded_logo is not None:
                logo_bytes = uploaded_logo.read()
                logo_b64 = base64.b64encode(logo_bytes).decode('utf-8')
            else:
                logo_b64 = mevcut_logo

            cursor.execute('''
            INSERT INTO kurum_ayarlari (id, kurum_adi, logo_base64) 
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET kurum_adi=excluded.kurum_adi, logo_base64=excluded.logo_base64
            ''', (yeni_kurum_adi, logo_b64))

            conn.commit()
            conn.close()
            st.success("✅ Kaydedildi!")
            st.rerun()

    with col2:
        st.subheader("🖼️ Kayıtlı Logo")
        if mevcut_logo:
            st.image(base64.b64decode(mevcut_logo), width=220)

# --- 13. MENÜ: SINAV SİLME ---
elif secim == "🗑️ Sınav Yönetimi & Silme" and st.session_state['role'] == 'admin':
    st.title("🗑️ Sınav Yönetim ve Silme Paneli")
    conn = sqlite3.connect("sinav_takip.db")
    cursor = conn.cursor()

    cursor.execute("SELECT sinav_id, sinav_adi, tarih FROM sinavlar ORDER BY tarih DESC")
    sinavlar = cursor.fetchall()

    if sinavlar:
        sinav_dict = {f"{s[1]} ({s[2]})": s[0] for s in sinavlar}
        silinecek_label = st.selectbox("Silinecek Sınavı Seçin:", list(sinav_dict.keys()))
        silinecek_id = sinav_dict[silinecek_label]

        if st.button("🔴 Seçilen Sınavı Sil", type="primary"):
            try:
                cursor.execute("DELETE FROM ogrenci_sonuclari WHERE sinav_id = ?", (silinecek_id,))
                cursor.execute("DELETE FROM ogrenci_eksikleri WHERE sinav_id = ?", (silinecek_id,))
                cursor.execute("DELETE FROM sinavlar WHERE sinav_id = ?", (silinecek_id,))
                conn.commit()
                st.success("✅ Sınav silindi.")
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")
    conn.close()