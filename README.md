# SmartThings Integration for Unfolded Circle Remote 2/3

Control your SmartThings devices seamlessly with your Unfolded Circle Remote 2 or Remote 3.

![SmartThings](https://img.shields.io/badge/SmartThings-Cloud%20API-blue)
![Version](https://img.shields.io/badge/version-1.1.9-green)
![License](https://img.shields.io/badge/license-MPL--2.0-orange)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg)](https://buymeacoffee.com/meirmiyara)
[![PayPal](https://img.shields.io/badge/PayPal-donate-blue.svg)](https://paypal.me/mmiyara)

## Features

This integration provides comprehensive control of your SmartThings ecosystem directly from your Unfolded Circle Remote, supporting a wide range of device types

## Important

Due to the way Smartthings work, to make this integration Free/Open Source without the mandatory requirement for a hosted public facing SmartApp (webhooks) i had to use a Pull Method, the downside is that there will be a delay between state change and what the remote will reflect on the screen - This is a trade off to get this integration to work. At some point in the future when UC Team make Smartthings integration baked into the remote firmware, they will most likely to host and maintain their own SmartApp (webhooks) with WWST (Work With Smartthings) Certification. 
### 🏠 Supported Device Types

The integration automatically detects and categorizes your configured SmartThings devices

## Device Support Matrix

| Device Type | Control Features | Status Updates | Examples |
|-------------|-----------------|----------------|----------|
| 💡 **Smart Lights** | On/Off, Dim, Color, Color Temp | Real-time | Philips Hue, LIFX, Sengled |
| 🔌 **Smart Switches** | On/Off, Toggle | Real-time | TP-Link Kasa, Leviton, GE |  
| 🔒 **Smart Locks** | Lock/Unlock (as Switch) | Real-time | August, Yale, Schlage |
| 🌡️ **Thermostats** | Temp, Mode, Fan | Real-time | Ecobee, Honeywell |
| 🏠 **Garage Doors** | Open/Close/Stop | Real-time | MyQ, Linear GoControl |
| 📺 **Smart TVs** | Power, Volume | Real-time | Samsung, LG SmartThings |
| 📊 **Sensors** | Status Monitoring | Real-time | Motion, Contact, Temp |
| 🔘 **Buttons** | Press Actions | Event-based | SmartThings Button |


#### NOTES: Due to Smartthings large devices support, some devices might not be recognized properly - did my best to generalize and categorize
- **Lights**: *Supports: On/Off, Dimming, Color Control, Color Temperature, Toggle*

- **Switches & Outlets**: *Supports: On/Off Control, Toggle, Power Monitoring (where available)*

- **Switches & Outlets**: *Supports: On/Off Control, Toggle, Power Monitoring (where available)*

- **Security & Access**: *Note: Locks appear as switches for easy control (ON=Locked, OFF=Unlocked)*

- **Climate Control**: *Supports: Temperature Control, Mode Setting (Heat/Cool/Auto), Current Temperature Display*

- **Covers & Access Control**: *Supports: Open/Close/Stop Commands, Position Control (where supported)*

- **Climate Control**: *Supports: Temperature Control, Mode Setting (Heat/Cool/Auto), Current Temperature Display*

- **Media & Entertainment**: *Supports: Power On/Off, Volume Control, Play/Pause (where supported)*


- **Sensors & Monitoring**: *Provides: Real-time sensor readings, status monitoring, alerts*


- **Buttons & Controls**: *Supports: Single Press, Long Press Actions (device dependent)*




### 🚀 **Advanced Features**

#### **Smart Polling System**
- **Adaptive Intervals**: Faster polling for recently changed devices
- **Activity-Based**: High activity = 3sec intervals, Low activity = 20sec intervals  
- **Resource Efficient**: Minimizes API calls while maintaining responsiveness
- **Batch Processing**: Optimized API usage with intelligent batching

#### **Error Handling**
- **Connection Recovery**: Automatic reconnection if network issues occur
- **API Rate Limiting**: Intelligent handling of SmartThings API limits
- **Graceful Degradation**: Integration continues working even if some devices are offline
- **Detailed Logging**: Comprehensive logging for troubleshooting

## How It Works - Important!

### **Pull-Based Architecture**
Unlike local integrations that use webhooks, this SmartThings integration uses a **pull-based approach** due to SmartThings Cloud API architecture and limitations:

```
UC Remote ←→ Integration ←→ SmartThings Cloud API ←→ SmartThings Hub ←→ Your Devices
```

**Why Pull Instead of Push?**
- SmartThings Cloud API doesn't support webhook subscriptions for third-party integrations unless official partner
- Ensures reliability across different network configurations
- No need for port forwarding or external network access
- Works with any internet connection (including cellular, VPN, etc.)

## Prerequisites

- Unfolded Circle Remote 2 or Remote 3
- SmartThings account with configured devices
- SmartThings Hub or compatible devices
- Internet connection for cloud API access
- **Personal Access Token** from SmartThings Developer Portal

## Installation

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

## Configuration

### Step 1: Generate SmartThings Personal Access Token

1. Visit [SmartThings Developer Portal](https://account.smartthings.com/tokens)
2. Click **"Generate new token"**
3. Enter token name: `UC Remote Integration`
4. **Select Required Permissions:**
   - ✅ **Devices**: List all devices, See all devices, Control all devices
   - ✅ **Locations**: List all locations, See all locations  
   - ✅ **Installed Applications**: List all installed applications, See all installed applications
   - ✅ **Scenes**: List all scenes, See all scenes, Control all scenes
   - ✅ **Rules**: See all rules, Control all rules (optional)
   - ✅ **Device Profiles**: See all device profiles (optional)
5. Click **"Generate token"**
6. **Copy the token immediately** (you cannot view it again)

### Step 2: Setup Integration

1. After installation, go to **Settings** → **Integrations**
2. The SmartThings integration should appear in **Available Integrations**
3. Click **"Configure"** and follow the setup wizard:

   **Token Setup:**
   - Paste your Personal Access Token
   - Integration will test connection to SmartThings

   **Location Selection:**
   - Choose your SmartThings location (home, office, etc.)
   - Integration will discover all devices in that location

   **Polling Configuration:**
   - **Base Interval**: How often to check device status (3-60 seconds)
   - **Auto-optimized** based on your device count

4. Click **"Complete Setup"**
5. Integration will create entities for all selected device types

### Step 3: Add Entities to Activities

1. Go to **Activities** in your remote interface
2. Edit or create an activity
3. Add SmartThings entities from the **Available Entities** list
4. Configure button mappings as desired
5. Save your activity


### Performance Features - Explanation due to pull based architecture

#### **Instant Response (Optimistic Updates)**
When you press a button on your remote:
1. **Immediate**: Remote UI updates instantly (0.1 seconds)
2. **Background**: Command sent to SmartThings (0.5-2 seconds)
3. **Verification**: Real device status confirmed (2-5 seconds)
4. **Correction**: UI corrects if command failed

#### **Smart Status Updates**
- **Recent Activity**: Devices used in last minute update every 3 seconds
- **Medium Activity**: Devices used in last 5 minutes update every 8 seconds  
- **Low Activity**: Inactive devices update every 20 seconds
- **On Demand**: Manual refresh available by pressing


## Performance & Optimization

### **API Usage Optimization**
- Smart Rate Limiting in Client:

- Tracks request times and prevents exceeding 8 requests per 10 seconds
Automatically waits when approaching limits
No retries to avoid stacking requests


- Single Verification Strategy:
- Only 1 verification attempt after 2 seconds (vs 2 attempts before)
Skips verification if recently rate limited
Lets background polling catch up instead
- Minimum 15-30 seconds between polls (vs 3-5 seconds before)
Pauses completely during commands
Extends pause after rate limits

- Gracefully handles 429 errors
Marks rate limit timestamps to inform future decisions
Falls back to polling for state updates

### **Network Requirements**
- **Bandwidth**: Minimal (~1KB per device per minute)
- **Latency**: Works well with 200ms+ internet latency
- **Reliability**: Handles network interruptions gracefully or Remote reboot
- **Firewall**: Only outbound HTTPS (port 443) required


## Troubleshooting

### Common Issues

#### **"No Devices Found"**
- Verify Personal Access Token has correct permissions
- Check that devices are online in SmartThings app
- Ensure location selection is correct
- Try refreshing the integration

#### **"Commands Not Working"**
- Check internet connectivity on remote
- Verify device is online in SmartThings app
- Check SmartThings service status
- Review integration logs for errors

#### **"Slow Response Times"**
- Check your internet connection speed and latency
- Reduce polling intervals if you have many devices
- Verify SmartThings cloud service is responsive
- Consider enabling optimistic updates

#### **"Integration Offline"**
- Check remote's internet connection
- Verify Personal Access Token hasn't expired
- Restart the integration from remote settings
- Check SmartThings Developer Portal for token status

#### **"Lock Control Issues"**
- Remember: ON = Locked, OFF = Unlocked
- Check lock battery level in SmartThings app
- Verify lock is within hub communication range
- Test lock control in SmartThings app first

### Debug Information

Enable detailed logging by setting environment variable:
```bash
export LOG_LEVEL=DEBUG
```

View integration logs:
- **Remote Interface**: Settings → Integrations → SmartThings → View Logs
- **Docker**: `docker logs smartthings-integration`

Check SmartThings API status:
- [SmartThings Developer Portal](https://developer.smartthings.com/)
- [SmartThings Status Page](https://status.smartthings.com/)

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

### **Network Requirements**
- **Internet Required**: Cannot work offline or with local-only networks  
- **Cloud Latency**: Response times depend on internet connection quality
- **API Dependencies**: Requires SmartThings cloud services to be operational

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
   Create `.env` file:
   ```bash
   SMARTTHINGS_TOKEN=your-personal-access-token-here
   LOG_LEVEL=DEBUG
   ```

3. **Run integration:**
   ```bash
   python -m uc_intg_smartthings.driver
   ```

4. **VS Code debugging:**
   - Open project in VS Code
   - Use F5 to start debugging session
   - Integration runs on `localhost:9090`

### Project Structure

```
uc-intg-smartthings/
├── uc_intg_smartthings/        # Main package
│   ├── __init__.py             # Package info  
│   ├── client.py               # SmartThings API client
│   ├── config.py               # Configuration management
│   ├── driver.py               # Main integration driver
│   ├── entities.py             # Entity factory & optimization
│   ├── entity_mapping.py       # Device type mapping
│   └── setup_flow.py           # Setup wizard
├── .github/workflows/          # GitHub Actions
├── driver.json                 # Integration metadata
├── requirements.txt            # Dependencies
├── pyproject.toml              # Python project config
└── README.md                   # This file
```

### Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/ -v

# Test specific device types
pytest tests/test_entities.py -v
```

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes and add tests
4. Run tests: `pytest tests/ -v`
5. Commit changes: `git commit -m 'Add amazing feature'`
6. Push to branch: `git push origin feature/amazing-feature`
7. Open a Pull Request

## License

This project is licensed under the Mozilla Public License 2.0 - see the [LICENSE](LICENSE) file for details.

## Credits

- **Developer**: Meir Miyara
- **SmartThings API**: Samsung SmartThings Platform
- **Unfolded Circle**: Remote 2/3 integration framework
- **Home Assistant**: Device capability mapping inspiration

## Support & Community

- **GitHub Issues**: [Report bugs and request features](https://github.com/mase1981/uc-intg-smartthings/issues)
- **UC Community Forum**: [General discussion and support](https://unfolded.community/)
- **Developer**: [Meir Miyara](mailto:meir.miyara@gmail.com)

---

**Made with ❤️ for the Unfolded Circle Community** 

**Thank You**: Meir Miyara  
