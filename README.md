# SmartThings Integration for Unfolded Circle Remote 2/3

Control your Samsung SmartThings smart home devices directly from your Unfolded Circle Remote 2 or Remote 3 with comprehensive device control, **real-time state monitoring**, and **OAuth2-based secure authentication**.

![SmartThings](https://img.shields.io/badge/SmartThings-Smart%20Home-blue)
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

This integration provides comprehensive control of Samsung SmartThings devices through the official SmartThings REST API with OAuth2 authentication, delivering seamless integration with your Unfolded Circle Remote for complete smart home control.

---
## Support Development

If you find this integration useful, consider supporting development:

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/mase1981)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/mmiyara)

Your support helps maintain this integration. Thank you!

---

### Supported Device Types

| Device Type | Entity | Features |
|-------------|--------|----------|
| **Lights** | Light | On/Off, Brightness, Color Temperature, RGB Color |
| **Switches** | Switch | On/Off |
| **Thermostats** | Climate | Temperature, HVAC Mode, Fan Mode |
| **Blinds/Shades** | Cover | Open/Close, Position |
| **TVs/Speakers** | Media Player | On/Off, Volume, Mute, Source |
| **Sensors** | Sensor | Temperature, Humidity, Motion, Contact, Battery |
| **Scenes** | Select | Execute SmartThings Scenes |
| **Modes** | Select | Set SmartThings Location Modes |
| **Buttons** | Button | Press to execute scene |

### Light Control

- **On/Off** - Toggle light state
- **Brightness** - Adjust brightness level (0-100%)
- **Color Temperature** - Warm to cool white adjustment
- **RGB Color** - Full color control for color-capable lights
- **Real-time Updates** - Instant state feedback via polling

### Switch Control

- **On/Off** - Toggle switch state
- **Real-time Updates** - Instant state feedback

### Climate Control

- **Temperature** - Set target temperature
- **HVAC Mode** - Heat, Cool, Auto, Off
- **Fan Mode** - Auto, Low, Medium, High
- **Current Temperature** - Real-time reading
- **Humidity** - Current humidity level (if supported)

### Cover Control

- **Open/Close** - Fully open or close
- **Position** - Set specific position (0-100%)
- **Stop** - Stop current movement

### Media Player Control

- **On/Off** - Power control
- **Volume** - Volume level adjustment
- **Mute** - Toggle mute state
- **Source** - Input source selection
- **Playback** - Play, Pause, Stop, Next, Previous

### Sensor Monitoring

| Sensor Type | Description |
|-------------|-------------|
| Temperature | Current temperature reading |
| Humidity | Relative humidity percentage |
| Motion | Motion detected / Clear |
| Contact | Open / Closed state |
| Battery | Battery level percentage |
| Presence | Present / Away |
| Power | Energy consumption |

### Scenes & Modes (NEW in v3.0)

- **Scenes** - Select entity to execute any SmartThings scene
- **Modes** - Select entity to switch between location modes (Home, Away, Night, etc.)
- **Button Entities** - Quick-press buttons for favorite scenes

### Protocol Requirements

- **Protocol**: SmartThings REST API v1
- **Authentication**: OAuth2 (Authorization Code Flow)
- **Connection**: Cloud-based with polling for state updates
- **Polling Interval**: Configurable (default 10 seconds)
- **Rate Limiting**: Built-in protection (8 requests per 10 seconds)

### Network Requirements

- **Internet Access** - Required for SmartThings cloud API
- **HTTPS Protocol** - Secure OAuth2 authentication
- **SmartThings Account** - Samsung account with SmartThings

---

## Prerequisites

Before installing this integration, you need to create a SmartThings OAuth2 application:

### Step 1: Create SmartThings Developer Account

