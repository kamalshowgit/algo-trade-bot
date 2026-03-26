import pyotp
from SmartApi import SmartConnect

# CONFIGURATION - Replace with your actual Angel One details
API_KEY = "D8LSmLpD"
CLIENT_ID = "K114092"
PASSWORD = "5389"
TOTP_SECRET = "HRJVN7JF2YTGXVTXNGHOCYNM4A" # The string you used for Google Authenticator

def test_login():
    try:
        # 1. Initialize SmartAPI
        smart_api = SmartConnect(api_key=API_KEY)
        
        # 2. Generate TOTP
        totp = pyotp.TOTP(TOTP_SECRET).now()
        
        # 3. Generate Session
        data = smart_api.generateSession(CLIENT_ID, PASSWORD, totp)
        
        if data['status']:
            print("--- LOGIN SUCCESSFUL ---")
            # 4. Get Profile to confirm connection
            profile = smart_api.getProfile(data['data']['refreshToken'])
            print(f"Welcome, {profile['data']['name']}!")
            print(f"Account Balance: {smart_api.rmsLimit()['data']['net']}")
        else:
            print(f"Login Failed: {data['message']}")
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    test_login()
