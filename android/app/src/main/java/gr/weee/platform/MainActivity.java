package gr.weee.platform;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.provider.MediaStore;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

public class MainActivity extends Activity {
    private static final String VERSION = "2.5.41";
    private static final int REQ_FILES = 4711;

    private WebView web;
    private SharedPreferences prefs;
    private String serverUrl;
    private ValueCallback<Uri[]> filePathCallback;
    private File cameraFile;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("weee", MODE_PRIVATE);
        serverUrl = prefs.getString("server", "http://192.168.1.27:8000");
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(243,245,246));

        // Η επάνω μπάρα (τίτλος/έκδοση, admin, ΔΕΛΤΙΟ ΗΜΕΡΑΣ, ONLINE) σχεδιάζεται πλέον μέσα στη σελίδα (/mobile)· το κουμπί ONLINE
        // καλεί το editServer() (πρώην κουμπί SERVER) μέσω του WeeeNative.
        getWindow().setStatusBarColor(Color.rgb(24,36,47));

        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        ws.setAllowFileAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Object() {
            @android.webkit.JavascriptInterface public void editServer() { runOnUiThread(() -> MainActivity.this.editServer()); }
            @android.webkit.JavascriptInterface public String version() { return VERSION; }
            // Από την οθόνη σφάλματος: «Αποθήκευση και δοκιμή» (νέα διεύθυνση) και «Ξανά» (ίδια διεύθυνση).
            @android.webkit.JavascriptInterface public void saveServer(String url) { runOnUiThread(() -> MainActivity.this.saveServer(url)); }
            @android.webkit.JavascriptInterface public void retry() { runOnUiThread(() -> MainActivity.this.loadApp()); }
        }, "WeeeNative");
        web.setWebViewClient(new WebViewClient() {
            // Αν η κύρια σελίδα δεν φορτώνει (timeout, αποτυχία σύνδεσης) ή απαντά 5xx, δείχνουμε δική μας οθόνη με πεδίο διεύθυνσης.
            @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) showServerError(String.valueOf(err.getDescription()));
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest req, WebResourceResponse resp) {
                if (req != null && req.isForMainFrame() && resp != null && resp.getStatusCode() >= 500) showServerError("HTTP " + resp.getStatusCode());
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            // <input type="file"> in /mobile: offer camera or gallery, results go back to the page which uploads them to the load.
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                boolean multiple = params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE;
                new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Φωτογραφία")
                    .setItems(new String[]{"Κάμερα", "Συλλογή"}, (d, which) -> { if (which == 0) openCamera(); else openGallery(multiple); })
                    .setOnCancelListener(d -> finishChooser(null))
                    .show();
                return true;
            }
        });
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);
        loadApp();
    }

    private void openCamera() {
        try {
            cameraFile = new File(PhotoProvider.dir(this), "cam_" + System.currentTimeMillis() + ".jpg");
            Uri out = PhotoProvider.uriFor(cameraFile);
            Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            i.putExtra(MediaStore.EXTRA_OUTPUT, out);
            i.setClipData(ClipData.newRawUri("photo", out));
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            // Always show the app picker instead of silently reusing whatever camera app is set as
            // the device default -- lets a camera app installed for its own features (e.g.
            // Timestamp Camera, which stamps date/time on the photo) be picked deliberately.
            startActivityForResult(Intent.createChooser(i, "Επιλογή εφαρμογής κάμερας"), REQ_FILES);
        } catch (ActivityNotFoundException | SecurityException e) {
            cameraFile = null;
            Toast.makeText(this, "Δεν ήταν δυνατό το άνοιγμα της κάμερας", Toast.LENGTH_LONG).show();
            finishChooser(null);
        }
    }

    private void openGallery(boolean multiple) {
        cameraFile = null;
        try {
            Intent i = new Intent(Intent.ACTION_GET_CONTENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("image/*");
            if (multiple) i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            startActivityForResult(Intent.createChooser(i, "Επιλογή φωτογραφιών"), REQ_FILES);
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "Δεν βρέθηκε εφαρμογή συλλογής", Toast.LENGTH_LONG).show();
            finishChooser(null);
        }
    }

    private void finishChooser(Uri[] result) {
        if (filePathCallback != null) { filePathCallback.onReceiveValue(result); filePathCallback = null; }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_FILES) return;
        Uri[] result = null;
        if (resultCode == RESULT_OK) {
            if (cameraFile != null) {
                if (cameraFile.exists() && cameraFile.length() > 0) {
                    result = new Uri[]{PhotoProvider.uriFor(cameraFile)};
                } else if (data != null) {
                    // Some camera-replacement apps ignore EXTRA_OUTPUT entirely and return the
                    // photo their own way instead -- fall back to those so the picture still
                    // reaches the app rather than silently staying only in that app's own gallery.
                    Uri returned = data.getData();
                    if (returned != null) {
                        result = new Uri[]{returned};
                    } else {
                        Object thumb = data.getExtras() != null ? data.getExtras().get("data") : null;
                        if (thumb instanceof Bitmap) {
                            try (FileOutputStream out2 = new FileOutputStream(cameraFile)) {
                                ((Bitmap) thumb).compress(Bitmap.CompressFormat.JPEG, 90, out2);
                                result = new Uri[]{PhotoProvider.uriFor(cameraFile)};
                            } catch (IOException ignored) { }
                        }
                    }
                }
            } else if (data != null) {
                if (data.getClipData() != null) {
                    ClipData c = data.getClipData();
                    result = new Uri[c.getItemCount()];
                    for (int k = 0; k < result.length; k++) result[k] = c.getItemAt(k).getUri();
                } else if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                }
            }
        }
        cameraFile = null;
        finishChooser(result);
    }

    private void loadApp() {
        String s = serverUrl.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length()-1);
        web.clearCache(true);
        web.loadUrl(s + "/mobile?build=" + VERSION);
    }

    private static String esc(String t) {
        return t == null ? "" : t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private void saveServer(String url) {
        String s = url == null ? "" : url.trim();
        if (s.isEmpty()) return;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        serverUrl = s;
        prefs.edit().putString("server", serverUrl).apply();
        loadApp();
    }

    private void showServerError(String reason) {
        String html = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "<style>body{font:16px sans-serif;background:#f3f5f6;color:#18242f;margin:0;padding:24px}h2{margin:0 0 8px}"
            + "p{color:#556;margin:6px 0 16px}input{width:100%;box-sizing:border-box;font-size:18px;padding:12px;border:1px solid #889;border-radius:8px}"
            + "button{font-size:16px;padding:12px 18px;margin:12px 10px 0 0;border:0;border-radius:8px;background:#18242f;color:#fff}"
            + "button.b2{background:#fff;color:#18242f;border:1px solid #18242f}</style></head><body>"
            + "<h2>Δεν είναι δυνατή η σύνδεση με τον server</h2>"
            + "<p>Διεύθυνση τώρα: <b>" + esc(serverUrl) + "</b><br>Αιτία: " + esc(reason) + "</p>"
            + "<label>Διεύθυνση server</label><input id='u' value=\"" + esc(serverUrl) + "\" autocapitalize='off' autocorrect='off' spellcheck='false'>"
            + "<button onclick=\"WeeeNative.saveServer(document.getElementById('u').value)\">Αποθήκευση και δοκιμή</button>"
            + "<button class='b2' onclick=\"WeeeNative.retry()\">Ξανά</button>"
            + "</body></html>";
        web.loadDataWithBaseURL("about:blank", html, "text/html", "utf-8", null);
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
        if (web == null) { super.onBackPressed(); return; }
        // The page closes its top-most layer (photo / panel / load) and answers "true"; on the loads list it answers "false" and the app exits.
        web.evaluateJavascript("(function(){try{return window.appBack?window.appBack():false}catch(e){return false}})()", value -> {
            if (!"true".equals(value)) super.onBackPressed();
        });
    }
}
