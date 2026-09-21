package gr.weee.platform;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private WebView web;
    private SharedPreferences prefs;
    private String serverUrl;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("weee", MODE_PRIVATE);
        serverUrl = prefs.getString("server", "http://192.168.1.100:8000");
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(243,245,246));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(12,10,12,10);
        TextView status = new TextView(this);
        status.setText("WEEE Platform 2.5.1");
        status.setTextSize(16);
        status.setTextColor(Color.WHITE);
        status.setPadding(8,12,8,12);
        bar.setBackgroundColor(Color.rgb(24,36,47));
        Button cfg = new Button(this);
        cfg.setText("SERVER");
        cfg.setOnClickListener(v -> editServer());
        bar.addView(status, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        bar.addView(cfg, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(bar);

        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        ws.setAllowFileAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);
        loadApp();
    }

    private void loadApp() {
        String s = serverUrl.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length()-1);
        web.clearCache(true);
        web.loadUrl(s + "/mobile?build=2.5.30");
    }

    private void editServer() {
        EditText input = new EditText(this);
        input.setText(serverUrl);
        input.setSingleLine(true);
        new AlertDialog.Builder(this)
            .setTitle("Διεύθυνση WEEE Server")
            .setMessage("Παράδειγμα: http://192.168.1.20:8000")
            .setView(input)
            .setNegativeButton("Ακύρωση", null)
            .setPositiveButton("Αποθήκευση", (d,w) -> {
                serverUrl = input.getText().toString().trim();
                prefs.edit().putString("server", serverUrl).apply();
                loadApp();
            }).show();
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
