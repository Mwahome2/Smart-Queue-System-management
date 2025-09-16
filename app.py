import streamlit as st
import sqlite3
import pandas as pd
import datetime
from gtts import gTTS
import os
from streamlit_autorefresh import st_autorefresh
import matplotlib.pyplot as plt

# ----------------- DATABASE SETUP -----------------
conn = sqlite3.connect("hospital.db", check_same_thread=False)
c = conn.cursor()

# Patients table
c.execute('''
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    middle_name TEXT,
    surname TEXT,
    age INTEGER,
    gender TEXT,
    condition TEXT
)
''')

# Queue table
c.execute('''
CREATE TABLE IF NOT EXISTS queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER,
    emergency BOOLEAN,
    entry_time TEXT,
    exit_time TEXT,
    destination TEXT,
    status TEXT DEFAULT "waiting",
    FOREIGN KEY(patient_id) REFERENCES patients(id)
)
''')
conn.commit()

# --- Migration check: add missing columns if old DB exists ---
c.execute("PRAGMA table_info(queue)")
cols = [col[1] for col in c.fetchall()]
if "entry_time" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN entry_time TEXT")
if "exit_time" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN exit_time TEXT")
if "destination" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN destination TEXT")
conn.commit()

# ----------------- FUNCTIONS -----------------
def add_patient(first_name, middle_name, surname, age, gender, condition):
    c.execute("INSERT INTO patients (first_name, middle_name, surname, age, gender, condition) VALUES (?, ?, ?, ?, ?, ?)",
              (first_name, middle_name, surname, age, gender, condition))
    conn.commit()

def get_patient_by_name(first_name, surname):
    c.execute("SELECT * FROM patients WHERE first_name=? AND surname=?", (first_name, surname))
    return c.fetchone()

def add_to_queue(patient_id, emergency, destination):
    entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO queue (patient_id, emergency, entry_time, destination) VALUES (?, ?, ?, ?)",
              (patient_id, emergency, entry_time, destination))
    conn.commit()

def get_queue():
    try:
        return pd.read_sql("""
            SELECT q.queue_id,
                   p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
                   p.age, p.gender, p.condition,
                   q.emergency, q.entry_time, q.exit_time, q.destination, q.status
            FROM queue q
            JOIN patients p ON q.patient_id = p.id
            ORDER BY q.emergency DESC, q.queue_id ASC
        """, conn)
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()

def get_next_patient():
    c.execute("""
        SELECT q.queue_id,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               p.age, p.gender, p.condition, q.destination
        FROM queue q
        JOIN patients p ON q.patient_id=p.id
        WHERE q.status='waiting'
        ORDER BY q.emergency DESC, q.queue_id ASC
        LIMIT 1
    """)
    return c.fetchone()

def mark_done(queue_id):
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE queue SET status='done', exit_time=? WHERE queue_id=?", (exit_time, queue_id))
    conn.commit()

# Function to generate audio announcement
def announce_patient(patient_number, name, destination):
    text = f"Now serving patient number {patient_number}, {name}. Please proceed to {destination}."
    tts = gTTS(text=text, lang="en")
    filename = "announcement.mp3"
    tts.save(filename)
    return filename

# ----------------- STREAMLIT DASHBOARD -----------------
st.title("🏥 Smart Queue & Patient Management Dashboard")

col1, col2 = st.columns(2)

# Add new patient
with col1:
    st.subheader("➕ Add New Patient")
    first_name = st.text_input("First Name")
    middle_name = st.text_input("Middle Name")
    surname = st.text_input("Surname")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    condition = st.text_area("Condition / Diagnosis")

    if st.button("Save Patient"):
        add_patient(first_name, middle_name, surname, age, gender, condition)
        st.success("✅ Patient added successfully")

