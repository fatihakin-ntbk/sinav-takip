import base64
import datetime
import io
import os
import re
import sqlite3
import urllib.parse
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypdf
import streamlit as st

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="YKS Sınav Takip & Analiz Paneli", page_icon="🎓", layout="wide"
)

# --- ŞİFRELEME YARDIMCISI ---
import hashlib


def hash_sifre(sifre):
  return hashlib.sha256(sifre.encode("utf-8")).hexdigest()


# --- TÜRKÇE KARAKTER NORMALEŞTİRME ---
def tr_normalize(text):
  if not text:
    return ""
  text = str(text).upper().strip()
  tr_map = {"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C"}
  for k, v in tr_map.items():
    text = text.replace(k, v)
  return " ".join(text.split())


# --- VERİTABANI OLUŞTURMA & GÜNCELLEME ---
def init_db():
  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  # Ana Öğrenci Listesi
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS ogrenciler (
        ogrenci_id INTEGER PRIMARY KEY AUTOINCREMENT,
        okul_no TEXT UNIQUE,
        ad_soyad TEXT,
        ad_soyad_norm TEXT UNIQUE,
        sinif TEXT,
        veli_telefon TEXT
    )""")

  # Sınavlar Tablosu (Sınav Türü: TYT / AYT)
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS sinavlar (
        sinav_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_adi TEXT UNIQUE,
        sinav_turu TEXT DEFAULT 'TYT',
        tarih TEXT
    )""")

  # Öğrenci Sonuçları Tablosu (TYT + AYT Tüm Sütunlar)
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS ogrenci_sonuclari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_no TEXT,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        sinif TEXT,
        tyt_puan REAL,
        say_puan REAL,
        ea_puan REAL,
        soz_puan REAL,
        dil_puan REAL,
        kurum_sirasi INTEGER,
        turkce_net REAL,
        sosyal_net REAL,
        matematik_net REAL,
        fen_net REAL,
        ayt_mat_net REAL,
        ayt_fiz_net REAL,
        ayt_kim_net REAL,
        ayt_biy_net REAL,
        ayt_edb_net REAL,
        ayt_tar1_net REAL,
        ayt_cog1_net REAL,
        ayt_tar2_net REAL,
        ayt_cog2_net REAL,
        ayt_fel_net REAL,
        ayt_din_net REAL,
        ayt_dil_net REAL,
        toplam_net REAL,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )""")

  # Öğrenci Eksikleri Tablosu
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS ogrenci_eksikleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sinav_id INTEGER,
        ogrenci_adi TEXT,
        ogrenci_adi_norm TEXT,
        ders TEXT,
        konu_kazanim TEXT,
        soru_nolari TEXT,
        FOREIGN KEY (sinav_id) REFERENCES sinavlar (sinav_id) ON DELETE CASCADE
    )""")

  # Kurum Ayarları
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS kurum_ayarlari (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kurum_adi TEXT,
        logo_base64 TEXT
    )""")

  # Kullanıcılar Tablosu
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_adi TEXT UNIQUE,
        sifre TEXT,
        rol TEXT,
        ogrenci_adi_norm TEXT,
        telefon TEXT
    )""")

  # Öğrenci Hedefleri Tablosu
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS ogrenci_hedefleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT UNIQUE,
        hedef_bolum TEXT,
        hedef_net REAL,
        hedef_puan REAL,
        hedef_puan_turu TEXT DEFAULT 'TYT'
    )""")

  # Ödevler Tablosu
  cursor.execute("""
    CREATE TABLE IF NOT EXISTS odevler (
        odev_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ogrenci_adi_norm TEXT,
        ders TEXT,
        odev_tanimi TEXT,
        son_tarih TEXT,
        durum TEXT DEFAULT 'Bekliyor',
        ogretmen_notu TEXT
    )""")

  # Varsayılan Hesaplar
  admin_hash = hash_sifre("admin123")
  cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = 'admin'")
  if not cursor.fetchone():
    cursor.execute(
        "INSERT INTO kullanicilar (kullanici_adi, sifre, rol,"
        " ogrenci_adi_norm, telefon) VALUES ('admin', ?, 'admin', NULL, '')",
        (admin_hash,),
    )

  conn.commit()
  conn.close()


init_db()


# --- YKS PUAN HESAPLAMA MOTORU ---
def hesapla_yks_puanlari(tyt_netler, ayt_netler, obp=80.0):
  # TYT Ham Puanı (100 Taban Puanlı)
  tyt_ham = 100 + (
      tyt_netler.get("turkce", 0.0) * 3.3
      + tyt_netler.get("sosyal", 0.0) * 3.4
      + tyt_netler.get("matematik", 0.0) * 3.3
      + tyt_netler.get("fen", 0.0) * 3.4
  )

  # AYT Ham Puanlar (%40 TYT + %60 AYT)
  say_ham = (
      tyt_ham * 0.4
      + (
          ayt_netler.get("mat", 0.0) * 3.0
          + ayt_netler.get("fiz", 0.0) * 2.8
          + ayt_netler.get("kim", 0.0) * 3.0
          + ayt_netler.get("biy", 0.0) * 3.0
      )
      * 0.6
  )

  ea_ham = (
      tyt_ham * 0.4
      + (
          ayt_netler.get("mat", 0.0) * 3.0
          + ayt_netler.get("edb", 0.0) * 3.0
          + ayt_netler.get("tar1", 0.0) * 2.8
          + ayt_netler.get("cog1", 0.0) * 3.3
      )
      * 0.6
  )

  soz_ham = (
      tyt_ham * 0.4
      + (
          ayt_netler.get("edb", 0.0) * 3.0
          + ayt_netler.get("tar1", 0.0) * 2.8
          + ayt_netler.get("cog1", 0.0) * 3.3
          + ayt_netler.get("tar2", 0.0) * 2.9
          + ayt_netler.get("cog2", 0.0) * 2.9
          + ayt_netler.get("fel", 0.0) * 3.0
          + ayt_netler.get("din", 0.0) * 3.3
      )
      * 0.6
  )

  dil_ham = tyt_ham * 0.4 + (ayt_netler.get("dil", 0.0) * 3.0) * 0.6

  # OBP Eklenmiş Puanlar (OBP * 0.6)
  obp_puan = obp * 0.6

  return {
      "TYT": round(tyt_ham, 2),
      "SAY": round(say_ham + obp_puan, 2),
      "EA": round(ea_ham + obp_puan, 2),
      "SOZ": round(soz_ham + obp_puan, 2),
      "DİL": round(dil_ham + obp_puan, 2),
  }


# --- WHATSAPP MEAJ OLUŞTURUCU ---
def format_whatsapp_link(telefon, mesaj):
  if not telefon:
    return ""
  tel_clean = re.sub(r"\D", "", str(telefon))
  if len(tel_clean) == 10:
    tel_clean = "90" + tel_clean
  elif len(tel_clean) == 11 and tel_clean.startswith("0"):
    tel_clean = "90" + tel_clean[1:]
  encoded_msg = urllib.parse.quote(mesaj)
  return f"https://wa.me/{tel_clean}?text={encoded_msg}"


# --- PDF EKSİK KAZANIM OKUMA ---
def parse_pdf_eksikleri(pdf_file):
  try:
    reader = pypdf.PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
      text += page.extract_text() + "\n"

    eksikler = []
    lines = text.split("\n")
    current_ogrenci = None

    for line in lines:
      line = line.strip()
      if not line:
        continue
      if "Öğrenci:" in line or "Sayın" in line or "Adı Soyadı:" in line:
        current_ogrenci = tr_normalize(
            line.split(":")[-1].replace("Sayın", "").strip()
        )
      elif " - " in line or ":" in line:
        if current_ogrenci:
          parts = line.split("-") if "-" in line else line.split(":")
          if len(parts) >= 2:
            ders = parts[0].strip()
            kazanim = parts[1].strip()
            eksikler.append({
                "ogrenci_adi_norm": current_ogrenci,
                "ders": ders,
                "kazanim": kazanim,
            })
    return eksikler
  except Exception as e:
    st.error(f"PDF Okunurken Hata Oluştu: {e}")
    return []


# --- OTURUM YÖNETİMİ ---
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "user_role" not in st.session_state:
  st.session_state.user_role = None
if "username" not in st.session_state:
  st.session_state.username = None
if "ogrenci_adi_norm" not in st.session_state:
  st.session_state.ogrenci_adi_norm = None

# --- GİRİŞ EKRANI ---
if not st.session_state.logged_in:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.title("🎓 YKS Sınav Takip Portalı")
    st.subheader("Giriş Yap")
    username_input = st.text_input("Kullanıcı Adı veya Okul No")
    password_input = st.text_input("Şifre", type="password")

    if st.button("Giriş Yap", use_container_width=True):
      conn = sqlite3.connect("sinav_takip.db")
      cursor = conn.cursor()
      hashed_pwd = hash_sifre(password_input)

      cursor.execute(
          "SELECT * FROM kullanicilar WHERE kullanici_adi = ? AND sifre = ?",
          (username_input, hashed_pwd),
      )
      user = cursor.fetchone()

      # Eski düz metin şifreler için geriye dönük uyumluluk
      if not user:
        cursor.execute(
            "SELECT * FROM kullanicilar WHERE kullanici_adi = ? AND sifre = ?",
            (username_input, password_input),
        )
        user = cursor.fetchone()

      conn.close()

      if user:
        st.session_state.logged_in = True
        st.session_state.username = user[1]
        st.session_state.user_role = user[3]
        st.session_state.ogrenci_adi_norm = user[4]
        st.success("Giriş Başarılı!")
        st.rerun()
      else:
        st.error("Kullanıcı adı veya şifre hatalı!")
  st.stop()

# --- YAN MENÜ & ARAYÜZ ---
with st.sidebar:
  st.title("🎓 Navigasyon")
  st.write(f"**Kullanıcı:** {st.session_state.username}")
  st.write(f"**Yetki:** {st.session_state.user_role.upper()}")

  if st.session_state.user_role == "admin":
    menu = st.radio(
        "Menü",
        [
            "📊 Genel Okul Analizi",
            "👤 Öğrenci Karnesi",
            "📥 Sınav Yükle (Excel/PDF)",
            "🧮 YKS Puan & Sıralama Hesaplayıcı",
            "🎯 Hedef Belirleme",
            "📚 Ödev Takip Sistemi",
            "👥 Öğrenci & Kullanıcı Yönetimi",
            "⚙️ Kurum Ayarları",
        ],
    )
  elif st.session_state.user_role == "ogretmen":
    menu = st.radio(
        "Menü",
        [
            "📊 Genel Okul Analizi",
            "👤 Öğrenci Karnesi",
            "🧮 YKS Puan & Sıralama Hesaplayıcı",
            "🎯 Hedef Belirleme",
            "📚 Ödev Takip Sistemi",
        ],
    )
  else:  # Öğrenci / Veli
    menu = st.radio(
        "Menü",
        [
            "👤 Öğrenci Karnesi",
            "🧮 YKS Puan & Sıralama Hesaplayıcı",
            "🎯 Hedef Belirleme",
            "📚 Ödev Takip Sistemi",
        ],
    )

  if st.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state.logged_in = False
    st.rerun()

# --- 1. GENEL OKUL ANALİZİ ---
if menu == "📊 Genel Okul Analizi":
  st.header("📊 Okul Geneli Sınav Analizi")
  conn = sqlite3.connect("sinav_takip.db")

  sinavlar_df = pd.read_sql_query("SELECT * FROM sinavlar", conn)
  if sinavlar_df.empty:
    st.info("Sistemde henüz yüklenmiş sınav bulunmuyor.")
    conn.close()
  else:
    secilen_sinav = st.selectbox(
        "Analiz Edilecek Sınavı Seçin", sinavlar_df["sinav_adi"].tolist()
    )
    sinav_id = sinavlar_df[sinavlar_df["sinav_adi"] == secilen_sinav][
        "sinav_id"
    ].values[0]
    sinav_turu = sinavlar_df[sinavlar_df["sinav_adi"] == secilen_sinav][
        "sinav_turu"
    ].values[0]

    df_sonuc = pd.read_sql_query(
        f"SELECT * FROM ogrenci_sonuclari WHERE sinav_id = {sinav_id}", conn
    )

    if not df_sonuc.empty:
      c1, c2, c3, c4 = st.columns(4)
      c1.metric("Giren Öğrenci", len(df_sonuc))
      c2.metric("Sınav Türü", sinav_turu)

      if sinav_turu == "TYT":
        c3.metric(
            "Ortalama TYT Net", round(df_sonuc["toplam_net"].mean(), 2)
        )
        c4.metric("Ortalama TYT Puan", round(df_sonuc["tyt_puan"].mean(), 2))
      else:
        c3.metric(
            "Ortalama AYT Mat Net", round(df_sonuc["ayt_mat_net"].mean(), 2)
        )
        c4.metric(
            "Ortalama SAY Puan", round(df_sonuc["say_puan"].mean(), 2)
        )

      st.subheader("🏆 Sınav Derece Listesi")
      gosterilecek_sutunlar = [
          "kurum_sirasi",
          "ogrenci_no",
          "ogrenci_adi",
          "sinif",
      ]
      if sinav_turu == "TYT":
        gosterilecek_sutunlar += [
            "turkce_net",
            "sosyal_net",
            "matematik_net",
            "fen_net",
            "toplam_net",
            "tyt_puan",
        ]
      else:
        gosterilecek_sutunlar += [
            "ayt_mat_net",
            "ayt_fiz_net",
            "ayt_kim_net",
            "ayt_biy_net",
            "ayt_edb_net",
            "say_puan",
            "ea_puan",
        ]

      st.dataframe(
          df_sonuc[gosterilecek_sutunlar].sort_values("kurum_sirasi"),
          use_container_width=True,
      )

      st.subheader("📈 Ders Başarı Ortalamaları")
      if sinav_turu == "TYT":
        ders_ort = df_sonuc[
            ["turkce_net", "sosyal_net", "matematik_net", "fen_net"]
        ].mean()
      else:
        ders_ort = df_sonuc[[
            "ayt_mat_net",
            "ayt_fiz_net",
            "ayt_kim_net",
            "ayt_biy_net",
            "ayt_edb_net",
            "ayt_tar1_net",
            "ayt_cog1_net",
        ]].mean()

      fig, ax = plt.subplots(figsize=(10, 4))
      ders_ort.plot(kind="bar", ax=ax, color="#1f77b4")
      plt.title("Ders Bazlı Ortalamalar")
      plt.ylabel("Net Ortalaması")
      st.pyplot(fig)

    conn.close()

# --- 2. ÖĞRENCİ KARNESİ ---
elif menu == "👤 Öğrenci Karnesi":
  st.header("👤 Bireysel Öğrenci Karnesi ve Gelişim Analizi")
  conn = sqlite3.connect("sinav_takip.db")

  if st.session_state.user_role in ["admin", "ogretmen"]:
    ogrenciler_df = pd.read_sql_query("SELECT * FROM ogrenciler", conn)
    secilen_ogr_norm = st.selectbox(
        "Öğrenci Seçin", ogrenciler_df["ad_soyad_norm"].tolist()
    )
  else:
    secilen_ogr_norm = st.session_state.ogrenci_adi_norm

  if secilen_ogr_norm:
    ogr_sonuc = pd.read_sql_query(
        f"""
            SELECT s.sinav_adi, s.sinav_turu, s.tarih, os.* 
            FROM ogrenci_sonuclari os
            JOIN sinavlar s ON os.sinav_id = s.sinav_id
            WHERE os.ogrenci_adi_norm = '{secilen_ogr_norm}'
            ORDER BY s.sinav_id ASC
        """,
        conn,
    )

    if ogr_sonuc.empty:
      st.warning("Bu öğrenciye ait kayıtlı sınav bulunamadı.")
    else:
      st.subheader(
          f"📌 {ogr_sonuc['ogrenci_adi'].iloc[0]} - Sınav Gelişim Raporu"
      )

      tab1, tab2, tab3 = st.tabs(
          ["📈 TYT Analizi", "📊 AYT Analizi", "❌ Eksik Konular & WhatsApp"]
      )

      with tab1:
        tyt_df = ogr_sonuc[ogr_sonuc["sinav_turu"] == "TYT"]
        if not tyt_df.empty:
          st.dataframe(
              tyt_df[[
                  "sinav_adi",
                  "turkce_net",
                  "sosyal_net",
                  "matematik_net",
                  "fen_net",
                  "toplam_net",
                  "tyt_puan",
                  "kurum_sirasi",
              ]],
              use_container_width=True,
          )

          fig, ax = plt.subplots(figsize=(10, 3.5))
          ax.plot(
              tyt_df["sinav_adi"],
              tyt_df["toplam_net"],
              marker="o",
              linewidth=2,
              color="g",
              label="TYT Net",
          )
          plt.title("TYT Toplam Net Gelişimi")
          plt.grid(True)
          st.pyplot(fig)
        else:
          st.info("Kayıtlı TYT sınavı bulunmuyor.")

      with tab2:
        ayt_df = ogr_sonuc[ogr_sonuc["sinav_turu"] == "AYT"]
        if not ayt_df.empty:
          st.dataframe(
              ayt_df[[
                  "sinav_adi",
                  "ayt_mat_net",
                  "ayt_fiz_net",
                  "ayt_kim_net",
                  "ayt_biy_net",
                  "ayt_edb_net",
                  "say_puan",
                  "ea_puan",
              ]],
              use_container_width=True,
          )

          fig2, ax2 = plt.subplots(figsize=(10, 3.5))
          ax2.plot(
              ayt_df["sinav_adi"],
              ayt_df["say_puan"],
              marker="s",
              color="b",
              label="SAY Puan",
          )
          ax2.plot(
              ayt_df["sinav_adi"],
              ayt_df["ea_puan"],
              marker="^",
              color="orange",
              label="EA Puan",
          )
          plt.title("AYT Puan Gelişimi")
          plt.legend()
          plt.grid(True)
          st.pyplot(fig2)
        else:
          st.info("Kayıtlı AYT sınavı bulunmuyor.")

      with tab3:
        eksik_df = pd.read_sql_query(
            f"""
                SELECT s.sinav_adi, oe.ders, oe.konu_kazanim 
                FROM ogrenci_eksikleri oe
                JOIN sinavlar s ON oe.sinav_id = s.sinav_id
                WHERE oe.ogrenci_adi_norm = '{secilen_ogr_norm}'
            """,
            conn,
        )

        if not eksik_df.empty:
          st.write("### 🎯 Tespit Edilen Konu Eksikleri")
          st.dataframe(eksik_df, use_container_width=True)

          # Velayete Bildirim Hazırlama
          ogr_info = pd.read_sql_query(
              "SELECT veli_telefon FROM ogrenciler WHERE ogrenci_adi_norm ="
              f" '{secilen_ogr_norm}'",
              conn,
          )
          tel = (
              ogr_info["veli_telefon"].iloc[0] if not ogr_info.empty else ""
          )

          mesaj = (
              f"Sayın Velimiz, Öğrencimiz {ogr_sonuc['ogrenci_adi'].iloc[0]}'in"
              f" son sınav neti: {ogr_sonuc['toplam_net'].iloc[-1]}. Eksik"
              " konuları tespit edilmiştir."
          )
          wa_url = format_whatsapp_link(tel, mesaj)
          if wa_url:
            st.markdown(
                f'<a href="{wa_url}" target="_blank"><button'
                ' style="background-color:#25D366; color:white; border:none;'
                " padding:10px 20px; border-radius:5px;"
                ' cursor:pointer;">📲 Velisine WhatsApp Bilgilendirmesi'
                " Gönder</button></a>",
                unsafe_allow_html=True,
            )
        else:
          st.info("Eksik kazanım kaydı bulunmamaktadır.")

  conn.close()

# --- 3. SINAV YÜKLE ---
elif menu == "📥 Sınav Yükle (Excel/PDF)":
  st.header("📥 Sınav Sonuçları ve PDF Eksik Dosyası Yükleme")

  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  sinav_adi = st.text_input("Sınav Adı (Örn: Özdebir TYT-1 veya Bilgi Sarmal AYT-2)")
  sinav_turu = st.selectbox("Sınav Türü", ["TYT", "AYT"])
  tarih = st.date_input("Sınav Tarihi", datetime.date.today())

  st.subheader("1. Excel Sınav Sonuç Dosyası")
  excel_file = st.file_uploader(
      "Sınav Sonuç Excel Dosyasını Yükleyin", type=["xlsx", "xls"]
  )

  st.subheader("2. PDF Kazanım Eksik Dosyası (Opsiyonel)")
  pdf_file = st.file_uploader(
      "Sınav Eksik Kazanım PDF Dosyasını Yükleyin", type=["pdf"]
  )

  if st.button("🚀 Sınavı Sistem Kaydet", use_container_width=True):
    if not sinav_adi or not excel_file:
      st.error("Lütfen Sınav Adını ve Excel Dosyasını Eksiksiz Yükleyin!")
    else:
      try:
        # 1. Sınavı Oluştur
        cursor.execute(
            "INSERT OR REPLACE INTO sinavlar (sinav_adi, sinav_turu, tarih)"
            " VALUES (?, ?, ?)",
            (sinav_adi, sinav_turu, str(tarih)),
        )
        sinav_id = cursor.lastrowid

        # 2. Excel Oku ve İşle
        df = pd.read_excel(excel_file)
        df.columns = [tr_normalize(c) for c in df.columns]

        def get_val(row, *col_names):
          for name in col_names:
            norm_name = tr_normalize(name)
            for c in row.index:
              if norm_name in c:
                return row[c]
          return 0.0

        for idx, row in df.iterrows():
          ogr_no = str(get_val(row, "NO", "OGRENCI NO", "OKUL NO"))
          ad_soyad = str(get_val(row, "AD SOYAD", "ISIM", "OGRENCI ADI"))
          ad_norm = tr_normalize(ad_soyad)
          sinif = str(get_val(row, "SINIF", "SUBE"))

          # Ogrenciyi kayıt et (Yoksa)
          cursor.execute(
              "INSERT OR IGNORE INTO ogrenciler (okul_no, ad_soyad,"
              " ad_soyad_norm, sinif) VALUES (?, ?, ?, ?)",
              (ogr_no, ad_soyad, ad_norm, sinif),
          )

          # Netleri Al
          t_net = float(get_val(row, "TURKCE NET", "TR NET", "TURKCE"))
          s_net = float(get_val(row, "SOSYAL NET", "SOS NET", "SOSYAL"))
          m_net = float(get_val(row, "MATEMATIK NET", "MAT NET", "MATEMATIK"))
          f_net = float(get_val(row, "FEN NET", "FEN"))

          # AYT Netleri
          ayt_mat = float(get_val(row, "AYT MAT", "MAT 2"))
          ayt_fiz = float(get_val(row, "FIZIK NET", "FIZIK"))
          ayt_kim = float(get_val(row, "KIMYA NET", "KIMYA"))
          ayt_biy = float(get_val(row, "BIYOLOJI NET", "BIYOLOJI"))
          ayt_edb = float(get_val(row, "EDEBIYAT NET", "EDB"))

          tyt_p = float(get_val(row, "TYT PUAN", "PUAN"))
          say_p = float(get_val(row, "SAY PUAN", "SAYISAL PUAN"))
          ea_p = float(get_val(row, "EA PUAN", "ESIT AGIRLIK"))
          sira = int(get_val(row, "SIRA", "KURUM SIRA", "DERECE"))
          top_net = float(get_val(row, "TOPLAM NET", "NET"))

          cursor.execute(
              """
                        INSERT INTO ogrenci_sonuclari (
                            sinav_id, ogrenci_no, ogrenci_adi, ogrenci_adi_norm, sinif,
                            tyt_puan, say_puan, ea_puan, kurum_sirasi,
                            turkce_net, sosyal_net, matematik_net, fen_net,
                            ayt_mat_net, ayt_fiz_net, ayt_kim_net, ayt_biy_net, ayt_edb_net,
                            toplam_net
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
              (
                  sinav_id,
                  ogr_no,
                  ad_soyad,
                  ad_norm,
                  sinif,
                  tyt_p,
                  say_p,
                  ea_p,
                  sira,
                  t_net,
                  s_net,
                  m_net,
                  f_net,
                  ayt_mat,
                  ayt_fiz,
                  ayt_kim,
                  ayt_biy,
                  ayt_edb,
                  top_net,
              ),
          )

        # 3. PDF Eksik Okuma
        if pdf_file:
          eksikler = parse_pdf_eksikleri(pdf_file)
          for eksik in eksikler:
            cursor.execute(
                """
                            INSERT INTO ogrenci_eksikleri (sinav_id, ogrenci_adi, ogrenci_adi_norm, ders, konu_kazanim)
                            VALUES (?, ?, ?, ?, ?)
                        """,
                (
                    sinav_id,
                    eksik["ogrenci_adi_norm"],
                    eksik["ogrenci_adi_norm"],
                    eksik["ders"],
                    eksik["kazanim"],
                ),
            )

        conn.commit()
        st.success("Sınav ve Eksik Dosyası Başarıyla Yüklendi ve İşlendi!")
      except Exception as e:
        st.error(f"Aktarım Sırasında Hata Oluştu: {e}")

  conn.close()

