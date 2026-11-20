package com.organizer.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.util.Base64;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Organizer — Android kabuğu. Web paketini (assets/web ya da kurulmuş güncelleme) kendi
 * https://app.organizer.local/ adresinden sunar; JavaScript'e "Native" köprüsünü verir.
 * Kabuk sürümü (KABUK) Java kodu değiştikçe artar; manifest "kabuk" alanı bundan büyükse telefon APK ister.
 * KABUK 2 (v.1.0.5): yeniden başlatma kurulan sürümü gerçekten açar (güncelleme döngüsü düzeltmesi).
 */
public class MainActivity extends Activity {
    static final String HOST = "app.organizer.local";
    static final String BASE = "https://" + HOST + "/index.html";
    static final int KABUK = 2;

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;
    private static final int REQ_FILE = 11;
    private Ota ota;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ota = new Ota(this);
        ota.bootCheck();

        Window w = getWindow();
        w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (Build.VERSION.SDK_INT >= 21) {
            w.setStatusBarColor(Color.parseColor("#2e7d6b"));
            w.setNavigationBarColor(Color.WHITE);
        }
        if (Build.VERSION.SDK_INT >= 26) {
            w.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setTextZoom(100);
        web.setBackgroundColor(Color.WHITE);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.addJavascriptInterface(new Native(), "Native");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (u != null && HOST.equals(u.getHost())) return serve(u.getPath());
                return null;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (u == null || HOST.equals(u.getHost())) return false;
                openExternal(u.toString());
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = cb;
                try {
                    if (params.isCaptureEnabled()) {
                        File dir = new File(getCacheDir(), "camera");
                        dir.mkdirs();
                        File f = new File(dir, "foto-" + System.currentTimeMillis() + ".jpg");
                        f.createNewFile();
                        cameraUri = FilesProvider.uriFor(f);
                        Intent cam = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
                        cam.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, cameraUri);
                        cam.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        startActivityForResult(cam, REQ_FILE);
                    } else {
                        cameraUri = null;
                        Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                        pick.addCategory(Intent.CATEGORY_OPENABLE);
                        pick.setType("image/*");
                        pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                        startActivityForResult(Intent.createChooser(pick, null), REQ_FILE);
                    }
                } catch (Exception e) {
                    fileCallback.onReceiveValue(null);
                    fileCallback = null;
                    Toast.makeText(MainActivity.this, "Kamera / galeri açılamadı", Toast.LENGTH_SHORT).show();
                }
                return true;
            }
        });

        setContentView(web);
        web.loadUrl(BASE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != REQ_FILE) { super.onActivityResult(requestCode, resultCode, data); return; }
        if (fileCallback == null) return;
        Uri[] out = null;
        if (resultCode == RESULT_OK) {
            List<Uri> uris = new ArrayList<>();
            if (data != null && data.getClipData() != null) {
                ClipData cd = data.getClipData();
                for (int i = 0; i < cd.getItemCount(); i++) uris.add(cd.getItemAt(i).getUri());
            } else if (data != null && data.getData() != null) {
                uris.add(data.getData());
            } else if (cameraUri != null) {
                uris.add(cameraUri);
            }
            if (!uris.isEmpty()) out = uris.toArray(new Uri[0]);
        }
        fileCallback.onReceiveValue(out);
        fileCallback = null;
        cameraUri = null;
    }

    // ------------------------------------------------------------ web paketi
    private static final Map<String, String> MIME = new HashMap<>();
    static {
        MIME.put("html", "text/html"); MIME.put("js", "application/javascript"); MIME.put("css", "text/css");
        MIME.put("json", "application/json"); MIME.put("png", "image/png"); MIME.put("jpg", "image/jpeg");
        MIME.put("jpeg", "image/jpeg"); MIME.put("svg", "image/svg+xml"); MIME.put("webp", "image/webp");
        MIME.put("ico", "image/x-icon"); MIME.put("woff", "font/woff"); MIME.put("woff2", "font/woff2"); MIME.put("txt", "text/plain");
    }

    private WebResourceResponse serve(String path) {
        if (path == null || path.equals("/") || path.isEmpty()) path = "/index.html";
        String rel = path.startsWith("/") ? path.substring(1) : path;
        if (rel.contains("..")) return notFound();
        String ext = rel.contains(".") ? rel.substring(rel.lastIndexOf('.') + 1).toLowerCase() : "";
        String mime = MIME.containsKey(ext) ? MIME.get(ext) : "application/octet-stream";
        InputStream in = ota.open(rel);
        if (in == null) return notFound();
        Map<String, String> h = new HashMap<>();
        h.put("Cache-Control", "no-store");
        h.put("Access-Control-Allow-Origin", "*");
        return new WebResourceResponse(mime, mime.startsWith("text/") || mime.contains("javascript") || mime.contains("json") ? "utf-8" : null, 200, "OK", h, in);
    }

    private WebResourceResponse notFound() {
        return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", new HashMap<String, String>(),
                new ByteArrayInputStream("bulunamadı".getBytes(StandardCharsets.UTF_8)));
    }

    // ------------------------------------------------------------ geri tuşu
    @Override
    public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript("(function(){try{return window.onBack&&window.onBack()?'1':'0'}catch(e){return '0'}})()", new ValueCallback<String>() {
            @Override
            public void onReceiveValue(String v) {
                if (v == null || !v.contains("1")) finishAfterTransition();
            }
        });
    }

    private void openExternal(String url) {
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "Bu bağlantıyı açacak uygulama yok", Toast.LENGTH_SHORT).show();
        }
    }

    /** Yeniden başlat: kurulan sürümü seç (bootCheck) ve onu yükle. Eskiden yalnızca sayfa yenileniyordu → döngü. */
    void reload() {
        runOnUiThread(new Runnable() {
            public void run() {
                ota.bootCheck();
                web.clearCache(true);
                web.loadUrl(BASE);
            }
        });
    }

    // ------------------------------------------------------------ JavaScript köprüsü
    class Native {
        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Organizer", text == null ? "" : text));
        }

        @JavascriptInterface
        public void openUrl(final String url) {
            runOnUiThread(new Runnable() { public void run() { openExternal(url); } });
        }

        @JavascriptInterface
        public void shareFile(String name, String mime, String b64) {
            try {
                File dir = new File(getCacheDir(), "share");
                dir.mkdirs();
                String safe = (name == null ? "dosya" : name).replaceAll("[\\\\/:*?\"<>|]", "_");
                File f = new File(dir, safe);
                try (OutputStream o = new FileOutputStream(f)) { o.write(Base64.decode(b64, Base64.DEFAULT)); }
                final Intent i = new Intent(Intent.ACTION_SEND);
                i.setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
                i.putExtra(Intent.EXTRA_STREAM, FilesProvider.uriFor(f));
                i.putExtra(Intent.EXTRA_SUBJECT, safe);
                i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                runOnUiThread(new Runnable() { public void run() { startActivity(Intent.createChooser(i, null)); } });
            } catch (Exception e) {
                toast("Paylaşılamadı: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void printPage(final String title) {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        PrintManager pm = (PrintManager) getSystemService(Context.PRINT_SERVICE);
                        String job = (title == null || title.isEmpty()) ? "Organizer" : title;
                        PrintDocumentAdapter ad = web.createPrintDocumentAdapter(job);
                        pm.print(job, ad, new PrintAttributes.Builder().build());
                    } catch (Exception e) {
                        toast("Yazdırılamadı: " + e.getMessage());
                    }
                }
            });
        }

        @JavascriptInterface
        public int kabuk() { return KABUK; }

        @JavascriptInterface
        public String skipped() { return ota.skipped(); }

        @JavascriptInterface
        public void skip(String version) { ota.skip(version); }

        /** İmzalı web paketini kurar; sorun varsa açıklamasını, yoksa "" döndürür. */
        @JavascriptInterface
        public String installWeb(String version, String b64, String sig) { return ota.installWeb(version, b64, sig); }

        /** İmzalı APK'yı kurulum için Android'e verir; sorun varsa açıklamasını, yoksa "" döndürür. */
        @JavascriptInterface
        public String installApk(String b64, String sig) { return ota.installApk(b64, sig); }

        /** Yeni sürüm sorunsuz açıldı: geri dönüş noktası silinir, eski paketler temizlenir. */
        @JavascriptInterface
        public void bootOk() { ota.bootOk(); }

        @JavascriptInterface
        public void restart() { reload(); }

        /** Şu an çalışan web paketinin sürümü. */
        @JavascriptInterface
        public String version() { return ota.activeVersion(); }
    }

    void toast(final String s) {
        runOnUiThread(new Runnable() { public void run() { Toast.makeText(MainActivity.this, s, Toast.LENGTH_LONG).show(); } });
    }
}
