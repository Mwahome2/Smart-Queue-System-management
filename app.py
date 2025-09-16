import streamlit as st
import sqlite3
import pandas as pd
import time
from gtts import gTTS
import os
from streamlit_autorefresh import st_autorefresh


# ----------------- DATABASE SETUP -----------------
conn = sqlite3.connect("hospital.db", check_same_thread=False)
c = conn.cursor()

# Patients table
c.execute('''
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
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
    time TEXT,
    status TEXT DEFAULT "waiting",
    FOREIGN KEY(patient_id) REFERENCES patients(id)
)
''')
conn.commit()

# ----------------- FUNCTIONS -----------------
def add_patient(name, age, gender, condition):
    c.execute("INSERT INTO patients (name, age, gender, condition) VALUES (?, ?, ?, ?)",
              (name, age, gender, condition))
    conn.commit()

def get_patient_by_name(name):
    c.execute("SELECT * FROM patients WHERE name=?", (name,))
    return c.fetchone()

def add_to_queue(patient_id, emergency):
    c.execute("INSERT INTO queue (patient_id, emergency, time) VALUES (?, ?, ?)",
              (patient_id, emergency, time.strftime("%H:%M:%S")))
    conn.commit()

def get_queue():
    return pd.read_sql("SELECT q.queue_id, p.name, p.age, p.gender, p.condition, q.emergency, q.time, q.status \
                        FROM queue q JOIN patients p ON q.patient_id = p.id WHERE q.status='waiting' \
                        ORDER BY q.emergency DESC, q.queue_id ASC", conn)

def get_next_patient():
    c.execute("SELECT q.queue_id, p.name, p.age, p.gender, p.condition FROM queue q \
               JOIN patients p ON q.patient_id=p.id WHERE q.status='waiting' \
               ORDER BY q.emergency DESC, q.queue_id ASC LIMIT 1")
    return c.fetchone()

def mark_done(queue_id):
    c.execute("UPDATE queue SET status='done' WHERE queue_id=?", (queue_id,))
    conn.commit()

# Function to generate audio announcement
def announce_patient(patient_number, name):
    text = f"Now serving patient number {patient_number}, {name}"
    tts = gTTS(text=text, lang="en")
    filename = "announcement.mp3"
    tts.save(filename)
    return filename

# ----------------- STREAMLIT APP -----------------
st.title("🏥 Smart Queue & Patient Management")

menu = st.sidebar.selectbox("Menu", ["Home", "Upload Data", "Add Patient", "Register", "Patient Records", "Doctor View", "TV Display"])

# HOME
if menu == "Home":
    st.write("Welcome to Smart Queue + Patient Records System.")

# UPLOAD DATA
elif menu == "Upload Data":
    st.subheader("📂 Upload Hospital Dataset")
    file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

    if file is not None:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        st.write("Preview of uploaded data:")
        st.dataframe(df.head())

        if st.button("Save to Database"):
            for _, row in df.iterrows():
                # Basic check to avoid duplicates
                existing = get_patient_by_name(row["name"])
                if not existing:
                    add_patient(row["name"], int(row["age"]), row["gender"], row.get("condition", ""))
            st.success("✅ Data uploaded successfully!")

# ADD NEW PATIENT
elif menu == "Add Patient":
    st.subheader("➕ Add New Patient")
    name = st.text_input("Name")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    condition = st.text_area("Condition / Diagnosis")

    if st.button("Save Patient"):
        add_patient(name, age, gender, condition)
        st.success("✅ Patient added successfully")

# REGISTER TO QUEUE
elif menu == "Register":
    st.subheader("📝 Register Patient to Queue")
    patient_name = st.text_input("Enter Patient Name")
    emergency = st.checkbox("Emergency Case?")
    if st.button("Register to Queue"):
        patient = get_patient_by_name(patient_name)
        if patient:
            add_to_queue(patient[0], emergency)
            st.success(f"✅ {patient[1]} added to queue")
        else:
            st.error("❌ Patient not found. Please add them first or upload hospital data.")

# PATIENT RECORDS
elif menu == "Patient Records":
    st.subheader("📂 Patient Records")
    df = pd.read_sql("SELECT * FROM patients", conn)
    st.dataframe(df)

# DOCTOR VIEW
elif menu == "Doctor View":
    st.subheader("👨‍⚕️ Doctor's Panel")
    df = get_queue()
    if not df.empty:
        st.table(df)
        if st.button("Next Patient"):
            patient = get_next_patient()
            if patient:
                st.success(f"Now seeing: {patient[1]} (Age {patient[2]}, {patient[3]}) - Condition: {patient[4]}")
                mark_done(patient[0])
    else:
        st.info("No patients in queue")

# TV DISPLAY
elif menu == "TV Display":
    st.subheader("📺 Waiting Room Display")

    # Auto refresh every 5 seconds
    st_autorefresh(interval=5000, key="tvdisplay")

    # Get last patient served
    current = pd.read_sql("""
        SELECT q.queue_id, p.name
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status='done'
        ORDER BY q.queue_id DESC
        LIMIT 1
    """, conn)

    if not current.empty:
        patient_num = current["queue_id"].iloc[0]
        patient_name = current["name"].iloc[0]

        # Big display
        st.markdown(
            f"<h1 style='text-align:center; font-size:60px;'>Now Serving</h1>"
            f"<h2 style='text-align:center; color:red; font-size:80px;'>#{patient_num} - {patient_name}</h2>",
            unsafe_allow_html=True
        )

        # Generate and play audio
        audio_file = announce_patient(patient_num, patient_name)
        audio_bytes = open(audio_file, "rb").read()
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)

    else:
        st.info("No patients being served at the moment.")
