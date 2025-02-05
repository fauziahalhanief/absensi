import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import base64
from streamlit_calendar import calendar
import os
import calendar as cal_mod  # Modul calendar Python
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go

# Konfigurasi halaman Streamlit
st.set_page_config(page_title="Dashboard Absensi", layout="wide")
col1, col2 = st.columns([1, 4])
with col1:
    st.image("https://cesgs.unair.ac.id/wp-content/uploads/2024/02/Logo-CESGS-UNAIR-400x121.png", use_column_width=True)
with col2:
    st.markdown('<h1 style="text-align:right; color: black;">Dashboard Absensi Karyawan</h1>', unsafe_allow_html=True)

# --- Fungsi Utilitas ---

def cek_ketepatan_waktu(waktu_masuk):
    try:
        waktu_batas = datetime.strptime("09:17", "%H:%M").time()
        if isinstance(waktu_masuk, str):
            waktu_masuk_obj = datetime.strptime(waktu_masuk.strip(), "%H:%M").time()
        elif isinstance(waktu_masuk, (datetime, pd.Timestamp)):
            waktu_masuk_obj = waktu_masuk.time()
        else:
            return "Invalid Time"
        return "Telat" if waktu_masuk_obj > waktu_batas else "Tepat Waktu"
    except Exception as e:
        return "Invalid Time"

def get_karyawan_mapping():
    conn = sqlite3.connect("absensi.db")
    try:
        df_karyawan = pd.read_sql_query("SELECT ID, Divisi FROM karyawan", conn)
    except Exception as e:
        st.error("Error membaca data karyawan dari database.")
        df_karyawan = pd.DataFrame(columns=["ID", "Divisi"])
    conn.close()
    mapping = df_karyawan.set_index("ID")["Divisi"].to_dict()
    return mapping

def format_presensi_data(df):
    # Pastikan kolom wajib ada
    required_cols = ['ID', 'Nama', 'Jenis']
    for col in required_cols:
        if col not in df.columns:
            st.error(f"Kolom '{col}' tidak ditemukan dalam data!")
            return pd.DataFrame()
    
    df["Jenis"] = df["Jenis"].str.lower()
    # Identifikasi kolom tanggal (diasumsikan nama kolom berupa digit: "1", "2", ..., "31")
    day_cols = [col for col in df.columns if str(col).isdigit()]
    if not day_cols:
        st.error("Tidak ditemukan kolom tanggal (1-31) dalam data!")
        return pd.DataFrame()
    
    # Ubah data dari format wide ke long
    df_long = df.melt(
        id_vars=['ID', 'Nama', 'Jenis'],
        value_vars=day_cols,
        var_name='tanggal',
        value_name='waktu'
    )
    df_long = df_long.dropna(subset=['waktu'])
    
    # Pivot data sehingga nilai pada kolom 'Jenis' menjadi kolom tersendiri
    df_pivot = df_long.pivot_table(
        index=['ID', 'Nama', 'tanggal'],
        columns='Jenis',
        values='waktu',
        aggfunc='first'
    ).reset_index()
    
    if 'datang' not in df_pivot.columns:
        df_pivot['datang'] = ""
    if 'pulang' not in df_pivot.columns:
        df_pivot['pulang'] = ""
    
    # Hitung status kehadiran berdasarkan waktu "datang"
    df_pivot['status'] = df_pivot['datang'].apply(lambda x: cek_ketepatan_waktu(x) if x != "" else "No Data")
    
    df_final = df_pivot[['ID', 'Nama', 'tanggal', 'status', 'datang', 'pulang']].copy()
    df_final.rename(columns={'ID': 'id'}, inplace=True)
    mapping = get_karyawan_mapping()
    df_final['divisi'] = df_final['id'].apply(lambda x: mapping.get(x, "No Data"))
    df_final = df_final[['id', 'Nama', 'divisi', 'tanggal', 'status', 'datang', 'pulang']]
    return df_final

# --- Login dan Role Management ---
# Role-based access (Admin vs Karyawan)
role = st.sidebar.radio("Pilih Role", ["Admin", "Karyawan"])

