import streamlit as st
import sqlite3
import pandas as pd
import datetime
import random
from gtts import gTTS
from streamlit_autorefresh import st_autorefresh
import matplotlib.pyplot as plt
from difflib import get_close_matches

# ----------------- DB SETUP -----------------
conn = sqlite3.connect("hospital.db", check_same_thread=False)
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    middle_name TEXT,
    surname TEXT,
    age INTEGER,
    gender TEXT,
    weight REAL,
    height REAL,
    bp TEXT,
    condition TEXT
)
''')

c.execute('''
CREATE TABLE IF NOT EXISTS queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER,
    ticket_number TEXT,
    entry_time TEXT,
    exit_time TEXT,
    location TEXT,
    status TEXT DEFAULT "waiting",
    destination TEXT,
    FOREIGN KEY(patient_id) REFERENCES patients(id)
)
''')
conn.commit()

# ----------------- FUNCTIONS -----------------
def generate_ticket():
    return f"T{datetime.datetime.now().strftime('%H%M%S')}"

def add_patient(first_name, middle_name, surname, age, gender):
    c.execute("INSERT INTO patients (first_name, middle_name, surname, age, gender) VALUES (?, ?, ?, ?, ?)",
              (first_name, middle_name, surname, age, gender))
    conn.commit()
    return c.lastrowid

def add_to_queue(patient_id):
    ticket = generate_ticket()
    entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO queue (patient_id, ticket_number, entry_time, location) VALUES (?, ?, ?, ?)",
              (patient_id, ticket, entry_time, "Entry"))
    conn.commit()
    return ticket

def update_triage(patient_id, weight, height, bp):
    c.execute("UPDATE patients SET weight=?, height=?, bp=? WHERE id=?", (weight, height, bp, patient_id))
    c.execute("UPDATE queue SET location='Triage', destination='Consultation' WHERE patient_id=?", (patient_id,))
    conn.commit()

def update_doctor(patient_id, condition, destination):
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE patients SET condition=? WHERE id=?", (condition, patient_id))
    c.execute("UPDATE queue SET location='Doctor', destination=?, exit_time=? WHERE patient_id=?",
              (destination, exit_time, patient_id))
    conn.commit()

def mark_done(patient_id, section):
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE queue SET location=?, status='done', exit_time=? WHERE patient_id=?",
              (section, exit_time, patient_id))
    conn.commit()

def get_queue():
    return pd.read_sql("""
        SELECT q.queue_id, q.ticket_number,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               p.age, p.gender, p.weight, p.height, p.bp, p.condition,
               q.location, q.status, q.destination, q.entry_time, q.exit_time
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        ORDER BY q.queue_id ASC
    """, conn)

def announce_patient(ticket, name, destination):
    text = f"Now serving ticket number {ticket}, {name}. Please proceed to {destination}."
    tts = gTTS(text=text, lang="en")
    filename = "announcement.mp3"
    tts.save(filename)
    return filename

# ----------------- STREAMLIT APP -----------------
st.set_page_config(page_title="Smart Queue System", page_icon="🏥", layout="wide")

menu = st.sidebar.radio("📌 Navigation", 
    ["Home", "About", "Kiosk (Entry)", "TV Display", "Triage", "Doctor Panel", 
     "Pharmacy", "Lab", "Payment", "Analytics", "Chatbot", "FAQs", "Contacts"])

# ----------------- PAGES -----------------
if menu == "Home":
    st.title("🏥 Smart Queue & Patient Journey Tracking")
    st.write("Welcome to the Hospital Smart Queue System. This app helps manage patients from entry to exit.")

elif menu == "About":
    st.title("ℹ️ About")
    st.write("""
    This Smart Queue Management System was built to streamline patient flow:  
    - 🎟 Kiosk → Patient self-registration  
    - 📺 TV Display → Queue management with announcements  
    - 📋 Triage → Vitals recording  
    - 👨‍⚕️ Doctor Panel → Consultation & referral  
    - 💊 Pharmacy / 🧪 Lab / 💵 Payment → Patient completion  
    """)

elif menu == "Kiosk (Entry)":
    st.title("🎟 Patient Kiosk (Entry)")
    first_name = st.text_input("First Name")
    middle_name = st.text_input("Middle Name")
    surname = st.text_input("Surname")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    if st.button("Generate Ticket"):
        pid = add_patient(first_name, middle_name, surname, age, gender)
        ticket = add_to_queue(pid)
        st.success(f"✅ Ticket generated: {ticket}. Please wait for triage.")

elif menu == "TV Display":
    st.title("📺 Waiting Room Display")
    st_autorefresh(interval=7000, key="tvdisplay")
    current = pd.read_sql("""
        SELECT q.ticket_number,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               q.destination
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status='done'
        ORDER BY q.queue_id DESC
        LIMIT 1
    """, conn)

    if not current.empty:
        ticket = current["ticket_number"].iloc[0]
        name = current["full_name"].iloc[0]
        destination = current["destination"].iloc[0] if current["destination"].iloc[0] else "Triage"
        st.markdown(
            f"<h1 style='text-align:center;'>Now Serving</h1>"
            f"<h2 style='text-align:center; color:red; animation: blinker 1s infinite;'>#{ticket} - {name}</h2>"
            f"<h3 style='text-align:center; color:blue;'>Proceed to {destination}</h3>",
            unsafe_allow_html=True)
        audio_file = announce_patient(ticket, name, destination)
        st.audio(open(audio_file, "rb").read(), format="audio/mp3", autoplay=True)
    else:
        st.info("⏳ Waiting for patients...")

    tips = ["💧 Drink water", "🍎 Eat fruits", "🏃‍♂️ Exercise daily", "🧘 Meditate", "💉 Get vaccinated"]
    st.markdown(f"<p style='text-align:center; font-size:20px; color:green;'>{random.choice(tips)}</p>", unsafe_allow_html=True)

elif menu == "Analytics":
    st.title("📊 Analytics Dashboard")
    df = get_queue()
    if not df.empty:
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
        df = df.dropna(subset=["entry_time", "exit_time"])  # ✅ only completed patients

        if not df.empty:
            df["wait"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60
            st.metric("Average Wait Time", f"{df['wait'].mean():.1f} min")
            fig, ax = plt.subplots()
            df["destination"].value_counts().plot(kind="bar", ax=ax)
            st.pyplot(fig)
        else:
            st.info("No completed patients yet for analytics.")
    else:
        st.info("No data yet.")

# (keep your Triage, Doctor, Pharmacy, Lab, Payment, Chatbot, FAQ, Contacts code unchanged)
