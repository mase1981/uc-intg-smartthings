# SmartThings Integration for Unfolded Circle Remote 2/3

Control your SmartThings devices seamlessly with your Unfolded Circle Remote 2 or Remote 3 with comprehensive device support, **OAuth2 authentication**, and **smart polling system**.

![SmartThings](https://img.shields.io/badge/SmartThings-Cloud%20API-blue)
[![GitHub Release](https://img.shields.io/github/v/release/mase1981/uc-intg-smartthings?style=flat-square)](https://github.com/mase1981/uc-intg-smartthings/releases)
![License](https://img.shields.io/badge/license-MPL--2.0-blue?style=flat-square)
[![GitHub issues](https://img.shields.io/github/issues/mase1981/uc-intg-smartthings?style=flat-square)](https://github.com/mase1981/uc-intg-smartthings/issues)
[![Community Forum](https://img.shields.io/badge/community-forum-blue?style=flat-square)](https://unfolded.community/)
[![Discord](https://badgen.net/discord/online-members/zGVYf58)](https://discord.gg/zGVYf58)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/mase1981/uc-intg-smartthings/total?style=flat-square)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=flat-square)](https://buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-donate-blue.svg?style=flat-square)](https://paypal.me/mmiyara)
[![Github Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-30363D?&logo=GitHub-Sponsors&logoColor=EA4AAA&style=flat-square)](https://github.com/sponsors/mase1981)


## Features

This integration provides comprehensive control of your SmartThings ecosystem directly from your Unfolded Circle Remote, supporting a wide range of device types with **OAuth2 authentication** for enhanced security and reliability.

---
## ❤️ Support Development ❤️

If you find this integration useful, consider supporting development:

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/mase1981)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/mmiyara)

Your support helps maintain this integration. Thank you! ❤️
---

## Important Note

Due to SmartThings architecture, this integration uses polling rather than webhooks. There will be a delay (3-20 seconds) between state changes and remote display updates. This is a necessary trade-off to provide a free/open-source integration without requiring a public-facing SmartApp.

### 📱 **Supported Device Types**

| Device Type | Control Features | Status Updates | Examples |
|-------------|-----------------|----------------|----------|
| **Smart Lights** | On/Off, Dim, Color, Color Temp | Real-time | Philips Hue, LIFX, Sengled |
| **Smart Switches** | On/Off, Toggle | Real-time | TP-Link Kasa, Leviton, GE |
| **Smart Locks** | Lock/Unlock (as Switch) | Real-time | August, Yale, Schlage |
| **Thermostats** | Temp, Mode, Fan | Real-time | Ecobee, Honeywell |
| **Garage Doors** | Open/Close/Stop | Real-time | MyQ, Linear GoControl |
| **Smart TVs** | Power, Volume | Real-time | Samsung, LG SmartThings |
| **Sensors** | Status Monitoring | Real-time | Motion, Contact, Temp |
| **Buttons** | Press Actions | Event-based | SmartThings Button |

### ⚡ **Advanced Features**

#### **Smart Polling System**
- **Adaptive Intervals** - Faster polling for recently changed devices
- **Activity-Based** - High activity = 3sec intervals, Low activity = 20sec intervals
- **Resource Efficient** - Minimizes API calls while maintaining responsiveness
- **Batch Processing** - Optimized API usage with intelligent batching

#### **OAuth2 Security**
- **Secure Authentication** - Industry-standard OAuth2 flow
- **Token Management** - Automatic token refresh and renewal
- **SmartApp Integration** - Uses your own SmartApp for enhanced control
- **Permission Control** - Fine-grained access control through SmartThings

### **Protocol Requirements**

- **Protocol**: SmartThings Cloud API
- **Authentication**: OAuth2 with SmartApp
- **Internet Required**: Cloud-based integration
- **Network Access**: Outbound HTTPS (port 443)
- **Connection**: Smart polling with adaptive intervals

### **Network Requirements**

- **Internet Connection** - Required for SmartThings Cloud API access
- **HTTPS Access** - Outbound HTTPS traffic on port 443
- **Bandwidth** - Minimal (~1KB per device per minute)
- **Latency** - Works well with 200ms+ internet latency

## Installation

### Option 1: Remote Web Interface (Recommended)
1. Navigate to the [**Releases**](https://github.com/mase1981/uc-intg-smartthings/releases) page
2. Download the latest `uc-intg-smartthings-<version>.tar.gz` file
3. Open your remote's web interface (`http://your-remote-ip`)
4. Go to **Settings** → **Integrations** → **Add Integration**
5. Click **Upload** and select the downloaded `.tar.gz` file

### Option 2: Docker (Advanced Users)

The integration is available as a pre-built Docker image from GitHub Container Registry:

**Image**: `ghcr.io/mase1981/uc-intg-smartthings:latest`

**Docker Compose:**
```yaml
services:
  uc-intg-smartthings:
    image: ghcr.io/mase1981/uc-intg-smartthings:latest
    container_name: uc-intg-smartthings
    network_mode: host
    volumes:
      - </local/path>:/data
    environment:
      - UC_CONFIG_HOME=/data
      - UC_INTEGRATION_HTTP_PORT=9090
      - UC_INTEGRATION_INTERFACE=0.0.0.0
      - PYTHONPATH=/app
    restart: unless-stopped
```

**Docker Run:**
```bash
docker run -d --name uc-smartthings --restart unless-stopped --network host -v smartthings-config:/app/config -e UC_CONFIG_HOME=/app/config -e UC_INTEGRATION_INTERFACE=0.0.0.0 -e UC_INTEGRATION_HTTP_PORT=9090 -e PYTHONPATH=/app ghcr.io/mase1981/uc-intg-smartthings:latest
```

## Configuration

### Prerequisites

- SmartThings account with configured devices
- Internet connection for cloud API access
- Node.js and SmartThings CLI (for SmartApp creation)
- Developer Account on SmartThings Developer Portal

### Step 1: Create SmartApp

**Important**: Every user must create their own SmartApp with unique credentials.

1. **Install SmartThings CLI**:
   ```bash
   npm install -g @smartthings/cli
   ```

2. **Create SmartApp**:
   ```bash
   smartthings apps:create
   ```

3. **Follow prompts**:
   - Display name: `UC Integration SmartThings`
   - Description: `Unfolded Circle Integration SmartApp`
   - Skip icon and target URL (press Enter)

4. **CRITICAL - Select OAuth2 Scopes**:
   Must select these exact scopes:
   - ✅ `r:devices:*` (Read all devices)
   - ✅ `w:devices:*` (Write to all devices)
   - ✅ `x:devices:*` (Execute commands)
   - ✅ `r:locations:*` (Read locations)
   - ✅ `w:locations:*` (Write locations)
   - ✅ `x:locations:*` (Execute location commands)
   - ❌ DO NOT select scopes with `$` symbols

5. **Redirect URI**:
   Use exactly: `https://httpbin.org/get`

6. **Save Credentials**:
   Copy and save the OAuth Client ID and OAuth Client Secret

### Step 2: Configure Integration

1. Install the integration on your UC Remote
2. Go to **Settings** → **Integrations** → SmartThings
3. Click **"Configure"**

#### **Enter Client Credentials**:
- Client ID: Paste OAuth Client ID from SmartApp
- Client Secret: Paste OAuth Client Secret from SmartApp
- Click **"Next"**

#### **Authorization Flow**:
- Browser opens with authorization URL
- Log in to SmartThings
- Select your HOME
- Click "Authorize"
- Copy the authorization code from the redirect URL
- Paste code back into integration setup

#### **Device Selection**:
- Select SmartThings location
- Choose device types to include:
  - Lights, Switches, Climate, Covers, Media Players, Buttons, Sensors

#### **Complete Setup**:
- Click **"Complete Setup"**
- Integration creates entities for all discovered devices

## Using the Integration

### Device Control

The integration automatically creates appropriate entities for each SmartThings device:

- **Lights**: On/Off, Dimming, Color, Color Temperature
- **Switches**: On/Off, Toggle control
- **Climate**: Temperature, Mode, Fan controls
- **Covers**: Open/Close/Stop commands
- **Media Players**: Power, Volume control
- **Sensors**: Real-time status monitoring
- **Buttons**: Press action support

### Performance

- **Response Time**: 0.6-1.2 seconds average
- **Status Updates**: 3-20 second delay (adaptive polling)
- **API Optimization**: Smart rate limiting and batching
- **Network**: Handles latency and interruptions gracefully

## Credits

- **Developer**: Meir Miyara
- **SmartThings**: Samsung SmartThings Platform
- **Unfolded Circle**: Remote 2/3 integration framework (ucapi)
- **Protocol**: SmartThings Cloud API with OAuth2
- **Community**: Testing and feedback from UC community

## License

This project is licensed under the Mozilla Public License 2.0 (MPL-2.0) - see LICENSE file for details.

## Support & Community

- **GitHub Issues**: [Report bugs and request features](https://github.com/mase1981/uc-intg-smartthings/issues)
- **UC Community Forum**: [General discussion and support](https://unfolded.community/)
- **Developer**: [Meir Miyara](https://www.linkedin.com/in/meirmiyara)
- **SmartThings Support**: [Official SmartThings Support](https://support.smartthings.com/)

---

**Made with ❤️ for the Unfolded Circle and SmartThings Communities**

**Thank You**: Meir Miyara
