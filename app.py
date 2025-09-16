import streamlit as st
import sqlite3
import pandas as pd
import datetime
import random
from gtts import gTTS
from streamlit_autorefresh import st_autorefresh
from difflib import get_close_matches

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
    weight REAL,
    height REAL,
    bp TEXT,
    condition TEXT
)
''')

# Queue table
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

# --- Migration check ---
c.execute("PRAGMA table_info(queue)")
cols = [col[1] for col in c.fetchall()]
if "ticket_number" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN ticket_number TEXT")
if "location" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN location TEXT")
if "destination" not in cols:
    c.execute("ALTER TABLE queue ADD COLUMN destination TEXT")
conn.commit()

# ----------------- FUNCTIONS -----------------
def generate_ticket():
    return f"T{datetime.datetime.now().strftime('%H%M%S')}"

def add_patient(first_name, middle_name, surname, age, gender):
    c.execute("INSERT INTO patients (first_name, middle_name, surname, age, gender) VALUES (?, ?, ?, ?, ?)",
              (first_name, middle_name, surname, age, gender))
    conn.commit()
    return c.lastrowid

def add_to_queue(patient_id, destination="Triage"):
    ticket = generate_ticket()
    entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO queue (patient_id, ticket_number, entry_time, location, destination) VALUES (?, ?, ?, ?, ?)",
              (patient_id, ticket, entry_time, "Entry", destination))
    conn.commit()
    return ticket

def update_triage(patient_id, weight, height, bp):
    c.execute("UPDATE patients SET weight=?, height=?, bp=? WHERE id=?", (weight, height, bp, patient_id))
    c.execute("UPDATE queue SET location='Triage', status='waiting', destination='Consultation' WHERE patient_id=?", (patient_id,))
    conn.commit()

def update_condition(patient_id, condition):
    c.execute("UPDATE patients SET condition=? WHERE id=?", (condition, patient_id))
    c.execute("UPDATE queue SET location='Consultation', status='done', exit_time=? WHERE patient_id=?",
              (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), patient_id))
    conn.commit()

def get_queue():
    return pd.read_sql("""
        SELECT q.queue_id, q.ticket_number,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               p.age, p.gender, p.weight, p.height, p.bp, p.condition,
               q.location, q.status, q.destination
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
                        ["Home", "Kiosk (Entry)", "Triage", "Doctor Panel", "TV Display", "About", "Contacts", "FAQs", "Chatbot"])

# ----------------- PAGES -----------------
if menu == "Home":
    st.title("🏥 Smart Queue & Patient Journey Tracking")
    st.write("""
    This system manages patients from entry → triage → doctor → exit:
    - 🎟 **Kiosk** issues tickets
    - 📋 **Triage** records vitals
    - 👨‍⚕️ **Doctor** enters diagnosis
    - 📺 **TV Display** shows queue with audio + animations
    """)
    st.success("✅ Making hospital visits faster and transparent!")

elif menu == "Kiosk (Entry)":
    st.title("🎟 Patient Kiosk (Entry)")
    first_name = st.text_input("First Name")
    middle_name = st.text_input("Middle Name")
    surname = st.text_input("Surname")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    
    if st.button("Generate Ticket"):
        patient_id = add_patient(first_name, middle_name, surname, age, gender)
        ticket = add_to_queue(patient_id)
        st.success(f"✅ Ticket generated: {ticket}. Please wait for Triage.")

elif menu == "Triage":
    st.title("📋 Triage Station")
    patient_id = st.number_input("Enter Patient ID", step=1, min_value=1)
    weight = st.number_input("Weight (kg)")
    height = st.number_input("Height (cm)")
    bp = st.text_input("Blood Pressure")
    
    if st.button("Save Triage Data"):
        update_triage(patient_id, weight, height, bp)
        st.success("✅ Triage data saved. Patient moved to Consultation queue.")

elif menu == "Doctor Panel":
    st.title("👨‍⚕️ Doctor Panel")
    patient_id = st.number_input("Enter Patient ID", step=1, min_value=1)
    condition = st.text_area("Enter Diagnosis / Condition")
    
    if st.button("Save Diagnosis & Complete Visit"):
        update_condition(patient_id, condition)
        st.success("✅ Condition saved. Patient marked as Done.")

    st.subheader("📂 Current Queue")
    st.dataframe(get_queue())

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
        destination = current["destination"].iloc[0]

        # Blinking + Audio
        st.markdown(
            f"""
            <style>
            .blinking {{
              animation: blinker 1.5s linear infinite;
              color: red;
              font-size: 80px;
              text-align: center;
            }}
            @keyframes blinker {{
              50% {{ opacity: 0; }}
            }}
            </style>
            <h1 style='text-align:center;'>Now Serving</h1>
            <div class="blinking">Ticket #{ticket} - {name}</div>
            <h3 style='text-align:center; color:blue;'>Proceed to {destination}</h3>
            """, unsafe_allow_html=True
        )

        audio_file = announce_patient(ticket, name, destination)
        audio_bytes = open(audio_file, "rb").read()
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)

    else:
        st.info("⏳ Waiting for the first patient to be served...")

    tips = [
        "💧 Drink at least 8 glasses of water daily.",
        "🍎 Eat more fruits and vegetables for better immunity.",
        "🏃‍♂️ Exercise at least 30 minutes a day.",
        "🧘 Manage stress with deep breathing or meditation.",
        "💉 Stay updated with your vaccinations."
    ]
    st.markdown(f"<p style='text-align:center; font-size:20px; color:green;'>{random.choice(tips)}</p>", unsafe_allow_html=True)

elif menu == "About":
    st.title("ℹ️ About")
    st.write("Smart Queue tracks patient flow from entry to exit with real-time updates.")

elif menu == "Contacts":
    st.title("📞 Contact Us")
    st.write("Support: support@hospital.com | +254-700-123-456")

elif menu == "FAQs":
    st.title("❓ FAQs")
    st.write("""
    - **How do I register?** Use the kiosk at entry.
    - **What happens at triage?** Vitals (weight, height, BP) are measured.
    - **Where do I wait?** Please proceed to waiting area until your ticket is called.
    """)

elif menu == "Chatbot":
    st.title("🤖 Hospital Chatbot")
    faq = {
        "how to register": "📝 Register at the kiosk at entry. You’ll get a ticket number.",
        "triage": "📋 Triage includes weight, height, and blood pressure checks.",
        "consultation": "👨‍⚕️ Consultation comes after triage. The doctor will call you.",
        "pharmacy": "💊 Pharmacy is after consultation, on the ground floor.",
    }
    user_q = st.text_input("Ask me something...")
    if user_q:
        q = user_q.lower()
        match = get_close_matches(q, faq.keys(), n=1, cutoff=0.5)
        if match:
            st.write(faq[match[0]])
        else:
            st.write("I’m still learning 🤖. Please ask the reception.")

