"""Google OAuth 2.0 authentication for user-based Drive access.

This module handles OAuth flow for accessing Google Drive with user credentials.
Unlike service accounts, OAuth uses the user's own Drive quota.

Usage:
    1. First-time setup: Run `python -m app.core.oauth` to authenticate
    2. This saves refresh token to credentials/oauth_token.json
    3. Application uses refresh token for subsequent API calls
"""

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes needed for Google Docs and Drive operations
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

# Paths for OAuth credentials
# Docker: /app/credentials, Local: backend/../credentials
import os
if os.path.exists("/app/credentials"):
    CREDENTIALS_DIR = Path("/app/credentials")
else:
    CREDENTIALS_DIR = Path(__file__).parent.parent.parent.parent / "credentials"
    
OAUTH_CLIENT_PATH = CREDENTIALS_DIR / "oauth_client.json"
OAUTH_TOKEN_PATH = CREDENTIALS_DIR / "oauth_token.json"


def get_oauth_credentials() -> Credentials:
    """
    Get OAuth credentials for user-based Google API access.
    
    First checks for existing token, then refreshes or initiates new auth flow.
    
    Returns:
        Google OAuth Credentials object
        
    Raises:
        FileNotFoundError: If oauth_client.json is missing
        ValueError: If authentication fails
    """
    creds = None
    
    # Check for existing token
    if OAUTH_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    
    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh existing token
            creds.refresh(Request())
            # Save refreshed token
            with open(OAUTH_TOKEN_PATH, "w") as token:
                token.write(creds.to_json())
        else:
            # Token doesn't exist or can't be refreshed
            # In production, this should already be set up
            raise FileNotFoundError(
                f"OAuth token not found or expired at {OAUTH_TOKEN_PATH}. "
                "Please run 'python manual_oauth.py' to generate a new token."
            )
    
    return creds


def check_oauth_status() -> dict:
    """
    Check current OAuth authentication status.
    
    Returns:
        Dict with status info (authenticated, email, expiry, etc.)
    """
    result = {
        "client_exists": OAUTH_CLIENT_PATH.exists(),
        "token_exists": OAUTH_TOKEN_PATH.exists(),
        "authenticated": False,
        "email": None,
        "expired": None,
    }
    
    if result["token_exists"]:
        try:
            creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
            result["authenticated"] = creds.valid
            result["expired"] = creds.expired if creds else None
            
            # Try to get user info
            if creds and creds.valid:
                from googleapiclient.discovery import build
                service = build("oauth2", "v2", credentials=creds)
                user_info = service.userinfo().get().execute()
                result["email"] = user_info.get("email")
        except Exception as e:
            result["error"] = str(e)
    
    return result


if __name__ == "__main__":
    """Run this directly to authenticate: python -m app.core.oauth"""
    print("=" * 60)
    print("Google OAuth Authentication Setup")
    print("=" * 60)
    
    # Check status
    status = check_oauth_status()
    
    if not status["client_exists"]:
        print(f"\n❌ OAuth client file not found!")
        print(f"   Expected location: {OAUTH_CLIENT_PATH}")
        print("\nTo set up:")
        print("1. Go to: https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 Client ID (Desktop app)")
        print("3. Download JSON and save as 'credentials/oauth_client.json'")
        exit(1)
    
    print(f"\n✅ OAuth client file found")
    
    if status["authenticated"]:
        print(f"✅ Already authenticated as: {status['email']}")
    else:
        print("\n🔐 Starting authentication flow...")
        print("   A browser window will open for Google sign-in.\n")
        
        try:
            creds = get_oauth_credentials()
            print("\n✅ Authentication successful!")
            print(f"   Token saved to: {OAUTH_TOKEN_PATH}")
            
            # Get user info
            from googleapiclient.discovery import build
            service = build("oauth2", "v2", credentials=creds)
            user_info = service.userinfo().get().execute()
            print(f"   Authenticated as: {user_info.get('email')}")
        except Exception as e:
            print(f"\n❌ Authentication failed: {e}")
            exit(1)
