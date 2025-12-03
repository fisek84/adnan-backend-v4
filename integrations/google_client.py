import json
import httpx
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class GoogleAuthError(Exception):
    """Raised for all Google authentication errors."""
    pass


class GoogleClientConfig(BaseModel):
    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    redirect_uri: str = Field(..., description="Authorized redirect URI")
    scope: str = Field(..., description="Requested permissions scope")
    token_url: str = "https://oauth2.googleapis.com/token"
    auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"


class GoogleClient:
    """
    Production-ready Google API client.
    Handles OAuth flow, token exchange, refresh operations,
    and safe HTTP calls to Google endpoints.
    """

    def __init__(self, config: GoogleClientConfig):
        self.config = config
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    # ----------------------------------------------------------------------
    # STEP 1 — Generate OAuth Authorization URL
    # ----------------------------------------------------------------------
    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        URL that user should open to authorize the application.
        """

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": self.config.scope,
            "access_type": "offline",
            "prompt": "consent"
        }

        if state:
            params["state"] = state

        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.config.auth_url}?{query}"

    # ----------------------------------------------------------------------
    # STEP 2 — Exchange auth code for tokens
    # ----------------------------------------------------------------------
    async def exchange_code(self, code: str) -> Dict[str, Any]:
        payload = {
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code"
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.config.token_url, data=payload)

        if not response.is_success:
            raise GoogleAuthError(f"Token exchange failed: {response.text}")

        data = response.json()
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")

        return data

    # ----------------------------------------------------------------------
    # STEP 3 — Refresh expired token
    # ----------------------------------------------------------------------
    async def refresh_access_token(self) -> str:
        if not self.refresh_token:
            raise GoogleAuthError("Cannot refresh token — no refresh_token present")

        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.config.token_url, data=payload)

        if not response.is_success:
            raise GoogleAuthError(f"Token refresh failed: {response.text}")

        data = response.json()
        self.access_token = data["access_token"]
        return self.access_token

    # ----------------------------------------------------------------------
    # STEP 4 — Authorized Google API request
    # ----------------------------------------------------------------------
    async def request(self, method: str, url: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        if not self.access_token:
            raise GoogleAuthError("Google API call attempted without access token")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=headers, json=json)

        if response.status_code == 401:
            # Auto refresh token and retry once
            await self.refresh_access_token()
            return await self.request(method, url, json=json)

        if not response.is_success:
            raise GoogleAuthError(f"Google API Error {response.status_code}: {response.text}")

        return response.json()