# Register to queue
with col2:
    st.subheader("📝 Register Patient to Queue")
    first_name = st.text_input("Enter First Name for Queue")
    surname = st.text_input("Enter Surname for Queue")
    emergency = st.checkbox("Emergency Case?")
    destination = st.selectbox("Destination", ["Consultation", "Lab", "Pharmacy", "Other"])
    if st.button("Register to Queue"):
        patient = get_patient_by_name(first_name, surname)
        if patient:
            add_to_queue(patient[0], emergency, destination)
            st.success(f"✅ {first_name} {surname} added to queue for {destination}")
        else:
            st.error("❌ Patient not found. Please add them first.")

# Patient records
st.subheader("📂 Patient Records")
df_patients = pd.read_sql("SELECT id, first_name, middle_name, surname, age, gender, condition FROM patients", conn)
st.dataframe(df_patients)

# Doctor view
st.subheader("👨‍⚕️ Doctor's Panel")
df_queue = get_queue()
if not df_queue.empty:
    st.dataframe(df_queue)
    if st.button("Next Patient"):
        patient = get_next_patient()
        if patient:
            st.success(f"Now seeing: {patient[1]} (Age {patient[2]}, {patient[3]}) - Condition: {patient[4]} → Destination: {patient[5]}")
            mark_done(patient[0])
else:
    st.info("No patients in queue")

# TV display
st.subheader("📺 Waiting Room Display")
st_autorefresh(interval=5000, key="tvdisplay")

try:
    current = pd.read_sql("""
        SELECT q.queue_id,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               q.destination
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status='done'
        ORDER BY q.queue_id DESC
        LIMIT 1
    """, conn)

    if not current.empty:
        patient_num = current["queue_id"].iloc[0]
        patient_name = current["full_name"].iloc[0]
        destination = current["destination"].iloc[0]

        st.markdown(
            f"<h1 style='text-align:center; font-size:60px;'>Now Serving</h1>"
            f"<h2 style='text-align:center; color:red; font-size:80px;'>#{patient_num} - {patient_name}</h2>"
            f"<h3 style='text-align:center; color:blue;'>Proceed to {destination}</h3>",
            unsafe_allow_html=True
        )

        audio_file = announce_patient(patient_num, patient_name, destination)
        audio_bytes = open(audio_file, "rb").read()
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
    else:
        st.info("No patients being served at the moment.")
except Exception as e:
    st.error(f"Error loading TV Display: {e}")

# ----------------- ANALYTICS SECTION -----------------
st.subheader("📊 Analytics Dashboard")

df_all = pd.read_sql("SELECT * FROM queue", conn)

if not df_all.empty:
    # Patients per destination
    st.write("### Patients per Destination")
    dest_counts = df_all["destination"].value_counts()
    fig1, ax1 = plt.subplots()
    dest_counts.plot(kind="bar", ax=ax1)
    ax1.set_ylabel("Number of Patients")
    ax1.set_xlabel("Destination")
    st.pyplot(fig1)

    # Average waiting time
    st.write("### Average Waiting Time (minutes)")
    df_done = df_all.dropna(subset=["entry_time", "exit_time"]).copy()
    if not df_done.empty:
        df_done["entry_time"] = pd.to_datetime(df_done["entry_time"])
        df_done["exit_time"] = pd.to_datetime(df_done["exit_time"])
        df_done["wait_minutes"] = (df_done["exit_time"] - df_done["entry_time"]).dt.total_seconds() / 60
        avg_wait = df_done["wait_minutes"].mean()
        st.metric("Avg Waiting Time", f"{avg_wait:.1f} minutes")
    else:
        st.info("No completed patients to calculate waiting time.")

    # Queue load per hour
    st.write("### Queue Load Over Time")
    df_all["entry_time"] = pd.to_datetime(df_all["entry_time"], errors="coerce")
    df_all["hour"] = df_all["entry_time"].dt.hour
    load = df_all.groupby("hour").size()
    fig2, ax2 = plt.subplots()
    load.plot(kind="line", marker="o", ax=ax2)
    ax2.set_ylabel("Patients Registered")
    ax2.set_xlabel("Hour of Day")
    st.pyplot(fig2)
else:
    st.info("No data yet for analytics.")
