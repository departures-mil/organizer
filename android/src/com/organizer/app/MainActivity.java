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
import android.content.res.Configuration;
import android.speech.RecognizerIntent;
import android.speech.tts.TextToSpeech;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

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
 * KABUK 3 (v.1.0.8): sesli arama (listen), sesli cevap (speak), yerel ağ eşitlemesi (lanDiscover, lanPost),
 *                    koyu görünümde sistem çubukları (setDark, isNight).
 * KABUK 4 (2.2.0): ortak çekirdek — window.AndroidBridge (FcBridge): GitHub Releases latest.json + FCD1 yama
 *                    (kurulu APK + yama → yeni APK, ApkPatchInstaller), github.com/departures-mil/organizer/releases/…
 *                    istekleri yerelde çekilip CORS başlığıyla verilir. Eski imzalı web paketi (Ota) yalnız açılışta
 *                    APK'daki paketten eskiyse yok sayılır; yeni güncellemeler APK olarak gelir.
 */
public class MainActivity extends Activity {
    static final String HOST = "app.organizer.local";
    static final String BASE = "https://" + HOST + "/index.html";
    static final int KABUK = 4;

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;
    private static final int REQ_FILE = 11;
    private static final int REQ_VOICE = 12;
    private int voiceCb = 0;
    private TextToSpeech tts;
    private boolean ttsReady = false;
    private Ota ota;
    private FcBridge fc;

    /** JS çalıştır (her iş parçacığından). */
    void js(final String code) {
        runOnUiThread(new Runnable() { public void run() { if (web != null) web.evaluateJavascript(code, null); } });
    }

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
        fc = new FcBridge(this);
        web.addJavascriptInterface(fc, "AndroidBridge");   // ortak çekirdek (FC.host android)
        fc.cleanupIfUpdated();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (u != null && HOST.equals(u.getHost())) return serve(u.getPath());
                return githubProxy(req);
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
        if (requestCode == REQ_VOICE) {
            String text = "";
            if (resultCode == RESULT_OK && data != null) {
                ArrayList<String> r = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
                if (r != null && !r.isEmpty()) text = r.get(0);
            }
            callback(voiceCb, !text.isEmpty(), text.isEmpty() ? "cancel" : text);
            voiceCb = 0;
            return;
        }
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