# --- 4. YKS PUAN & SIRALAMA HESAPLAYICI ---
elif menu == "🧮 YKS Puan & Sıralama Hesaplayıcı":
  st.header("🧮 ÖSYM Uyumlu YKS Puan & Sıralama Simülatörü")
  st.write(
      "Aşağıdaki alanlara tahmini netlerinizi girerek ÖSYM yerleştirme"
      " puanlarınızı hesaplayabilirsiniz."
  )

  col_obp, col_empty = st.columns([1, 2])
  with col_obp:
    obp = st.number_input(
        "Diplom Notu (OBP) (50-100 Arası)",
        min_value=50.0,
        max_value=100.0,
        value=80.0,
        step=0.5,
    )

  st.markdown("---")
  c1, c2 = st.columns(2)

  with c1:
    st.subheader("📝 TYT Netleri")
    tyt_tr = st.number_input("Türkçe (40 Soru)", 0.0, 40.0, 25.0, 0.25)
    tyt_sos = st.number_input("Sosyal (20 Soru)", 0.0, 20.0, 12.0, 0.25)
    tyt_mat = st.number_input("Matematik (40 Soru)", 0.0, 40.0, 20.0, 0.25)
    tyt_fen = st.number_input("Fen (20 Soru)", 0.0, 20.0, 10.0, 0.25)

  with c2:
    st.subheader("📚 AYT Netleri")
    ayt_mat = st.number_input("AYT Matematik (40 Soru)", 0.0, 40.0, 15.0, 0.25)
    ayt_fiz = st.number_input("Fizik (14 Soru)", 0.0, 14.0, 5.0, 0.25)
    ayt_kim = st.number_input("Kimya (13 Soru)", 0.0, 13.0, 5.0, 0.25)
    ayt_biy = st.number_input("Biyoloji (13 Soru)", 0.0, 13.0, 5.0, 0.25)
    ayt_edb = st.number_input("Edebiyat (24 Soru)", 0.0, 24.0, 12.0, 0.25)
    ayt_tar1 = st.number_input("Tarih-1 (10 Soru)", 0.0, 10.0, 4.0, 0.25)
    ayt_cog1 = st.number_input("Coğrafya-1 (6 Soru)", 0.0, 6.0, 3.0, 0.25)
    ayt_dil = st.number_input("Yabancı Dil (80 Soru)", 0.0, 80.0, 0.0, 1.0)

  tyt_dict = {
      "turkce": tyt_tr,
      "sosyal": tyt_sos,
      "matematik": tyt_mat,
      "fen": tyt_fen,
  }
  ayt_dict = {
      "mat": ayt_mat,
      "fiz": ayt_fiz,
      "kim": ayt_kim,
      "biy": ayt_biy,
      "edb": ayt_edb,
      "tar1": ayt_tar1,
      "cog1": ayt_cog1,
      "dil": ayt_dil,
  }

  puanlar = hesapla_yks_puanlari(tyt_dict, ayt_dict, obp)

  st.markdown("---")
  st.subheader("📊 Tahmini Yerleştirme Puanlarınız (OBP Dahil)")

  m1, m2, m3, m4, m5 = st.columns(5)
  m1.metric("TYT Puanı", puanlar["TYT"])
  m2.metric("SAY Puanı", puanlar["SAY"])
  m3.metric("EA Puanı", puanlar["EA"])
  m4.metric("SÖZ Puanı", puanlar["SOZ"])
  m5.metric("DİL Puanı", puanlar["DİL"])