1. Go to [SmartThings Developer Workspace](https://smartthings.developer.samsung.com/workspace/projects)
2. Sign in with your Samsung account
3. Accept the developer terms if prompted

### Step 2: Create OAuth2 Application

1. Click **"New Project"**
2. Select **"Consumer"** project type
3. Fill in project details:
   - **Project Name**: "Unfolded Circle Integration"
   - **Description**: "Control SmartThings from UC Remote"
4. Click **"Add App Credentials"**
5. Configure OAuth settings:
   - **OAuth Client ID**: Auto-generated (copy this)
   - **OAuth Client Secret**: Click to reveal and copy
   - **Redirect URI**: Add `https://httpbin.org/get`
   - **Scopes**: Select:
     - `r:devices:*` - Read devices
     - `x:devices:*` - Execute device commands
     - `r:locations:*` - Read locations
     - `r:scenes:*` - Read scenes
     - `x:scenes:*` - Execute scenes

6. Save your **Client ID** and **Client Secret** securely

---

## Installation

### Option 1: Remote Web Interface (Recommended)

1. Navigate to the [**Releases**](https://github.com/mase1981/uc-intg-smartthings/releases) page
2. Download the latest `uc-intg-smartthings-<version>-aarch64.tar.gz` file
3. Open your remote's web interface (`http://your-remote-ip`)
4. Go to **Settings** > **Integrations** > **Add Integration**
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
docker run -d --name uc-smartthings --restart unless-stopped --network host \
  -v smartthings-config:/app/config \
  -e UC_CONFIG_HOME=/app/config \
  -e UC_INTEGRATION_INTERFACE=0.0.0.0 \
  -e UC_INTEGRATION_HTTP_PORT=9090 \
  -e PYTHONPATH=/app \
  ghcr.io/mase1981/uc-intg-smartthings:latest
```

## Configuration

### Step 1: Start Setup

1. After installation, go to **Settings** > **Integrations**
2. The SmartThings integration should appear in **Available Integrations**
3. Click **"Configure"** to begin setup

### Step 2: Enter OAuth Credentials

1. Enter your **OAuth Client ID** from SmartThings Developer Workspace
2. Enter your **OAuth Client Secret**
3. Click **Next**

### Step 3: Authorize SmartThings

1. You will see an authorization URL
2. Open this URL in a web browser on your phone or computer
3. Log in with your Samsung account
4. Authorize the application
5. You will be redirected to `https://httpbin.org/get?code=XXXXX`
6. Copy the **code** parameter from the URL
7. Paste the authorization code in the Remote setup

### Step 4: Select Location and Device Types

1. Select your SmartThings **Location** from the dropdown
2. Choose which device types to include:
   - Lights
   - Switches
   - Sensors
   - Climate
   - Covers
   - Media Players
3. Click **Complete Setup**

### Step 5: Configure Entities

The integration will create entities for all compatible devices:
- Lights, switches, climate, covers, media players
- Sensors for temperature, humidity, motion, contact
- Select entities for scenes and modes
- Button entities for quick scene activation

---

## Using the Integration

### Light Entities

Control smart lights with full feature support:
- Toggle on/off from activities or directly
- Adjust brightness with slider
- Change color temperature
- Set RGB color (if supported)

### Climate Entities

Control thermostats and HVAC:
- Set target temperature
- Switch between heat/cool/auto modes
- Adjust fan speed
- View current temperature and humidity

### Sensor Entities

Monitor environmental sensors:
- Temperature sensors show current readings
- Motion sensors show detected/clear state
- Contact sensors show open/closed state
- Battery sensors show charge level

### Scene Selection (NEW)

Execute SmartThings scenes via Select entity:
- Shows all available scenes in your location
- Choose a scene to execute it immediately
- Perfect for "Good Night" or "Movie Time" scenes

### Mode Selection (NEW)

Switch between location modes via Select entity:
- Home, Away, Night modes
- Custom modes you've created
- Affects all automations tied to modes

---

## Troubleshooting

### Authorization Failed

- Verify Client ID and Client Secret are correct
- Ensure redirect URI is exactly `https://httpbin.org/get`
- Check that all required scopes are selected

### Devices Not Appearing

- Verify devices are in the selected location
- Check device type filters in setup
- Some device types may not be supported yet

### Commands Not Working

- Check device is online in SmartThings app
- Verify OAuth scopes include execute permissions
- Check device supports the command capability

### Token Refresh Errors

- Tokens are refreshed automatically before expiration
- If persistent issues, re-run setup flow
- Check SmartThings developer workspace for app status

---

## Credits

- **Developer**: Meir Miyara
- **Samsung SmartThings**: Smart home platform and API
- **Unfolded Circle**: Remote 2/3 integration framework (ucapi)
- **Community**: Testing and feedback from UC community

## License

This project is licensed under the Mozilla Public License 2.0 (MPL-2.0) - see LICENSE file for details.

## Support & Community

- **GitHub Issues**: [Report bugs and request features](https://github.com/mase1981/uc-intg-smartthings/issues)
- **UC Community Forum**: [General discussion and support](https://unfolded.community/)
- **Developer**: [Meir Miyara](https://www.linkedin.com/in/meirmiyara)
- **SmartThings Support**: [Official SmartThings Support](https://support.smartthings.com/)

---

**Made with love for the Unfolded Circle and SmartThings Communities**

**Thank You**: Meir Miyara
