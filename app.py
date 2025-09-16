import streamlit as st
import sqlite3
import pandas as pd
import datetime
import random
from gtts import gTTS
from streamlit_autorefresh import st_autorefresh

# ----------------- DATABASE SETUP -----------------
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
    condition TEXT
)
''')

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
    return pd.read_sql("""
        SELECT q.queue_id,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               p.age, p.gender, p.condition,
               q.emergency, q.entry_time, q.exit_time, q.destination, q.status
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        ORDER BY q.emergency DESC, q.queue_id ASC
    """, conn)

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

# ----------------- STREAMLIT APP -----------------
st.set_page_config(page_title="Smart Queue System", page_icon="🏥", layout="wide")

menu = st.sidebar.radio("📌 Navigation", 
                        ["Home", "Add Patient (Kiosk)", "Register Patient (Triage)", 
                         "Doctor Panel", "TV Display", "About", "Contacts", "FAQs", "Chatbot"])

# ----------------- PAGES -----------------
if menu == "Home":
    st.title("🏥 Welcome to Smart Queue Management")
    st.write("""
    This system streamlines hospital patient flow:
    - Self-service **Add Patient** kiosk at entry
    - **Triage Staff** register patients into the queue
    - **Doctors** call patients via Doctor Panel
    - Waiting room shows updates on **TV Display**
    """)
    st.success("✅ Making hospital visits faster and stress-free!")

elif menu == "Add Patient (Kiosk)":
    st.title("📝 Patient Self-Registration (Kiosk)")
    first_name = st.text_input("First Name")
    middle_name = st.text_input("Middle Name")
    surname = st.text_input("Surname")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    condition = st.text_area("Condition / Diagnosis")

    if st.button("Save Patient"):
        add_patient(first_name, middle_name, surname, age, gender, condition)
        st.success("✅ Patient added successfully. Please proceed to Triage.")

elif menu == "Register Patient (Triage)":
    st.title("📋 Register Patient to Queue (Triage Use)")

    # Session state for triage login
    if "triage_logged_in" not in st.session_state:
        st.session_state.triage_logged_in = False

    if not st.session_state.triage_logged_in:
        password = st.text_input("Enter Triage Password", type="password")
        if st.button("Login as Triage"):
            if password == "triage123":  # 🔑 set your triage password
                st.session_state.triage_logged_in = True
                st.success("✅ Triage login successful")
            else:
                st.error("❌ Incorrect password")
    else:
        st.success("🔓 Triage Staff Logged In")

        first_name = st.text_input("First Name")
        surname = st.text_input("Surname")
        emergency = st.checkbox("Emergency Case?")
        destination = st.selectbox("Destination", ["Consultation", "Lab", "Pharmacy", "Other"])

        if st.button("Register to Queue"):
            patient = get_patient_by_name(first_name, surname)
            if patient:
                add_to_queue(patient[0], emergency, destination)
                st.success(f"✅ {first_name} {surname} registered for {destination}")
            else:
                st.error("❌ Patient not found. Please use the Kiosk first.")

        if st.button("Logout Triage"):
            st.session_state.triage_logged_in = False
            st.warning("Triage staff logged out")

elif menu == "Doctor Panel":
    st.title("👨‍⚕️ Doctor Panel (Login Required)")

    # Session state for doctor login
    if "doctor_logged_in" not in st.session_state:
        st.session_state.doctor_logged_in = False

    if not st.session_state.doctor_logged_in:
        password = st.text_input("Enter Doctor Password", type="password")
        if st.button("Login as Doctor"):
            if password == "doctor123":  # 🔑 set your doctor password
                st.session_state.doctor_logged_in = True
                st.success("✅ Doctor login successful")
            else:
                st.error("❌ Incorrect password")
    else:
        st.success("🔓 Doctor Logged In")

        df_queue = get_queue()
        st.subheader("🧾 Current Queue")
        if not df_queue.empty:
            st.dataframe(df_queue)
            if st.button("Next Patient"):
                patient = get_next_patient()
                if patient:
                    st.success(f"Now seeing: {patient[1]} (Age {patient[2]}, {patient[3]}) - Condition: {patient[4]} → Destination: {patient[5]}")
                    mark_done(patient[0])
        else:
            st.info("No patients in queue")

        if st.button("Logout Doctor"):
            st.session_state.doctor_logged_in = False
            st.warning("Doctor logged out")

elif menu == "TV Display":
    st.title("📺 Waiting Room Display")
    st_autorefresh(interval=7000, key="tvdisplay")

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
            f"<h1 style='text-align:center;'>Now Serving</h1>"
            f"<h2 style='text-align:center; color:red;'>#{patient_num} - {patient_name}</h2>"
            f"<h3 style='text-align:center; color:blue;'>Proceed to {destination}</h3>",
            unsafe_allow_html=True
        )
    else:
        st.info("⏳ Waiting for the first patient to be served...")

    # Health tips rotation
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
    st.write("Smart Queue is designed to improve hospital efficiency and patient experience.")

elif menu == "Contacts":
    st.title("📞 Contact Us")
    st.write("For support, reach us at: support@hospital.com | +254-700-123-456")

elif menu == "FAQs":
    st.title("❓ Frequently Asked Questions")
    st.write("- **How do I register?** Use the kiosk on entry.\n- **What if I need urgent care?** Select Emergency at triage.\n- **Where do I wait?** Please proceed to the waiting area until your number is called.")

elif menu == "Chatbot":
    st.title("🤖 Hospital Chatbot")
    user_q = st.text_input("Ask me something...")
    if user_q:
        if "time" in user_q.lower():
            st.write("⏰ We are open 24/7.")
        elif "lab" in user_q.lower():
            st.write("🧪 The Lab is located on the 2nd floor.")
        else:
            st.write("I’m still learning. Please ask the reception for more details.")