# --- 5. HEDEF BELİRLEME ---
elif menu == "🎯 Hedef Belirleme":
  st.header("🎯 Hedef Belirleme ve Takip")
  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  if st.session_state.user_role in ["admin", "ogretmen"]:
    ogr_df = pd.read_sql_query("SELECT * FROM ogrenciler", conn)
    secilen_norm = st.selectbox(
        "Hedef Tanımlanacak Öğrenci", ogr_df["ad_soyad_norm"].tolist()
    )
  else:
    secilen_norm = st.session_state.ogrenci_adi_norm

  hedef_bolum = st.text_input(
      "Targeted Department / Üniversite & Bölüm Hedefi"
  )
  hedef_puan_turu = st.selectbox("Hedef Puan Türü", ["TYT", "SAY", "EA", "SOZ"])
  hedef_net = st.number_input("Targeted Net / Hedef Toplam Net", 0.0, 200.0, 80.0)
  hedef_puan = st.number_input(
      "Targeted Score / Hedef Puan", 100.0, 560.0, 400.0
  )

  if st.button("Hedef Kaydet"):
    cursor.execute(
        """
            INSERT OR REPLACE INTO ogrenci_hedefleri (ogrenci_adi_norm, hedef_bolum, hedef_net, hedef_puan, hedef_puan_turu)
            VALUES (?, ?, ?, ?, ?)
        """,
        (secilen_norm, hedef_bolum, hedef_net, hedef_puan, hedef_puan_turu),
    )
    conn.commit()
    st.success("Hedef Başarıyla Kaydedildi!")

  # Mevcut Hedefi Göster
  hedef_df = pd.read_sql_query(
      f"SELECT * FROM ogrenci_hedefleri WHERE ogrenci_adi_norm ="
      f" '{secilen_norm}'",
      conn,
  )
  if not hedef_df.empty:
    st.subheader("📌 Güncel Hedef Durumu")
    st.json(hedef_df.iloc[0].to_dict())

  conn.close()