if role == "Admin":
    menu = st.sidebar.selectbox("Pilih Menu", ["Dashboard", "Data Pengajuan Izin", "Data Absensi", "Kalender Absensi"])
elif role == "Karyawan":
    menu = st.sidebar.selectbox("Pilih Menu", ["Pengajuan Izin Kerja"])

# --- Inisialisasi Database ---
def init_db():
    conn = sqlite3.connect("absensi.db")
    c = conn.cursor()
    
    # Tabel izin dengan kolom status (default: 'Pending')
    c.execute('''CREATE TABLE IF NOT EXISTS izin (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT,
                    divisi TEXT,
                    jenis_pengajuan TEXT,
                    tanggal_pengajuan TEXT,
                    tanggal_izin TEXT,
                    jumlah_hari INTEGER,
                    file_pengajuan BLOB,
                    file_persetujuan BLOB,
                    status TEXT DEFAULT 'Pending'
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS absensi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT,
                    divisi TEXT,
                    tanggal TEXT,
                    jam_masuk TEXT,
                    jam_keluar TEXT,
                    status TEXT
                )''')
    
    # Tabel karyawan: data minimal (ID, Nama, Divisi)
    c.execute('''CREATE TABLE IF NOT EXISTS karyawan (
                    ID INTEGER PRIMARY KEY,
                    Nama TEXT,
                    Divisi TEXT
                )''')
    
    conn.commit()
    conn.close()

init_db()

# --- Fungsi Penyimpanan dan Pengambilan Data ---

def save_absensi_to_db(df):
    conn = sqlite3.connect("absensi.db")
    for idx, row in df.iterrows():
        conn.execute(
            "INSERT INTO absensi (nama, divisi, tanggal, jam_masuk, jam_keluar, status) VALUES (?, ?, ?, ?, ?, ?)",
            (row['nama'], row['divisi'], row['tanggal'], row['jam_masuk'], row['jam_keluar'], row['status'])
        )
    conn.commit()
    conn.close()

