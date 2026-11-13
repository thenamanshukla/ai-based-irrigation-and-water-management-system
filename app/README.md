# Phone app (Android)

A small Capacitor app that reads the hub on the Raspberry Pi over the farm Wi Fi.
It shows only what the hub sends: today's plan, tank and pond water, soil, pipes, alerts and 48 hour trends.
English and Hindi. Manual watering and pond level need the hub PIN.

## 1. On the Pi

In `settings.json` set a PIN and a farm name:

```json
"service": { "planting_date": "2026-11-01", "app_pin": "4821", "farm_name": "Plot 3" }
```

Start the API next to the hub service:

```bash
sudo cp deploy/irrigation-api.service /etc/systemd/system/
sudo systemctl enable --now irrigation-api
curl http://localhost:8080/api/health
```

## 2. Build the APK on the Mac

Needs Node 22 or newer and Android Studio (with an Android SDK).

```bash
cd app
npm install
npm run android:add      # creates android/ and allows http to the hub
npm run sync
npm run open             # opens Android Studio
```

In Android Studio: Build > Build App Bundle(s) / APK(s) > Build APK(s).
The file appears in `android/app/build/outputs/apk/debug/app-debug.apk`. Copy it to the phone and install.

After any change in `www/`, run `npm run sync` again.

## 3. First run on the phone

1. Join the farm Wi Fi.
2. Settings > Hub address: the Pi address, for example `192.168.4.1:8080`. Tap Test connection, then Save.
3. Enter the PIN once under Settings > PIN.

## Notes

* Notifications show while the app is open. Background alerts when the app is closed are planned for a later version.
* Try it in a browser without building: `python3 -m http.server 8000` inside `www/`, then open `http://localhost:8000` and set the hub address.
