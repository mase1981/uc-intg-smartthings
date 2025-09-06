"""
SmartThings OAuth2 Client Implementation
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import asyncio
import logging
import time
import urllib.parse
from typing import Dict, Optional, Tuple
import aiohttp

_LOG = logging.getLogger(__name__)


class SmartThingsOAuth2:
    """OAuth2 client for SmartThings authentication."""
    
    CLIENT_ID = "uc-smartthings-integration"  # Placeholder - need real registration
    CLIENT_SECRET = "your-client-secret"      # Placeholder - need real registration
    
    OAUTH_BASE_URL = "https://account.smartthings.com/oauth"
    TOKEN_URL = "https://api.smartthings.com/oauth/token"
    
    SCOPES = [
        "r:devices:*",        # Read all devices
        "x:devices:*",        # Control all devices  
        "r:locations:*",      # Read all locations
        "r:apps:*",           # Read applications
        "x:apps:*",           # Manage applications
        "r:scenes:*",         # Read scenes
        "x:scenes:*",         # Execute scenes
    ]
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session and not self._session.closed:
            await self._session.close()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def generate_auth_url(self, state: str = None) -> str:
        """Generate OAuth2 authorization URL for user login."""
        params = {
            "client_id": self.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": "https://localhost:8080/callback",  # Dummy redirect
            "scope": " ".join(self.SCOPES),
        }
        
        if state:
            params["state"] = state
            
        query_string = urllib.parse.urlencode(params)
        auth_url = f"{self.OAUTH_BASE_URL}/authorize?{query_string}"
        
        _LOG.info(f"Generated OAuth2 authorization URL")
        return auth_url

    def extract_code_from_callback_url(self, callback_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract authorization code and state from callback URL."""
        try:
            parsed = urllib.parse.urlparse(callback_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            
            code = query_params.get("code", [None])[0]
            state = query_params.get("state", [None])[0]
            error = query_params.get("error", [None])[0]
            
            if error:
                _LOG.error(f"OAuth2 authorization error: {error}")
                return None, None
                
            if not code:
                _LOG.error("No authorization code found in callback URL")
                return None, None
                
            _LOG.info("Successfully extracted authorization code from callback URL")
            return code, state
            
        except Exception as e:
            _LOG.error(f"Failed to parse callback URL: {e}")
            return None, None

    async def exchange_code_for_tokens(self, authorization_code: str) -> Optional[Dict[str, any]]:
        """Exchange authorization code for access and refresh tokens."""
        token_data = {
            "grant_type": "authorization_code",
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "code": authorization_code,
            "redirect_uri": "https://localhost:8080/callback",
        }
        
        try:
            async with self:
                async with self._session.post(
                    self.TOKEN_URL,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        _LOG.error(f"Token exchange failed: {response.status} - {error_text}")
                        return None
                    
                    tokens = await response.json()
                    
                    # Add metadata
                    tokens["created_at"] = time.time()
                    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
                    
                    _LOG.info("Successfully exchanged authorization code for tokens")
                    _LOG.info(f"Access token expires in {tokens.get('expires_in', 'unknown')} seconds")
                    
                    return tokens
                    
        except Exception as e:
            _LOG.error(f"Failed to exchange authorization code: {e}")
            return None

    async def refresh_access_token(self, refresh_token: str) -> Optional[Dict[str, any]]:
        """Refresh access token using refresh token."""
        token_data = {
            "grant_type": "refresh_token", 
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "refresh_token": refresh_token,
        }
        
        try:
            async with self:
                async with self._session.post(
                    self.TOKEN_URL,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        _LOG.error(f"Token refresh failed: {response.status} - {error_text}")
                        return None
                    
                    tokens = await response.json()
                    
                    # Add metadata
                    tokens["created_at"] = time.time()
                    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
                    
                    # Preserve original refresh token if new one not provided
                    if "refresh_token" not in tokens:
                        tokens["refresh_token"] = refresh_token
                        
                    _LOG.info("Successfully refreshed access token")
                    return tokens
                    
        except Exception as e:
            _LOG.error(f"Failed to refresh access token: {e}")
            return None

    def is_token_expired(self, tokens: Dict[str, any], buffer_seconds: int = 300) -> bool:
        """Check if access token is expired or will expire soon."""
        if not tokens or "expires_at" not in tokens:
            return True
            
        return time.time() >= (tokens["expires_at"] - buffer_seconds)

    def get_token_remaining_time(self, tokens: Dict[str, any]) -> float:
        """Get remaining time until token expiry in seconds."""
        if not tokens or "expires_at" not in tokens:
            return 0.0
            
        remaining = tokens["expires_at"] - time.time()
        return max(0.0, remaining)


class OAuth2TokenManager:
    """Manages OAuth2 token storage and refresh logic."""
    
    def __init__(self, oauth2_client: SmartThingsOAuth2, config_manager):
        self.oauth2_client = oauth2_client
        self.config_manager = config_manager
        self._tokens: Optional[Dict[str, any]] = None
        self._refresh_lock = asyncio.Lock()

    async def get_valid_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if necessary."""
        async with self._refresh_lock:
            # Load tokens if not cached
            if not self._tokens:
                config = self.config_manager.load_config()
                self._tokens = config.get("oauth2_tokens")
                
            if not self._tokens:
                _LOG.error("No OAuth2 tokens available")
                return None
            
            # Check if token needs refresh
            if self.oauth2_client.is_token_expired(self._tokens):
                _LOG.info("Access token expired, attempting refresh...")
                
                refreshed_tokens = await self.oauth2_client.refresh_access_token(
                    self._tokens["refresh_token"]
                )
                
                if refreshed_tokens:
                    self._tokens = refreshed_tokens
                    await self._save_tokens(refreshed_tokens)
                    _LOG.info("Successfully refreshed access token")
                else:
                    _LOG.error("Failed to refresh access token")
                    return None
            
            return self._tokens.get("access_token")

    async def store_initial_tokens(self, tokens: Dict[str, any]) -> bool:
        """Store initial OAuth2 tokens from authorization flow."""
        try:
            self._tokens = tokens
            await self._save_tokens(tokens)
            _LOG.info("Successfully stored initial OAuth2 tokens")
            return True
        except Exception as e:
            _LOG.error(f"Failed to store OAuth2 tokens: {e}")
            return False

    async def _save_tokens(self, tokens: Dict[str, any]):
        """Save tokens to configuration."""
        try:
            current_config = self.config_manager.load_config()
            current_config["oauth2_tokens"] = tokens
            
            # Remove old PAT token if present
            if "access_token" in current_config:
                del current_config["access_token"]
                
            self.config_manager.save_config(current_config)
        except Exception as e:
            _LOG.error(f"Failed to save OAuth2 tokens to config: {e}")
            raise

    def get_token_status(self) -> Dict[str, any]:
        """Get current token status information."""
        if not self._tokens:
            config = self.config_manager.load_config()
            self._tokens = config.get("oauth2_tokens")
            
        if not self._tokens:
            return {
                "has_tokens": False,
                "is_expired": True,
                "remaining_hours": 0,
                "status": "no_tokens"
            }
        
        is_expired = self.oauth2_client.is_token_expired(self._tokens)
        remaining_time = self.oauth2_client.get_token_remaining_time(self._tokens)
        
        return {
            "has_tokens": True,
            "is_expired": is_expired,
            "remaining_hours": remaining_time / 3600,
            "status": "expired" if is_expired else "valid"
        }