def save_izin(nama, divisi, jenis_pengajuan, tanggal_pengajuan, tanggal_izin, jumlah_hari, file_pengajuan_bytes, file_persetujuan_bytes):
    conn = sqlite3.connect("absensi.db")
    c = conn.cursor()

    # Pastikan file dalam bentuk bytes (BLOB)
    file_pengajuan_blob = file_pengajuan_bytes if file_pengajuan_bytes else None
    file_persetujuan_blob = file_persetujuan_bytes if file_persetujuan_bytes else None

    c.execute('''INSERT INTO izin (nama, divisi, jenis_pengajuan, tanggal_pengajuan, tanggal_izin, jumlah_hari, file_pengajuan, file_persetujuan, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (nama, divisi, jenis_pengajuan, tanggal_pengajuan, tanggal_izin, jumlah_hari, file_pengajuan_blob, file_persetujuan_blob, "Pending"))
    
    conn.commit()
    conn.close()

def load_izin():
    conn = sqlite3.connect("absensi.db")
    df = pd.read_sql_query("SELECT * FROM izin", conn)
    conn.close()
    return df

def load_absensi():
    conn = sqlite3.connect("absensi.db")
    df = pd.read_sql_query("SELECT * FROM absensi", conn)
    conn.close()
    return df

def get_download_link(file_bytes, filename):
    if file_bytes is None:
        return ""
    b64 = base64.b64encode(file_bytes).decode()
    href = f'<a href="data:image/jpeg;base64,{b64}" download="{filename}" target="_blank">Lihat File</a>'
    return href

def update_izin_status(izin_id, new_status):
    conn = sqlite3.connect("absensi.db")
    c = conn.cursor()
    c.execute("UPDATE izin SET status = ? WHERE id = ?", (new_status, izin_id))
    conn.commit()
    conn.close()

def add_absensi_from_izin(izin_record):
    """
    Fungsi ini akan memasukkan data absensi (ketidakhadiran) ke tabel absensi 
    untuk setiap hari sesuai dengan tanggal_izin dan jumlah_hari pada data izin.
    """
    nama = izin_record['nama']
    divisi = izin_record['divisi']
    try:
        start_date = datetime.strptime(izin_record['tanggal_izin'], "%Y-%m-%d").date()
    except Exception as e:
        st.error("Format tanggal izin tidak valid.")
        return
    jumlah_hari = int(izin_record['jumlah_hari'])
    conn = sqlite3.connect("absensi.db")
    c = conn.cursor()
    for i in range(jumlah_hari):
        current_date = start_date + timedelta(days=i)
        c.execute("INSERT INTO absensi (nama, divisi, tanggal, jam_masuk, jam_keluar, status) VALUES (?, ?, ?, ?, ?, ?)",
                  (nama, divisi, current_date.strftime("%Y-%m-%d"), "", "", "Izin"))
    conn.commit()
    conn.close()

# --- Tampilan UI Streamlit ---

# Pastikan session_state untuk detail (di Kalender Absensi) terinisialisasi
if "detail_type" not in st.session_state:
    st.session_state.detail_type = None

# Warna yang disesuaikan dengan logo CESGS UNAIR
warna_biru = "#003C8D"  # Biru tua
warna_kuning = "#FFD700"  # Kuning emas

# 1. Menu untuk Karyawan: Pengajuan Izin Kerja
if menu == "Pengajuan Izin Kerja" and role == "Karyawan":
    st.subheader("Form Pengajuan Izin Tidak Masuk")
    nama = st.text_input("Nama Karyawan")
    divisi = st.text_input("Divisi")
    jenis_pengajuan = st.selectbox("Jenis Pengajuan", ["Cuti", "Izin", "Sakit", "WFH"])
    tanggal_pengajuan = st.date_input("Tanggal Pengajuan", datetime.today())
    tanggal_izin = st.date_input("Tanggal Izin", datetime.today())
    jumlah_hari = st.number_input("Jumlah Hari", min_value=1, step=1)
    file_pengajuan = st.file_uploader("Upload Form Pengajuan (JPG, PNG)", type=["jpg", "png"])
    file_persetujuan = st.file_uploader("Upload File Persetujuan (JPG, PNG)", type=["jpg", "png"])
    
    if st.button("Ajukan Izin"):
        file_pengajuan_bytes = file_pengajuan.getvalue() if file_pengajuan is not None else None
        file_persetujuan_bytes = file_persetujuan.getvalue() if file_persetujuan is not None else None
        save_izin(nama, divisi, jenis_pengajuan, str(tanggal_pengajuan), str(tanggal_izin), jumlah_hari,
                  file_pengajuan_bytes, file_persetujuan_bytes)
        st.success("Pengajuan izin berhasil disimpan!")
        
# 2. Menu untuk Admin: Dashboard (Tampilan grafik + tabel pengajuan izin pending dengan aksi Accept/Reject)
elif menu == "Dashboard" and role == "Admin":
    st.subheader("Dashboard Pengajuan Izin")
    
    # Grafik: Pengajuan Izin per Jenis
    df_izin_all = load_izin()
    if not df_izin_all.empty:
        jenis_pengajuan_count = df_izin_all.groupby("jenis_pengajuan").size().reset_index(name='Jumlah')
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=jenis_pengajuan_count['jenis_pengajuan'],
            y=jenis_pengajuan_count['Jumlah'],
            name="Jumlah Pengajuan",
            marker=dict(color=[warna_biru if x != "WFH" else warna_kuning for x in jenis_pengajuan_count['jenis_pengajuan']]),
            text=jenis_pengajuan_count['Jumlah'],
            textposition='outside',
        ))
        fig.update_layout(
            title="Jumlah Pengajuan Izin per Jenis",
            title_font_size=18,
            xaxis_title="Jenis Pengajuan",
            yaxis_title="Jumlah Pengajuan",
            plot_bgcolor='rgba(0,0,0,0)',
            template="plotly_dark",
            xaxis_tickangle=-45,
            hovermode="closest"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Belum ada data pengajuan izin.")
    
    st.write("### Tabel Pengajuan Izin (Pending)")
    conn = sqlite3.connect("absensi.db")
    df_pending = pd.read_sql_query("SELECT * FROM izin WHERE status = 'Pending'", conn)
    conn.close()

    if df_pending.empty:
        st.info("Tidak ada pengajuan izin yang pending.")
    else:
        # Header tabel
        headers = ["ID", "Nama", "Divisi", "Jenis Pengajuan", "Tanggal Pengajuan", "Tanggal Izin", "Jumlah Hari", "File Pengajuan", "File Persetujuan", "Status", "Persetujuan"]
        header_cols = st.columns(len(headers))
        for idx, header in enumerate(headers):
            header_cols[idx].write(f"**{header}**")
        
        # Tampilkan setiap baris data
        for index, row in df_pending.iterrows():
            row_cols = st.columns(len(headers))
            row_cols[0].write(row["id"])
            row_cols[1].write(row["nama"])
            row_cols[2].write(row["divisi"])
            row_cols[3].write(row["jenis_pengajuan"])
            row_cols[4].write(row["tanggal_pengajuan"])
            row_cols[5].write(row["tanggal_izin"])
            row_cols[6].write(row["jumlah_hari"])

            # Tambahkan link file pengajuan (jika ada)
            if row["file_pengajuan"]:
                file_pengajuan_link = get_download_link(row["file_pengajuan"], "file_pengajuan.jpg")
            else:
                file_pengajuan_link = "Tidak Ada File"
            row_cols[7].markdown(file_pengajuan_link, unsafe_allow_html=True)

            # Tambahkan link file persetujuan (jika ada)
            if row["file_persetujuan"]:
                file_persetujuan_link = get_download_link(row["file_persetujuan"], "file_persetujuan.jpg")
            else:
                file_persetujuan_link = "Belum Disetujui"
            row_cols[8].markdown(file_persetujuan_link, unsafe_allow_html=True)

            row_cols[9].write(row["status"])

            # Tambahkan tombol Accept dan Reject
            accept_clicked = row_cols[10].button("Accept", key=f"accept_{row['id']}")
            reject_clicked = row_cols[10].button("Reject", key=f"reject_{row['id']}")

            if accept_clicked:
                update_izin_status(row["id"], "Pengajuan izin telah diterima")
                add_absensi_from_izin(row)
                st.success(f"Pengajuan ID {row['id']} telah diterima.")
                st.session_state["last_action"] = "accept"

            if reject_clicked:
                update_izin_status(row["id"], "Pengajuan izin ditolak")
                st.warning(f"Pengajuan ID {row['id']} telah ditolak.")
                st.session_state["last_action"] = "reject"

# 3. Menu untuk Admin: Data Pengajuan Izin (hanya yang telah diterima)
elif menu == "Data Pengajuan Izin" and role == "Admin":
    st.subheader("Data Pengajuan Izin Karyawan")

    # Pilihan untuk memilih jenis pengajuan yang ingin ditampilkan
    jenis_filter = st.selectbox("Pilih Jenis Pengajuan", ["Semua", "Cuti", "Izin", "Sakit", "WFH"])

    # Ambil data pengajuan izin yang sudah diterima
    conn = sqlite3.connect("absensi.db")
    
    # Query untuk mengambil data pengajuan izin berdasarkan status dan jenis pengajuan yang dipilih
    if jenis_filter == "Semua":
        query = "SELECT * FROM izin WHERE status = 'Pengajuan izin telah diterima'"
    else:
        query = "SELECT * FROM izin WHERE status = 'Pengajuan izin telah diterima' AND jenis_pengajuan = ?"
    
    df_izin = pd.read_sql_query(query, conn, params=(jenis_filter,) if jenis_filter != "Semua" else ())
    conn.close()

    if df_izin.empty:
        st.info(f"Tidak ada pengajuan izin yang diterima untuk jenis '{jenis_filter}'.")
    else:
        # Mengubah kolom "file_pengajuan" menjadi link unduhan dengan nama file yang sesuai
        df_izin['file_pengajuan'] = df_izin['file_pengajuan'].apply(lambda x: f'<a href="data:image/jpeg;base64,{base64.b64encode(x).decode()}" download="file_pengajuan_{x[:10]}.jpg" target="_blank">Lihat Form Pengajuan</a>' if x else "")
        
        # Mengubah kolom "file_persetujuan" menjadi link unduhan dengan nama file yang sesuai
        df_izin['file_persetujuan'] = df_izin['file_persetujuan'].apply(lambda x: f'<a href="data:image/jpeg;base64,{base64.b64encode(x).decode()}" download="file_persetujuan_{x[:10]}.jpg" target="_blank">Lihat File Persetujuan</a>' if x else "")
        
        # Hapus kolom "file_persetujuan" yang tidak perlu jika Anda tidak ingin menampilkannya
        df_izin = df_izin.drop(columns=["file_persetujuan"])

        # Tampilkan data pengajuan izin dalam format tabel
        st.markdown(df_izin.to_html(escape=False), unsafe_allow_html=True)

# 4. Menu untuk Admin: Data Absensi
elif menu == "Data Absensi" and role == "Admin":
    st.subheader("Data Presensi Karyawan")
    
    # --- Langkah 1: Pilih Tahun, Bulan, dan Tanggal ---
    day_map = {0:"Senin", 1:"Selasa", 2:"Rabu", 3:"Kamis", 4:"Jumat", 5:"Sabtu", 6:"Minggu"}
    bulan_indonesia = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
    
    selected_year = st.number_input("Pilih Tahun", min_value=2000, max_value=2100, value=2024, step=1)
    selected_month = st.selectbox("Pilih Bulan", list(range(1,13)), format_func=lambda x: bulan_indonesia[x])
    
    num_days = cal_mod.monthrange(selected_year, selected_month)[1]
    dates_in_month = [datetime(selected_year, selected_month, d) for d in range(1, num_days+1)]
    formatted_dates = [f"{day_map[d.weekday()]}, {d.day} {bulan_indonesia[d.month]} {d.year}" for d in dates_in_month]
    
    # --- Langkah 2: Pilih Rentang Tanggal ---
    start_date, end_date = st.date_input(
        "Pilih Rentang Tanggal",
        value=(datetime(selected_year, selected_month, 1), datetime(selected_year, selected_month, num_days)),
        min_value=datetime(selected_year, selected_month, 1),
        max_value=datetime(selected_year, selected_month, num_days),
        help="Pilih rentang tanggal untuk melihat data presensi."
    )
    
    # --- Langkah 3: Cek data absensi di database untuk bulan yang dipilih ---
    # --- Langkah 3: Cek data absensi di database untuk bulan yang dipilih ---
    month_str = f"{selected_year}-{selected_month:02d}"
    conn = sqlite3.connect("absensi.db")
    df_absensi_db = pd.read_sql_query("SELECT * FROM absensi WHERE tanggal LIKE ?", conn, params=(month_str+"-%",))
    conn.close()

    # **Filter Data: Hanya Data Kehadiran (Tanpa Izin, Cuti, Sakit, WFH)**
    df_hadir = df_absensi_db[
        ~df_absensi_db["status"].isin(["Izin", "Cuti", "Sakit", "WFH"])
    ]

    if df_hadir.empty:
        st.info(f"Data absensi untuk bulan {selected_year}-{selected_month:02d} belum ada. Silakan upload data absensi.")

        # **Tampilkan File Uploader**
        uploaded_file = st.file_uploader("Upload Data Absensi Bulanan", type=["xlsx"])
        
        if uploaded_file is not None:
            try:
                # **Baca File Excel**
                df_input = pd.read_excel(uploaded_file)
                df_processed = format_presensi_data(df_input)
                
                if df_processed.empty:
                    st.error("Data dalam file tidak valid atau kosong.")
                else:
                    # **Ubah kolom 'tanggal' menjadi format YYYY-MM-DD**
                    df_processed['tanggal'] = df_processed['tanggal'].apply(lambda d: f"{selected_year}-{selected_month:02d}-{int(d):02d}")
                    
                    # **Ubah nama kolom agar cocok dengan database**
                    df_processed.rename(columns={"Nama": "nama", "datang": "jam_masuk", "pulang": "jam_keluar"}, inplace=True)
                    
                    # **Simpan Data ke Database**
                    save_absensi_to_db(df_processed)
                    st.success("Data absensi berhasil disimpan!")

            except Exception as e:
                st.error(f"Terjadi kesalahan saat membaca file: {e}")

    else:
        # **Tampilkan Data Absensi yang Sudah Ada**
        date_range_filter = (df_hadir['tanggal'] >= start_date.strftime('%Y-%m-%d')) & (df_hadir['tanggal'] <= end_date.strftime('%Y-%m-%d'))
        filtered_df = df_hadir[date_range_filter]

        if filtered_df.empty:
            st.info(f"Tidak ada data absensi untuk rentang tanggal {start_date.strftime('%d %B %Y')} hingga {end_date.strftime('%d %B %Y')}.")
        else:
            # **Tampilkan Data Absensi dalam Tabel**
            def highlight_telat(row):
                return ['background-color: #ffcccc' if row['status'].lower() == 'telat' else '' for _ in row]

            styled_df = filtered_df.style.apply(highlight_telat, axis=1)
            st.write(f"**Data Presensi untuk {start_date.strftime('%d %B %Y')} hingga {end_date.strftime('%d %B %Y')}:**")
            st.dataframe(styled_df, use_container_width=True)



# 5. Menu untuk Admin: Kalender Absensi
elif menu == "Kalender Absensi" and role == "Admin":
    st.subheader("Kalender Absensi Karyawan")
    
    # --- Bagian 1: Tampilan Kalender Ringkasan per Tanggal ---
    with st.container():
        st.markdown("#### Tampilan Kalender Absensi")
        df_absensi_all = load_absensi()
        if not df_absensi_all.empty:
            df_absensi_all['tanggal_dt'] = pd.to_datetime(df_absensi_all['tanggal']).dt.date
            grouped_absensi = df_absensi_all.groupby('tanggal_dt').apply(
                lambda g: pd.Series({
                    "hadir": len(g),
                    "telat": (g['status'].str.lower() == "telat").sum()
                })
            ).reset_index()
        else:
            grouped_absensi = pd.DataFrame(columns=['tanggal_dt', 'hadir', 'telat'])
        
        df_izin_all = load_izin()
        tidak_hadir_dict = {}
        for idx, row in df_izin_all.iterrows():
            try:
                if pd.isnull(row['tanggal_izin']) or pd.isnull(row['jumlah_hari']):
                    continue
                start_date = datetime.strptime(row['tanggal_izin'], "%Y-%m-%d").date()
                days = int(row['jumlah_hari'])
                for d in range(days):
                    curr_date = start_date + timedelta(days=d)
                    tidak_hadir_dict[curr_date] = tidak_hadir_dict.get(curr_date, 0) + 1
            except Exception as e:
                continue
        
        all_dates = set(grouped_absensi['tanggal_dt'].tolist()) | set(tidak_hadir_dict.keys())
        events = []
        for d in sorted(all_dates):
            if d in grouped_absensi['tanggal_dt'].values:
                row = grouped_absensi[grouped_absensi['tanggal_dt'] == d]
                hadir = int(row['hadir'].iloc[0])
                telat = int(row['telat'].iloc[0])
            else:
                hadir = 0
                telat = 0
            tidak_hadir = tidak_hadir_dict.get(d, 0)
            
            # Remove the "12a" part and only show the relevant info
            title = f"H:{hadir} T:{telat} TH:{tidak_hadir}"
            
            events.append({
    "title": f"H:{hadir} T:{telat} TH:{tidak_hadir}",
    "start": d.strftime("%Y-%m-%d"),  # Format hanya tanggal, tanpa waktu
    "color": "transparent",  # Warna latar belakang transparan
    "textColor": "black"  # Warna teks tetap hitam
})
        
        calendar_options = {
            "editable": False,
            "header": {
                "left": "prev,next today",
                "center": "title",
                "right": "month,agendaWeek,agendaDay"
            },
            "defaultView": "month"
        }
        calendar(events=events, options=calendar_options)
    
    st.markdown("---")
    
    # --- Bagian 2: Rincian Data Absensi Harian ---
    st.markdown("### Rincian Data Absensi Harian")
    selected_date = st.date_input("Pilih Tanggal untuk melihat rincian", value=datetime.today())
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    conn = sqlite3.connect("absensi.db")
    df_absensi = pd.read_sql_query("SELECT * FROM absensi WHERE tanggal = ?", conn, params=(selected_date_str,))
    conn.close()
    
    hadir_count = len(df_absensi)
    telat_count = len(df_absensi[df_absensi['status'].str.lower() == "telat"])
    
    conn = sqlite3.connect("absensi.db")
    df_izin = pd.read_sql_query("SELECT * FROM izin", conn)
    conn.close()
    
    # Fungsi untuk mengecek apakah tanggal tertentu termasuk dalam rentang izin
    def is_absent(row, sel_date):
        try:
            start_date = datetime.strptime(row['tanggal_izin'], "%Y-%m-%d").date()
            days = int(row['jumlah_hari'])
            end_date = start_date + timedelta(days=days-1)
            return start_date <= sel_date <= end_date
        except Exception as e:
            return False

    # Ambil data absensi dan izin
    conn = sqlite3.connect("absensi.db")
    df_absensi = pd.read_sql_query("SELECT * FROM absensi WHERE tanggal = ?", conn, params=(selected_date_str,))
    df_izin = pd.read_sql_query("SELECT * FROM izin", conn)
    conn.close()

    # Hitung jumlah karyawan yang hadir dan terlambat
    hadir_count = len(df_absensi)
    telat_count = len(df_absensi[df_absensi['status'].str.lower() == "telat"])

    # Hitung jumlah karyawan yang tidak hadir karena izin
    df_absent = df_izin[df_izin.apply(lambda row: is_absent(row, selected_date), axis=1)]
    tidak_hadir_count = len(df_absent)

    # Filter karyawan yang hadir (tidak termasuk yang izin)
    karyawan_hadir = df_absensi[~df_absensi['nama'].isin(df_absent['nama'])]
    hadir_count = len(karyawan_hadir)

    selected_date_obj = selected_date
    df_absent = df_izin[df_izin.apply(lambda row: is_absent(row, selected_date_obj), axis=1)]
    tidak_hadir_count = len(df_absent)
    
    st.markdown(f"### Ringkasan Absensi untuk {selected_date.strftime('%A, %d %B %Y')}")
    col1, col2, col3 = st.columns(3)
    if col1.button(f"{hadir_count} karyawan hadir"):
        st.session_state.detail_type = "hadir"
    if col2.button(f"{telat_count} karyawan terlambat"):
        st.session_state.detail_type = "telat"
    if col3.button(f"{tidak_hadir_count} karyawan tidak hadir"):
        st.session_state.detail_type = "tidak_hadir"
    
    if st.session_state.detail_type:
        st.markdown("#### Rincian Data")
        if st.button("Tutup rincian"):
            st.session_state.detail_type = None
        if st.session_state.detail_type == "hadir":
            st.dataframe(karyawan_hadir, use_container_width=True)
        elif st.session_state.detail_type == "telat":
            st.dataframe(karyawan_hadir[karyawan_hadir['status'].str.lower() == "telat"], use_container_width=True)
        elif st.session_state.detail_type == "tidak_hadir":
            if df_absent.empty:
                st.info("Tidak ada data karyawan tidak hadir untuk tanggal ini.")
            else:
                st.dataframe(df_absent[['nama', 'divisi', 'jenis_pengajuan', 'tanggal_izin', 'jumlah_hari']], use_container_width=True)
                
        
