package com.organizer.app;

import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.util.Base64;
import android.webkit.JavascriptInterface;

import com.departuresmil.ortak.ApkPatchInstaller;
import com.departuresmil.ortak.FcDelta;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * window.AndroidBridge — ortak çekirdeğin Android sözleşmesi (web/js/host.js), kitaplik/aile-ajandasi ile aynı desen:
 *   appVersion, moveTaskToBack, openExternal,
 *   updateBegin / updateChunk / updateFinish (çekirdek sözleşmesi: JS'ten gelen yama ya da tam APK baytları),
 *   apkUpdate(planJson) (YEREL EK: indirme Java tarafında — WebView'de GitHub indirmesi CORS'a takılır — + ortak ApkPatchInstaller:
 *     kurulu APK (applicationInfo.sourceDir) + FCD1 yama → yeni APK; yama yoksa/başarısızsa kendiliğinden tam APK).
 * Olaylar JS'e window.__fcApk({type:'progress'|'patchFailed'|'installing'|'done'|'error', …}) ile gider.
 * Bütün sürümler aynı anahtarla imzalanır (CI: ANDROID_KEYSTORE_* secret'ları); aksi halde Android güncellemeyi reddeder.
 */
final class FcBridge {
    static final String AUTHORITY_SUFFIX = ".guncelleme";   // UpdateFileProvider (AndroidManifest.xml)
    private final MainActivity a;
    private File incoming = null;
    private FileOutputStream incomingOut = null;
    private String incomingKind = "";
    private JSONObject incomingMeta = null;
    private static volatile boolean busy = false;

    FcBridge(MainActivity a) { this.a = a; }

    private ApkPatchInstaller installer() {
        return new ApkPatchInstaller(a, a.getPackageName() + AUTHORITY_SUFFIX);
    }

    private SharedPreferences prefs() { return a.getSharedPreferences("fc_guncelleme", MainActivity.MODE_PRIVATE); }

    @JavascriptInterface
    public String appVersion() {
        try { return a.getPackageManager().getPackageInfo(a.getPackageName(), 0).versionName; } catch (Exception e) { return ""; }
    }

    @JavascriptInterface
    public void moveTaskToBack() {
        a.runOnUiThread(new Runnable() { public void run() { a.moveTaskToBack(true); } });
    }

    @JavascriptInterface
    public void openExternal(final String url) {
        if (url == null || !(url.startsWith("https://") || url.startsWith("mailto:"))) return;
        a.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    a.startActivity(i);
                } catch (Exception ignored) { }
            }
        });
    }

    // ---------- çekirdek sözleşmesi: baytlar JS'ten (base64 parçalar) ----------
    @JavascriptInterface
    public synchronized boolean updateBegin(String kind, String metaJson) {
        try {
            closeIncoming();
            incomingKind = "patch".equals(kind) ? "patch" : "full";
            incomingMeta = new JSONObject(metaJson == null ? "{}" : metaJson);
            incoming = new File(installer().updatesDir(), "patch".equals(incomingKind) ? "update.patch" : "incoming.apk");
            incomingOut = new FileOutputStream(incoming);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @JavascriptInterface
    public synchronized boolean updateChunk(String b64) {
        try {
            incomingOut.write(Base64.decode(b64, Base64.DEFAULT));
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @JavascriptInterface
    public synchronized String updateFinish() {
        try {
            incomingOut.close();
            incomingOut = null;
            String want = incomingMeta.optString("targetSha256", "");
            File out = new File(installer().updatesDir(), "update.apk");
            if ("patch".equals(incomingKind)) {
                File installed = new File(a.getApplicationInfo().sourceDir);
                FcDelta.Header h = FcDelta.apply(installed, incoming, out, null);
                if (!want.isEmpty() && !want.equalsIgnoreCase(h.dstSha256Hex())) throw new IOException("BAD_HASH");
            } else {
                if (!want.isEmpty() && !want.equalsIgnoreCase(FcDelta.hex(FcDelta.sha256(incoming)))) throw new IOException("BAD_HASH");
                if (out.exists()) out.delete();
                if (!incoming.renameTo(out)) throw new IOException("MOVE_FAILED");
            }
            installOnUi(out);
            return "{\"ok\":true}";
        } catch (Exception e) {
            return "{\"ok\":false,\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}";
        } finally {
            if (incoming != null && incoming.getName().equals("update.patch")) incoming.delete();
            closeIncoming();
        }
    }

    private void closeIncoming() {
        if (incomingOut != null) try { incomingOut.close(); } catch (IOException ignored) { }
        incomingOut = null;
    }

    // ---------- Ağ köprüsü (ortak-cekirdek 1c11eb0): WebView GitHub'a fetch yapamaz (CORS, "Failed to fetch") ----------
    // httpGet(id, url) → yalnız https, en çok 2 MB metin (latest.json); sonuç window.__fcHttp(id, {status, body} | {error}).
    @JavascriptInterface
    public void httpGet(final String id, final String url) {
        new Thread(new Runnable() {
            public void run() {
                String res;
                java.net.HttpURLConnection c = null;
                try {
                    if (url == null || !url.startsWith("https://")) throw new IOException("ONLY_HTTPS");
                    String u = url;
                    int status = 0;
                    for (int hop = 0; hop < 6; hop++) {   // github.com yönlendirmeleri elle izlenir (yalnız https)
                        c = (java.net.HttpURLConnection) new java.net.URL(u).openConnection();
                        c.setInstanceFollowRedirects(false);
                        c.setConnectTimeout(15000);
                        c.setReadTimeout(30000);
                        c.setRequestProperty("User-Agent", "Organizer/" + appVersion());
                        c.setRequestProperty("Accept", "application/json, */*");
                        status = c.getResponseCode();
                        if (status >= 300 && status < 400) {
                            String loc = c.getHeaderField("Location");
                            c.disconnect();
                            c = null;
                            if (loc == null || !loc.startsWith("https://")) throw new IOException("BAD_REDIRECT");
                            u = loc;
                            continue;
                        }
                        break;
                    }
                    if (c == null) throw new IOException("TOO_MANY_REDIRECTS");
                    String body = "";
                    if (status == 200) {
                        java.io.InputStream in = c.getInputStream();
                        java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                        byte[] buf = new byte[16384];
                        int n;
                        while ((n = in.read(buf)) > 0) {
                            bo.write(buf, 0, n);
                            if (bo.size() > 2 * 1024 * 1024) throw new IOException("TOO_LARGE");
                        }
                        in.close();
                        body = new String(bo.toByteArray(), "UTF-8");
                    }
                    res = "{\"status\":" + status + ",\"body\":" + JSONObject.quote(body) + "}";
                } catch (Exception e) {
                    res = "{\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}";
                } finally {
                    if (c != null) c.disconnect();
                }
                a.js("window.__fcHttp && window.__fcHttp(" + JSONObject.quote(String.valueOf(id)) + "," + res + ")");
            }
        }).start();
    }

    // ---------- YEREL EK: Java tarafında indirme + ApkPatchInstaller ----------
    @JavascriptInterface
    public void apkUpdate(final String planJson) {
        if (busy) { emit("{\"type\":\"error\",\"error\":\"BUSY\"}"); return; }
        busy = true;
        new Thread(new Runnable() {
            public void run() {
                try {
                    JSONObject p = new JSONObject(planJson);
                    JSONObject full = p.getJSONObject("full");
                    JSONObject patch = p.optJSONObject("patch");
                    ApkPatchInstaller up = installer();
                    File apk = up.obtainApk(full.getString("url"), full.getString("sha256"), full.optLong("size", 0),
                            patch != null ? patch.optString("url", null) : null,
                            patch != null ? patch.optString("sha256", null) : null,
                            patch != null ? patch.optLong("size", 0) : 0,
                            new ApkPatchInstaller.Listener() {
                                @Override
                                public void onProgress(boolean patchMode, long done, long total, double bps) {
                                    emit("{\"type\":\"progress\",\"patch\":" + patchMode + ",\"done\":" + done + ",\"total\":" + total + "}");
                                }

                                @Override
                                public void onPatchFailed(Exception e) {
                                    emit("{\"type\":\"patchFailed\",\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}");
                                }
                            });
                    emit("{\"type\":\"installing\"}");
                    installOnUi(apk);
                    emit("{\"type\":\"done\",\"result\":\"done\"}");
                } catch (Exception e) {
                    emit("{\"type\":\"error\",\"error\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}");
                } finally {
                    busy = false;
                }
            }
        }).start();
    }

    /** Paket yükleyiciyi açar; "bilinmeyen kaynaklar" izni yoksa ayar ekranı açılır ve geri dönülünce (onResume) yeniden denenir. */
    private void installOnUi(final File apk) {
        a.runOnUiThread(new Runnable() {
            public void run() {
                boolean ok = installer().install(apk);
                prefs().edit().putBoolean("installPending", !ok).apply();
            }
        });
    }

    /** MainActivity.onResume: izin verildiyse bekleyen kurulumu sürdür. */
    void resumeInstall() {
        if (!prefs().getBoolean("installPending", false)) return;
        File apk = new File(installer().updatesDir(), "update.apk");
        if (!apk.exists()) { prefs().edit().putBoolean("installPending", false).apply(); return; }
        if (android.os.Build.VERSION.SDK_INT >= 26 && !a.getPackageManager().canRequestPackageInstalls()) return;
        installOnUi(apk);
    }

    /** Açılışta: yeni sürüm açıldıysa önceki güncelleme dosyalarını sil. */
    void cleanupIfUpdated() {
        String v = appVersion();
        if (!v.equals(prefs().getString("lastVersion", ""))) {
            if (!busy) installer().cleanup();
            prefs().edit().putString("lastVersion", v).putBoolean("installPending", false).apply();
        }
    }

    private void emit(String json) { a.js("window.__fcApk && window.__fcApk(" + json + ")"); }
}
