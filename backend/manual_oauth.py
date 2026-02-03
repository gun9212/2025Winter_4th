"""Manual OAuth token generation script."""
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

CREDENTIALS_DIR = Path(__file__).parent.parent / "credentials"
OAUTH_CLIENT_PATH = CREDENTIALS_DIR / "oauth_client.json"
OAUTH_TOKEN_PATH = CREDENTIALS_DIR / "oauth_token.json"

print("=" * 60)
print("Manual OAuth Token Generation")
print("=" * 60)

if not OAUTH_CLIENT_PATH.exists():
    print(f"❌ oauth_client.json not found at {OAUTH_CLIENT_PATH}")
    exit(1)

print(f"✅ Found: {OAUTH_CLIENT_PATH}")
print(f"📁 Token will be saved to: {OAUTH_TOKEN_PATH}")
print()

# Create flow
flow = InstalledAppFlow.from_client_secrets_file(
    str(OAUTH_CLIENT_PATH), 
    SCOPES,
    redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Out-of-band flow
)

# Generate authorization URL
auth_url, _ = flow.authorization_url(prompt='consent')

print("🔗 Please visit this URL to authorize:")
print()
print(auth_url)
print()
print("After authorization, you'll see a code.")
print("Copy and paste that code here:")
print()

code = input("Enter the authorization code: ").strip()

try:
    # Exchange code for token
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    # Save token
    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes),
    }
    
    with open(OAUTH_TOKEN_PATH, 'w') as f:
        json.dump(token_data, f, indent=2)
    
    print()
    print("✅ Authentication successful!")
    print(f"✅ Token saved to: {OAUTH_TOKEN_PATH}")
    
except Exception as e:
    print(f"❌ Error: {e}")
