import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import os
import random
from datetime import datetime

# --- 1. SETUP & MULTI-API FAILOVER ENGINE ---
# We track "dead" keys in session memory so we don't waste time retrying them
if 'dead_keys' not in st.session_state:
    st.session_state.dead_keys = set()

def scan_image_with_fallback(prompt, image):
    # Grab the list of keys securely from the secrets vault (.streamlit/secrets.toml)
    try:
        all_keys = st.secrets["GEMINI_KEYS"]
    except KeyError:
        return None, "CRITICAL ERROR: 'GEMINI_KEYS' not found in st.secrets. Please set up your secrets file."
    
    for key in all_keys:
        if key in st.session_state.dead_keys:
            continue # Skip keys we already know are maxed out today
            
        try:
            # Try to configure and run the model with the current key
            genai.configure(api_key=key)
            vision_model = genai.GenerativeModel('gemma-3-27b-it')
            response = vision_model.generate_content([prompt, image])
            return response.text.strip(), None # Success!
            
        except Exception as e:
            error_msg = str(e).lower()
            # If the error is a quota limit, rate limit, or timeout
            if "429" in error_msg or "exhausted" in error_msg or "quota" in error_msg or "timeout" in error_msg:
                st.session_state.dead_keys.add(key) # Mark key as dead
                print(f"Key exhausted! Moving to next key...")
                continue # Loop back and try the next key immediately
            else:
                return None, f"An unexpected error occurred: {e}"
                
    return None, "CRITICAL ERROR: All API keys are exhausted or dead."

# --- 2. AUTO-DETECT DEVICE & TOP MENU UI ---
st.set_page_config(page_title="Factory Scanner", layout="centered")

def get_default_role():
    try:
        # Peeks at the browser's User-Agent string to guess the device
        user_agent = st.context.headers.get("User-Agent", "").lower()
        if "mobi" in user_agent or "android" in user_agent or "iphone" in user_agent:
            return "📱 Phone (Scanner)"
    except:
        pass
    return "💻 PC (Live Monitor)"

roles = ["💻 PC (Live Monitor)", "📱 Phone (Scanner)"]
default_role = get_default_role()
default_index = roles.index(default_role)

st.title("⚙️ Factory Scanner System")

# Sleek horizontal top menu instead of the sidebar slider
role = st.radio(
    "Select Device Mode:", 
    roles, 
    index=default_index,
    horizontal=True,
    label_visibility="collapsed" # Hides the text label for a clean app look
)

st.divider() # Adds a clean visual line below the menu

# ==========================================
# MODE 1: THE PC (LIVE MONITOR)
# ==========================================
if role == "💻 PC (Live Monitor)":
    
    # Generate a unique 4-digit code for this specific PC tab
    if 'pc_code' not in st.session_state:
        st.session_state.pc_code = str(random.randint(1000, 9999))
        
    my_code = st.session_state.pc_code
    target_file = f"live_data_{my_code}.csv"
    
    st.header("💻 Live Factory Dashboard")
    
    # Massive UI so the worker can read the code from across the room
    st.info(f"### 📱 Ask the Phone Scanner to enter code: **{my_code}**")
    
    if st.button("🔄 Refresh Data", type="primary"):
        st.rerun()

    if os.path.isfile(target_file):
        df = pd.read_csv(target_file)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.write("---")
        if st.button("🗑️ Clear Data for this Room"):
            os.remove(target_file)
            st.rerun()
    else:
        st.write("Waiting for the phone to send data...")

# ==========================================
# MODE 2: THE PHONE (SCANNER)
# ==========================================
elif role == "📱 Phone (Scanner)":
    st.header("📱 Camera Scanner")
    
    # 1. Ask for the room code first
    room_code = st.text_input("Enter the 4-digit PC Code to connect:", placeholder="e.g. 4921")
    
    if room_code:
        # We only save to the specific file matching the PC's code
        target_file = f"live_data_{room_code}.csv"
        
        st.success(f"Connected to PC: {room_code}")
        
        if 'scanned_code' not in st.session_state:
            st.session_state.scanned_code = None

        # 2. THE MOBILE CAMERA HACK (Uses native phone camera, stops UI shaking)
        camera_photo = st.file_uploader("Tap here to open Camera", type=['jpg', 'jpeg', 'png'])
        
        if camera_photo is not None:
            # FIX: Instantly show the user the photo they just took!
            image_to_process = Image.open(camera_photo)
            st.image(image_to_process, caption="Captured Image", use_container_width=True)
            
            if st.button("1. Analyze Photo", type="primary"):
                with st.spinner("Analyzing with API Failover Engine..."):
                    prompt = """
                    You are an expert industrial AI. Look at this image of a metal bearing/cup.
                    There are often two types of writing on this metal: 
                    1. Small, machine-stamped/dot-peen engravings.
                    2. Large, thick, handwritten chalk numbers.
                    
                    CRITICAL RULE: COMPLETELY IGNORE the large handwritten chalk numbers. 
                    Read ONLY the small machine-stamped engravings. 
                    I ONLY want the core numerical bearing sequence (e.g., '12-19-210961' or '04-18-222258').
                    strictly IGNORE letter prefixes and country suffixes. 
                    Reply ONLY with the extracted sequence of numbers and dashes.
                    """
                    
                    # Call the smart multi-key function
                    extracted_text, error = scan_image_with_fallback(prompt, image_to_process)
                    
                    if error:
                        st.error(error)
                    else:
                        st.session_state.scanned_code = extracted_text
                        st.rerun() # Refresh to show the validation box

        if st.session_state.scanned_code is not None:
            final_code = st.text_input("Validate/Edit Code:", value=st.session_state.scanned_code)
            
            if st.button("2. Send to PC 🚀", type="secondary"):
                new_entry = pd.DataFrame({
                    "Time": [datetime.now().strftime("%I:%M:%S %p")],
                    "Bearing_Code": [final_code]
                })
                
                if not os.path.isfile(target_file):
                    new_entry.to_csv(target_file, index=False)
                else:
                    new_entry.to_csv(target_file, mode='a', index=False, header=False)
                    
                st.success(f"✅ Data sent to PC {room_code}!")
                st.session_state.scanned_code = None 
                st.rerun()