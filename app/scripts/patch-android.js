// The hub serves plain http on the farm Wi Fi, so Android must allow cleartext traffic.
const fs = require("fs");
const path = "android/app/src/main/AndroidManifest.xml";
if (!fs.existsSync(path)) { console.error("Run `npx cap add android` first."); process.exit(1); }
let xml = fs.readFileSync(path, "utf8");
if (!xml.includes("usesCleartextTraffic")) {
  xml = xml.replace("<application", '<application\n        android:usesCleartextTraffic="true"');
}
if (!xml.includes("POST_NOTIFICATIONS")) {
  xml = xml.replace("</manifest>", '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n</manifest>');
}
fs.writeFileSync(path, xml);
console.log("AndroidManifest patched: cleartext http allowed, notification permission added.");