        // ---------------------------------------------------- KABUK 3 (v.1.0.8)
        /** Sesli arama: Android'in ses tanıma ekranı; sonuç __nativeCb ile döner. */
        @JavascriptInterface
        public void listen(final int id, final String lang) {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
                        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, lang);
                        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                        voiceCb = id;
                        startActivityForResult(i, REQ_VOICE);
                    } catch (Exception e) {
                        callback(id, false, "Bu telefonda ses tanıma yok");
                    }
                }
            });
        }

        /** Sesli cevap ("Matkap: Balkon dolabı") */
        @JavascriptInterface
        public void speak(final String text, final String lang) {
            runOnUiThread(new Runnable() {
                public void run() {
                    final Runnable say = new Runnable() {
                        public void run() {
                            try {
                                tts.setLanguage(Locale.forLanguageTag(lang));
                                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "organizer");
                            } catch (Exception ignored) { }
                        }
                    };
                    if (tts != null && ttsReady) { say.run(); return; }
                    tts = new TextToSpeech(MainActivity.this, new TextToSpeech.OnInitListener() {
                        public void onInit(int status) {
                            ttsReady = status == TextToSpeech.SUCCESS;
                            if (ttsReady) say.run();
                        }
                    });
                }
            });
        }

        @JavascriptInterface
        public void lanDiscover(final int id) {
            new Thread(new Runnable() { public void run() { callback(id, true, discover()); } }).start();
        }

        /** body: base64 (UTF-8 JSON) */
        @JavascriptInterface
        public void lanPost(final int id, final String url, final String b64) {
            new Thread(new Runnable() {
                public void run() {
                    String body = new String(Base64.decode(b64, Base64.DEFAULT), StandardCharsets.UTF_8);
                    callback(id, true, post(url, body));
                }
            }).start();
        }

        @JavascriptInterface
        public void setDark(boolean dark) { applyBars(dark); }

        @JavascriptInterface
        public boolean isNight() {
            return (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        }
    }

    /** JavaScript'e eşzamansız sonuç: window.__nativeCb(id, ok, base64(metin)) */
    void callback(final int id, final boolean ok, final String text) {
        if (id == 0) return;
        final String b64 = Base64.encodeToString((text == null ? "" : text).getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
        runOnUiThread(new Runnable() {
            public void run() {
                web.evaluateJavascript("window.__nativeCb&&window.__nativeCb(" + id + "," + ok + ",'" + b64 + "')", null);
            }
        });
    }

    void applyBars(final boolean dark) {
        runOnUiThread(new Runnable() {
            public void run() {
                Window w = getWindow();
                if (Build.VERSION.SDK_INT >= 21) {
                    w.setStatusBarColor(Color.parseColor(dark ? "#070b14" : "#1d5f74"));
                    w.setNavigationBarColor(Color.parseColor(dark ? "#070b14" : "#eef2f7"));
                }
                if (Build.VERSION.SDK_INT >= 26) {
                    w.getDecorView().setSystemUiVisibility(dark ? 0 : View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
                }
                web.setBackgroundColor(Color.parseColor(dark ? "#070b14" : "#eef2f7"));
            }
        });
    }

    /** Aynı ağdaki Organizer bilgisayarlarını UDP yayınıyla bulur. */
    String discover() {
        JSONArray out = new JSONArray();
        Set<String> seen = new HashSet<>();
        Set<String> mine = new HashSet<>();
        DatagramSocket sock = null;
        try {
            List<InetAddress> targets = new ArrayList<>();
            targets.add(InetAddress.getByName("255.255.255.255"));
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    if (ia.getAddress() != null) mine.add(ia.getAddress().getHostAddress());
                    if (ia.getBroadcast() != null) targets.add(ia.getBroadcast());
                }
            }
            sock = new DatagramSocket();
            sock.setBroadcast(true);
            sock.setSoTimeout(300);
            byte[] probe = "ORGANIZER-LAN?".getBytes(StandardCharsets.UTF_8);
            long end = System.currentTimeMillis() + 1800;
            int sent = 0;
            byte[] buf = new byte[2048];
            while (System.currentTimeMillis() < end) {
                if (sent < 3) {
                    for (InetAddress a : targets) {
                        try { sock.send(new DatagramPacket(probe, probe.length, a, 47322)); } catch (Exception ignored) { }
                    }
                    sent++;
                }
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                try { sock.receive(p); } catch (SocketTimeoutException e) { continue; }
                String host = p.getAddress().getHostAddress();
                if (seen.contains(host) || mine.contains(host)) continue;
                try {
                    JSONObject info = new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8));
                    if (!"organizer-lan".equals(info.optString("app"))) continue;
                    JSONObject o = new JSONObject();
                    o.put("host", host);
                    o.put("port", info.optInt("port", 47321));
                    o.put("name", info.optString("name", host));
                    o.put("version", info.optString("version", ""));
                    out.put(o);
                    seen.add(host);
                } catch (Exception ignored) { }
            }
        } catch (Exception ignored) {
        } finally {
            if (sock != null) sock.close();
        }
        return out.toString();
    }

    /** Yerel ağdaki bilgisayara JSON gönderir; "durum\ngövde" döndürür (0 = ulaşılamadı). */
    String post(String url, String body) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(6000);
            c.setReadTimeout(90000);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] data = body.getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(data.length);
            try (OutputStream o = c.getOutputStream()) { o.write(data); }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            if (in != null) {
                byte[] b = new byte[16384];
                int n;
                while ((n = in.read(b)) > 0) bo.write(b, 0, n);
                in.close();
            }
            return code + "\n" + new String(bo.toByteArray(), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return "0\n" + e.getClass().getSimpleName() + ": " + e.getMessage();
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /** latest.json için: github.com/departures-mil/organizer/releases/… GET isteğini yerelde çeker, CORS başlığı ekler. */
    private WebResourceResponse githubProxy(WebResourceRequest req) {
        Uri u = req.getUrl();
        String p = u == null ? null : u.getPath();
        if (u == null || !"GET".equalsIgnoreCase(req.getMethod()) || !"https".equals(u.getScheme()) || !"github.com".equals(u.getHost())
                || p == null || !p.startsWith("/departures-mil/organizer/releases/")) return null;
        Map<String, String> h = new HashMap<>();
        h.put("Access-Control-Allow-Origin", "*");
        h.put("Cache-Control", "no-store");
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(u.toString()).openConnection();
            c.setInstanceFollowRedirects(true);
            c.setConnectTimeout(15000);
            c.setReadTimeout(30000);
            c.setUseCaches(false);
            c.setRequestProperty("User-Agent", "Organizer-Android");
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) in = new ByteArrayInputStream(new byte[0]);
            String msg = c.getResponseMessage();
            return new WebResourceResponse(p.endsWith(".json") ? "application/json" : "application/octet-stream", "utf-8",
                    code, msg == null || msg.isEmpty() ? (code < 400 ? "OK" : "Error") : msg, h, in);
        } catch (Exception e) {
            return new WebResourceResponse("text/plain", "utf-8", 502, "Bad Gateway", h, new ByteArrayInputStream(new byte[0]));
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (fc != null) fc.resumeInstall();
    }

    @Override
    protected void onDestroy() {
        if (tts != null) tts.shutdown();
        super.onDestroy();
    }

    void toast(final String s) {
        runOnUiThread(new Runnable() { public void run() { Toast.makeText(MainActivity.this, s, Toast.LENGTH_LONG).show(); } });
    }
}