# --- 6. ÖDEV TAKİP SİSTEMİ ---
elif menu == "📚 Ödev Takip Sistemi":
  st.header("📚 Ödev Atama ve Takip Modülü")
  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  if st.session_state.user_role in ["admin", "ogretmen"]:
    st.subheader("➕ Yeni Ödev Atama")
    ogr_df = pd.read_sql_query("SELECT * FROM ogrenciler", conn)
    secilen_norm = st.selectbox(
        "Ödev Verilecek Öğrenci", ogr_df["ad_soyad_norm"].tolist()
    )
    ders = st.selectbox(
        "Ders", ["Matematik", "Fizik", "Kimya", "Biyoloji", "Türkçe", "Tarih"]
    )
    odev_tanim = st.text_area("Ödev Açıklaması / Sayfa Aralığı / Test")
    son_tarih = st.date_input("Son Teslim Tarihi", datetime.date.today())

    if st.button("Ödevi Ata"):
      cursor.execute(
          """
                INSERT INTO odevler (ogrenci_adi_norm, ders, odev_tanimi, son_tarih)
                VALUES (?, ?, ?, ?)
            """,
          (secilen_norm, ders, odev_tanim, str(son_tarih)),
      )
      conn.commit()
      st.success("Ödev Öğrenciye Başarıyla Atandı!")

  st.subheader("📋 Ödev Listesi ve Kontrolü")
  if st.session_state.user_role in ["admin", "ogretmen"]:
    odevler_df = pd.read_sql_query("SELECT * FROM odevler", conn)
  else:
    odevler_df = pd.read_sql_query(
        f"SELECT * FROM odevler WHERE ogrenci_adi_norm ="
        f" '{st.session_state.ogrenci_adi_norm}'",
        conn,
    )

  st.dataframe(odevler_df, use_container_width=True)
  conn.close()

