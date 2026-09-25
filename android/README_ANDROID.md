# WEEE Platform Android — 2.5.37

Thin native WebView client for the WEEE backend. The operational UI is served from `/mobile`, so Windows and Android share the same database/API and business rules.

## Build APK
Open the `android` folder in Android Studio, allow Gradle sync, then **Build > Build APK(s)**.
The app asks for the LAN address of the WEEE server, e.g. `http://192.168.1.20:8000`.

## Photos (2.5.37)
The "📷 ΦΩΤΟ" button in the sorting screen opens a choice **Κάμερα / Συλλογή**.
- Camera: the system camera app writes into the app cache through `PhotoProvider` (no CAMERA permission required, no AndroidX).
- Gallery: multi-select is supported.
- Each photo is uploaded to `POST /sorting/{load_id}/photos`, so it is linked to that load (visible on Windows in the receipt's photos and in the mobile thumbnails). Large photos are downscaled to max 1600px JPEG in the page before upload.

Note: this source package contains no precompiled APK (no Android SDK in the packaging environment).
