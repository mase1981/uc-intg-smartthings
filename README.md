# SmartThings Integration for Unfolded Circle Remote 2/3

Control your SmartThings devices seamlessly with your Unfolded Circle Remote 2 or Remote 3.

![SmartThings](https://img.shields.io/badge/SmartThings-Cloud%20API-blue)
![Version](https://img.shields.io/badge/version-2.1.0-green)
![License](https://img.shields.io/badge/license-MPL--2.0-orange)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg)](https://buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-donate-blue.svg)](https://paypal.me/mmiyara)

## Features

This integration provides comprehensive control of your SmartThings ecosystem directly from your Unfolded Circle Remote, supporting a wide range of device types with **OAuth2 authentication** for enhanced security and reliability.

## Important

Due to the way SmartThings works, to make this integration free/Open Source without the mandatory requirement for a public facing SmartApp (webhooks) I had to use a Pull Method. The downside is that there will be a delay between state change and what the remote will reflect on the screen - This is a trade off to get this integration to work. At some point in the future when UC Team makes SmartThings integration baked into the remote firmware, they will most likely host and maintain their own SmartApp (webhooks) with WWST (Work With SmartThings) Certification.

## What's New in Version 2.1.0

- **OAuth2 Authentication**: Enhanced security with proper OAuth2 flow
- **SmartApp Integration**: Uses your own SmartApp for authentication
- **Improved Reliability**: Better session management and reconnection handling
- **Enhanced Setup**: Step-by-step SmartApp creation and configuration
- **Optimized Performance**: 0.6s average response time with smart polling

### Supported Device Types

The integration automatically detects and categorizes your configured SmartThings devices

## Device Support Matrix

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

#### Device Support Details

- **Lights**: *Supports: On/Off, Dimming, Color Control, Color Temperature, Toggle*
- **Switches & Outlets**: *Supports: On/Off Control, Toggle, Power Monitoring (where available)*
- **Security & Access**: *Note: Locks appear as switches for easy control (ON=Locked, OFF=Unlocked)*
- **Climate Control**: *Supports: Temperature Control, Mode Setting (Heat/Cool/Auto), Current Temperature Display*
- **Covers & Access Control**: *Supports: Open/Close/Stop Commands, Position Control (where supported)*
- **Media & Entertainment**: *Supports: Power On/Off, Volume Control, Play/Pause (where supported)*
- **Sensors & Monitoring**: *Provides: Real-time sensor readings, status monitoring, alerts*
- **Buttons & Controls**: *Supports: Single Press, Long Press Actions (device dependent)*

### Advanced Features

#### **Smart Polling System**
- **Adaptive Intervals**: Faster polling for recently changed devices
- **Activity-Based**: High activity = 3sec intervals, Low activity = 20sec intervals  
- **Resource Efficient**: Minimizes API calls while maintaining responsiveness
- **Batch Processing**: Optimized API usage with intelligent batching

#### **OAuth2 Security**
- **Secure Authentication**: Industry-standard OAuth2 flow
- **Token Management**: Automatic token refresh and renewal
- **SmartApp Integration**: Uses your own SmartApp for enhanced control
- **Permission Control**: Fine-grained access control through SmartThings

## Prerequisites

- Unfolded Circle Remote 2 or Remote 3
- SmartThings account with configured devices
- SmartThings Hub or compatible devices
- Internet connection for cloud API access
- **Node.js and SmartThings CLI** (for SmartApp creation)
- **Developer Account** on SmartThings Developer Portal

## Installation
***NOTE:*** Before proceeding with installation, you must go through the configuration and create a SmartApp, this might be overwhelming task, but extremely easy guided steps - without it - this integration will not work.
### Option 1: Remote Web Interface (Recommended)
1. Navigate to the [**Releases**](https://github.com/mase1981/uc-intg-smartthings/releases) page
2. Download the latest `uc-intg-smartthings-<version>.tar.gz` file
3. Open your remote's web interface (`http://your-remote-ip`)
4. Go to **Settings** → **Integrations** → **Add Integration**
5. Click **Upload** and select the downloaded `.tar.gz` file

### Option 2: Docker (Advanced Users)
For users running Docker environments:

**Docker Compose:**
```yaml
version: '3.8'
services:
  smartthings-integration:
    image: mase1981/uc-intg-smartthings:latest
    container_name: smartthings-integration
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config:/app/config
    environment:
      - UC_INTEGRATION_INTERFACE=0.0.0.0
      - UC_INTEGRATION_HTTP_PORT=9090
```

**Docker Run:**
```bash
docker run -d --restart=unless-stopped --net=host \
  -v $(pwd)/config:/app/config \
  -e UC_INTEGRATION_INTERFACE=0.0.0.0 \
  -e UC_INTEGRATION_HTTP_PORT=9090 \
  --name smartthings-integration \
  mase1981/uc-intg-smartthings:latest
```

## Configuration - Complete Setup Guide

**Important**: Every user must create their own SmartApp with unique credentials. Never share SmartApp credentials for security reasons.

### Step 1: Install SmartThings CLI

The SmartThings CLI is a **Node.js application** required to create and manage your SmartApp.

***NOTE:*** You may use Windows Powershell or Mac terminal. Below are seperate instructions to help with whichever option you choose. Bottom line you need to install nodejs and smartthings CLI


#### **Windows Installation (Command Prompt/PowerShell):**

1. **Install Node.js:**
   - Download from [nodejs.org](https://nodejs.org/) (LTS version recommended)
   - Run the installer and follow prompts
   - **Restart your computer** after installation

2. **Verify Node.js Installation:**
   
   **In Command Prompt:**
   ```cmd
   node --version
   npm --version
   ```
   
   **In PowerShell:**
   ```powershell
   node --version
   npm --version
   ```
   
   **In Visual Studio Terminal (PowerShell):**
   - Open Visual Studio: **View** → **Terminal** (or `Ctrl+``)
   - Select **PowerShell** as terminal type
   ```powershell
   node --version
   npm --version
   ```

3. **Install SmartThings CLI:**
   
   **In Command Prompt:**
   ```cmd
   npm install -g @smartthings/cli
   ```
   
   **In PowerShell/Visual Studio Terminal:**
   ```powershell
   npm install -g @smartthings/cli
   ```
   
   **If you get execution policy errors in PowerShell:**
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

4. **Verify CLI Installation:**
   ```cmd
   smartthings --version
   ```

#### **macOS Installation (Terminal):**

1. **Install Node.js:**
   ```bash
   # Using Homebrew (recommended)
   brew install node
   
   # Or download from nodejs.org
   ```

2. **Install SmartThings CLI:**
   ```bash
   npm install -g @smartthings/cli
   ```

3. **Verify CLI Installation:**
   ```bash
   smartthings --version
   ```

#### **Linux Installation:**

1. **Install Node.js:**
   ```bash
   # Ubuntu/Debian
   curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
   sudo apt-get install -y nodejs
   
   # CentOS/RHEL/Fedora
   curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
   sudo dnf install nodejs npm
   ```

2. **Install SmartThings CLI:**
   ```bash
   sudo npm install -g @smartthings/cli
   ```

3. **Verify CLI Installation:**
   ```bash
   smartthings --version
   ```

### Step 2: Authenticate with SmartThings CLI

1. **Start the SmartApp Process:**
   ```bash
   smartthings apps:create
   ```
   
2. **Follow the prompts: The CLI will guide you through providing the required information for your app, which typically includes:**

***Note:*** During this step you will be asked to log into your smartthings account, do so to create the authenticastion, after succesful login you will see in terminal "Login successful" or similar.

- A display name for your integration: ```UC Integration```
- A description for your integration: ```Unfolded Circle Integration SmartApp```
- An icon image URL (optional). ```SKIP THIS BY CLICKING ENTER```
 - The target URL of the hosting location of your SmartApp: ```SKIP THIS BY CLICKING ENTER```
 - The permissions (scopes) required by your app: ```toogle everything for simplicity```
 - The redirect URIs: ```https://httpbin.org/get```

    **Important**: This specific redirect URI has been tested and confirmed working with the integration.

- At the end of this process you will recieve an output with the below information ***MAKE SURE TO COPY SAFELY AND NEVER SHARE THIS INFORMATION - YOU WILL NEED THIS INFORMATION:***
   - **Client ID**: Long UUID string (e.g., `12345678-1234-1234-1234-123456789abc`)
   - **Client Secret**: Another long string (e.g., `abcdef12-3456-7890-abcd-ef1234567890`)


### Step 3: Verify

1. Open your smartthings app on your phone

2. Go to Menu

3. Click on the gear at the top right 


4. Click on Linked Services and validate you now see ```smartthings-cli```

### Step 4: Configure UC Remote Integration

1. After completing buidling the smartthings SmartApp, proceed with installing the integration on your UC Remote, go to **Settings** → **Integrations**
2. Upload the tar.gz latest from the Github releases section
3. Once uplaoded click on it and follow the setup wizard:

#### **OAuth2 Setup Process:**

1. **Enter Your Client Credentials:**
   - **Client ID**: Paste your Client ID from Step 2
   - **Client Secret**: Paste your Client Secret from Step 2
   - Click **"Next"**

2. **Authorization Flow:**
   - Integration will display an authorization URL - it should automatically open a new tab, if not:
   - Click the link or copy it to your browser
   - Log in to SmartThings if prompted
   - Authorize the integration by choosing HOME from the dropdown and click Authorize
   - You'll be redirected to `https://httpbin.org/get` new page
   - **Look for the authorization code** in the URL or JSON response
   - Find: `"code": "your-authorization-code-here"`
   - **Copy only the code value** (not the entire URL) Should be a string of 5 characters
   - Paste the authorization code back into the integration

3. **Location Selection:**
   - Integration will discover your SmartThings locations
   - Select the location containing your devices

4. **Device Configuration:**
   - Choose which device types to include:
     - ✅ **Lights** (Recommended)
     - ✅ **Switches** (Recommended) 
     - ✅ **Climate** (Thermostats)
     - ✅ **Covers** (Doors, Shades)
     - ✅ **Media Players** (TVs, Speakers)
     - ✅ **Buttons** (Smart Buttons)
     - ⚠️ **Sensors** (Monitoring only - optional)

5. **Polling Configuration:**
   - **Base Interval**: 8-12 seconds (auto-optimized based on device count)
   - Integration will recommend optimal settings

6. **Complete Setup:**
   - Click **"Complete Setup"**
   - Integration will create entities for all discovered devices

### Step 8: Add Entities to Activities

1. Go to **Activities** in your remote interface
2. Edit or create an activity
3. Add SmartThings entities from the **Available Entities** list
4. Configure button mappings as desired
5. Save your activity

## Troubleshooting SmartApp Creation

### Common CLI Issues

#### **"Command not found: smartthings"**
```bash
# Windows: Restart Command Prompt/PowerShell after Node.js installation
# Verify npm global path
npm config get prefix

# Linux/macOS: Fix npm permissions
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH=~/.npm-global/bin:$PATH

# Add to your shell profile (.bashrc, .zshrc, etc.)
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
```

#### **"Permission denied" errors**
```bash
# Windows: Run as Administrator
# Linux/macOS: Fix npm permissions (see above) or use sudo for installation only
sudo npm install -g @smartthings/cli
```

#### **CLI authentication issues**
```bash
# Clear CLI cache and re-authenticate
smartthings logout
smartthings login
```

### SmartApp Configuration Issues

#### **"Invalid redirect URI" error**
- Ensure you're using exactly: `https://httpbin.org/get`
- Check for extra spaces or characters
- Update the redirect URI:
  ```bash
  smartthings apps:oauth:update [YOUR_APP_ID]
  ```

#### **OAuth2 scope issues**
- Verify all required scopes are enabled:
  ```bash
  smartthings apps:oauth [YOUR_APP_ID]
  ```
- Required scopes: `r:devices:*`, `w:devices:*`, `x:devices:*`, `r:locations:*`

#### **App installation fails**
```bash
# Check app status
smartthings apps [YOUR_APP_ID]

# Try reinstalling
smartthings apps:uninstall [INSTALLATION_ID]
smartthings apps:install [YOUR_APP_ID]
```

### Integration Setup Issues

#### **"Invalid Client Credentials"**
- Double-check Client ID and Client Secret for typos
- Ensure no extra spaces when copying
- Verify SmartApp is properly installed
- Check that OAuth2 is configured on the SmartApp

#### **"Authorization Code Invalid"**
- Authorization codes expire quickly (10 minutes)
- Get a fresh code by restarting the authorization flow
- Ensure you're copying only the code value, not the entire URL
- Example: If you see `"code": "ABC123DEF456"`, copy `ABC123DEF456`

#### **"No Devices Found"**
- Verify SmartApp installation includes device permissions
- Check that devices are online in SmartThings app
- Ensure correct location selection
- Verify app has all required scopes

#### **Response Time Issues**
Commands typically take 0.6-1.2 seconds, which is optimal for this type of integration. If you experience slower responses:
- Check internet connection stability
- Verify SmartThings cloud service status
- Consider reducing polling intervals if you have many devices

## Performance & Optimization

### **API Usage Optimization**
- Smart Rate Limiting: Tracks requests and prevents exceeding 8 requests per 10 seconds
- Single Verification Strategy: Only 1 verification attempt after 0.5 seconds
- Adaptive Polling: 15-30 seconds between polls, pauses during commands
- Graceful Error Handling: Handles 429 errors and falls back to polling

### **Network Requirements**
- **Bandwidth**: Minimal (~1KB per device per minute)
- **Latency**: Works well with 200ms+ internet latency
- **Reliability**: Handles network interruptions gracefully and Remote reboots
- **Firewall**: Only outbound HTTPS (port 443) required

## Limitations

### **SmartThings API Limitations**
- **No Webhooks**: Third-party integrations cannot receive real-time push notifications
- **Rate Limits**: 250 requests per minute per token (well managed by integration)
- **Cloud Dependency**: Requires internet connection and SmartThings cloud service
- **Device Support**: Limited to devices with SmartThings cloud integration

### **Integration Limitations**  
- **Local Control**: Cannot control local-only devices (requires SmartThings cloud)
- **Custom Capabilities**: Advanced custom device capabilities may not be supported
- **Real-time Events**: 3-20 second delay for status updates (optimized by smart polling)
- **Scenes**: Basic scene support (full scene management requires SmartThings app)

## For Developers

### Local Development

1. **Clone and setup:**
   ```bash
   git clone https://github.com/mase1981/uc-intg-smartthings.git
   cd uc-intg-smartthings
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configuration:**
   Create configuration file with your OAuth2 credentials from your SmartApp

3. **Run integration:**
   ```bash
   python -m uc_intg_smartthings.driver
   ```

### Project Structure

```
uc-intg-smartthings/
├── uc_intg_smartthings/        # Main package
│   ├── __init__.py             # Package info  
│   ├── client.py               # SmartThings API client with OAuth2
│   ├── config.py               # Configuration management
│   ├── driver.py               # Main integration driver
│   ├── entities.py             # Entity factory & optimization
│   ├── entity_mapping.py       # Device type mapping
│   └── setup_flow.py           # OAuth2 setup wizard
├── .github/workflows/          # GitHub Actions
├── driver.json                 # Integration metadata
├── requirements.txt            # Dependencies
├── pyproject.toml              # Python project config
└── README.md                   # This file
```

### Development Notes

- **SmartThings CLI**: Node.js application for SmartApp management
- **Integration Code**: Python application using pip for dependencies
- **Two Different Environments**: CLI (Node.js) vs Integration (Python)

## Security Notes

- **Never share your SmartApp credentials** (Client ID/Secret)
- **Keep authorization codes private** and use them immediately
- **Each user must create their own SmartApp** for security
- **Credentials are stored locally** on your UC Remote only

## License

This project is licensed under the Mozilla Public License 2.0 - see the [LICENSE](LICENSE) file for details.

## Credits

- **Developer**: Meir Miyara
- **SmartThings API**: Samsung SmartThings Platform
- **Unfolded Circle**: Remote 2/3 integration framework
- **OAuth2 Implementation**: Enhanced security and reliability

## Support & Community

- **GitHub Issues**: [Report bugs and request features](https://github.com/mase1981/uc-intg-smartthings/issues)
- **UC Community Forum**: [General discussion and support](https://unfolded.community/)
- **Developer**: [Meir Miyara](mailto:meir.miyara@gmail.com)

---

**Made with ❤️ for the Unfolded Circle Community** 

**Thank You**: Meir Miyara