# --- 7. ÖĞRENCİ & KULLANICI YÖNETİMİ ---
elif menu == "👥 Öğrenci & Kullanıcı Yönetimi":
  st.header("👥 Öğrenci ve Kullanıcı Hesap Yönetimi")
  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  st.subheader("➕ Yeni Kullanıcı / Öğrenci Hesabı Oluştur")
  yeni_kullanici = st.text_input("Kullanıcı Adı")
  yeni_sifre = st.text_input("Şifre", type="password")
  rol = st.selectbox("Rol", ["ogrenci", "ogretmen", "admin"])
  ad_soyad = st.text_input("Öğrenci Adı Soyadı (Eğer öğrenci ise)")
  telefon = st.text_input("Veli Telefon No (Örn: 5xx1234567)")

  if st.button("Kullanıcı Kaydet"):
    if yeni_kullanici and yeni_sifre:
      hashed_p = hash_sifre(yeni_sifre)
      ad_norm = tr_normalize(ad_soyad) if ad_soyad else None

      try:
        cursor.execute(
            """
                    INSERT INTO kullanicilar (kullanici_adi, sifre, rol, ogrenci_adi_norm, telefon)
                    VALUES (?, ?, ?, ?, ?)
                """,
            (yeni_kullanici, hashed_p, rol, ad_norm, telefon),
        )

        if rol == "ogrenci" and ad_soyad:
          cursor.execute(
              """
                        INSERT OR IGNORE INTO ogrenciler (okul_no, ad_soyad, ad_soyad_norm, veli_telefon)
                        VALUES (?, ?, ?, ?)
                    """,
              (yeni_kullanici, ad_soyad, ad_norm, telefon),
          )

        conn.commit()
        st.success("Kullanıcı Kaydı Başarıyla Yapıldı!")
      except Exception as e:
        st.error(f"Hata: {e}")
    else:
      st.error("Kullanıcı adı ve şifre zorunludur!")

  st.subheader("📋 Mevcut Kullanıcı Listesi")
  users_df = pd.read_sql_query(
      "SELECT id, kullanici_adi, rol, ogrenci_adi_norm, telefon FROM"
      " kullanicilar",
      conn,
  )
  st.dataframe(users_df, use_container_width=True)
  conn.close()

# --- 8. KURUM AYARLARI ---
elif menu == "⚙️ Kurum Ayarları":
  st.header("⚙️ Kurum ve Sistem Ayarları")
  conn = sqlite3.connect("sinav_takip.db")
  cursor = conn.cursor()

  kurum_adi = st.text_input("Kurum / Okul Adı")
  logo_file = st.file_uploader("Kurum Logosu (PNG/JPG)", type=["png", "jpg"])

  if st.button("Ayarları Kaydet"):
    logo_base64 = ""
    if logo_file:
      logo_base64 = base64.b64encode(logo_file.read()).decode()

    cursor.execute(
        """
            INSERT OR REPLACE INTO kurum_ayarlari (id, kurum_adi, logo_base64)
            VALUES (1, ?, ?)
        """,
        (kurum_adi, logo_base64),
    )
    conn.commit()
    st.success("Kurum Ayarları Kaydedildi!")

  conn.close()