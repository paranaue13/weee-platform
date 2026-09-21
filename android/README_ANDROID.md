# WEEE Platform Android — Build 1.2 test client

This Android project is a thin native WebView client for the WEEE backend. The operational UI itself is served from `/mobile`, so Windows and Android use the same database/API and business rules.

## Build APK
Open the `android` folder in Android Studio, allow Gradle sync, then use **Build > Build APK(s)**.

The app asks for the LAN address of the WEEE server. Example: `http://192.168.1.20:8000`.

This source package does not contain a precompiled APK because the current packaging environment has Java but no Android SDK/Gradle build tools. Do not treat any renamed ZIP as an APK.
