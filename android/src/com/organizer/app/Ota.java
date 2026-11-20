package com.organizer.app;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Base64;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Uygulama içinden güncelleme (telefon). Masaüstündeki organizer/updater.py ile aynı düzen.
 * Kurulan web paketleri filesDir/guncelleme/organizer-telefon-<sürüm>/ altında durur; etkin.txt çalışan sürümü,
 * onceki.txt geri dönülecek sürümü, bozuk.txt açılamayan sürümleri tutar. Yeni sürüm açılıp bootOk() demezse
 * bir sonraki açılışta kendiliğinden önceki sürüme dönülür. İmzası doğrulanmayan paket kurulmaz.
 *
 * Kabuk 2 (v.1.0.5) düzeltmeleri — "Güncelle → yeniden başlıyor → yine aynı güncelleme" döngüsü:
 *  - Yeniden başlatma (restart) artık bootCheck()'i yeniden çalıştırır; eskiden yalnızca sayfa yenileniyordu,
 *    bellekteki "active" eski sürümde kalıyor, eski kod açılıp bootOk() ile yeni kurulan klasörü siliyordu.
 *  - bootOk() etkin.txt'de yazan (yeni kurulmuş) sürümün klasörünü asla silmez.
 *  - APK'nın içindeki paket (assets/web/surum.txt) kurulu güncellemeden yeniyse o kullanılır.
 */
class Ota {
    static final String KIND = "organizer-telefon";
    static final String PUB_SPKI =
            "MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEApDJyJfzD3NUo6KT1DqbxUtS4LbHBO8y3" +
            "S+bm7MlSt/z95iRXCba2YjnVOWEr3YfZ2R2iCk9fquQXYZF4z0Un5RNZtzgcAkyg4yaEqFRJPaA+" +
            "OlJLOpZm+pMxdcXJhvGXVXmQzjh69vnh0r0y18XwH+liiihJOmFcN0UVyApyLOeVs1jR3tAXLuXo" +
            "iCgXfMbYOD84e7CupEgNv/TuKMOMAUTLpp5hbhp32gkQyB9yQK9ur9eGCTAfPfUCUa9GRIOKKWDr" +
            "tdTYsnkGUwcV+xUYmGSby1DasTy/sgwX5WFd/5NUa/+dDB6myFiPXjnxkShNJBBXmWGqmU19gyo3" +
            "CzXm91b6i92BIsMgWUiQoewLnv6bTMgr2r2IOBBjhscE1UuuGYzjyY8fjq2MVesonckyvSA2BSeD" +
            "tZiBrrEUNqiogZ1GJhPYoTMQVZWF35HZJ1ktxx+mMgVxDV8x1CfJKrMCH+FAAetjB/rYz6FmgM3Q" +
            "vN8jS6UcIAyyNaiuni7EKaH7AgMBAAE=";

    private final MainActivity act;
    private final File root;
    private final SharedPreferences prefs;
    private String active = "";   // "" = programla gelen paket (assets/web)

    Ota(MainActivity a) {
        act = a;
        root = new File(a.getFilesDir(), "guncelleme");
        prefs = a.getSharedPreferences("ota", Context.MODE_PRIVATE);
    }

    // ------------------------------------------------------------ dosya yardımcıları
    private String read(String name) {
        File f = new File(root, name);
        if (!f.exists()) return "";
        try (InputStream in = new FileInputStream(f)) {
            byte[] b = new byte[(int) f.length()];
            int n = in.read(b);
            return new String(b, 0, Math.max(n, 0), StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            return "";
        }
    }

    private void write(String name, String text) {
        root.mkdirs();
        try (OutputStream o = new FileOutputStream(new File(root, name))) {
            o.write(text.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
        }
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        f.delete();
    }

    private File folder(String ver) { return new File(root, KIND + "-" + ver); }

    private boolean valid(String ver) {
        return ver != null && ver.matches("\\d+(\\.\\d+)*") && new File(folder(ver), "index.html").isFile();
    }

    /** a, b'den yeni mi (sayısal karşılaştırma: 2.1.0.10 > 2.1.0.9). */
    static boolean newer(String a, String b) {
        String[] x = (a == null ? "0" : a).split("\\."), y = (b == null ? "0" : b).split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            long p = i < x.length ? num(x[i]) : 0, q = i < y.length ? num(y[i]) : 0;
            if (p != q) return p > q;
        }
        return false;
    }

    private static long num(String s) {
        try { return Long.parseLong(s.trim()); } catch (Exception e) { return 0; }
    }

    /** APK'nın içinde gelen web paketinin sürümü (assets/web/surum.txt). */
    String bundledVersion() {
        try (InputStream in = act.getAssets().open("web/surum.txt")) {
            byte[] b = new byte[64];
            int n = in.read(b);
            return new String(b, 0, Math.max(n, 0), StandardCharsets.UTF_8).trim();
        } catch (IOException e) {
            return "0";
        }
    }

    // ------------------------------------------------------------ açılış
    /** Açılışta (ve her yeniden başlatmada): önceki açılış yarım kaldıysa bozuk sayıp geri döner; çalışacak sürümü seçer. */
    synchronized void bootCheck() {
        String ver = read("etkin.txt");
        if (ver.isEmpty()) { active = ""; return; }
        // APK ile gelen paket kurulu güncellemeden yeni (ya da aynı) ise APK'nınkini kullan
        if (!newer(ver, bundledVersion())) {
            write("etkin.txt", "");
            write("onceki.txt", "");
            prefs.edit().remove("pending-" + ver).apply();
            active = "";
            return;
        }
        boolean pending = prefs.getBoolean("pending-" + ver, false);
        if (pending || !valid(ver)) {
            String broken = read("bozuk.txt");
            write("bozuk.txt", (broken.isEmpty() ? "" : broken + "\n") + ver);
            prefs.edit().remove("pending-" + ver).apply();
            String prev = read("onceki.txt");
            if (!prev.isEmpty() && valid(prev) && !prev.equals(ver) && newer(prev, bundledVersion())) {
                write("etkin.txt", prev);
                active = prev;
            } else {
                write("etkin.txt", "");
                active = "";
            }
            write("onceki.txt", "");
            return;
        }
        active = ver;
        prefs.edit().putBoolean("pending-" + ver, true).apply();   // bootOk() gelmezse bir sonraki açılış geri döner
    }

    String activeVersion() { return active.isEmpty() ? bundledVersion() : active; }

    /** Web paketindeki bir dosyayı açar: kurulu güncelleme, yoksa programla gelen assets/web. */
    InputStream open(String rel) {
        try {
            String a = active;
            if (!a.isEmpty()) {
                File f = new File(folder(a), rel);
                if (f.isFile()) return new FileInputStream(f);
                return null;
            }
            return act.getAssets().open("web/" + rel);
        } catch (IOException e) {
            return null;
        }
    }

    synchronized void bootOk() {
        String installed = read("etkin.txt");
        if (!active.isEmpty()) prefs.edit().remove("pending-" + active).apply();
        // yeni bir sürüm kurulmuş ama henüz açılmamışsa geri dönüş noktasına ve klasörüne dokunma
        if (installed.equals(active)) write("onceki.txt", "");
        File[] kids = root.listFiles();
        if (kids == null) return;
        for (File k : kids) {
            String n = k.getName();
            if (!k.isDirectory() || !n.startsWith(KIND + "-")) continue;
            if (n.equals(KIND + "-" + active) || n.equals(KIND + "-" + installed)) continue;
            deleteTree(k);
        }
    }

    // ------------------------------------------------------------ atlanan sürümler
    String skipped() { return prefs.getString("skipped", ""); }

    void skip(String ver) {
        if (ver == null || ver.trim().isEmpty()) return;
        String s = skipped();
        if ((" " + s + " ").contains(" " + ver + " ")) return;
        prefs.edit().putString("skipped", (s + " " + ver).trim()).apply();
    }

    // ------------------------------------------------------------ imza
    static boolean verify(byte[] blob, String sigB64) {
        try {
            byte[] der = Base64.decode(PUB_SPKI, Base64.DEFAULT);
            PublicKey pk = KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));
            Signature s = Signature.getInstance("SHA256withRSA");
            s.initVerify(pk);
            s.update(blob);
            return s.verify(Base64.decode(sigB64 == null ? "" : sigB64, Base64.DEFAULT));
        } catch (Exception e) {
            return false;
        }
    }

    // ------------------------------------------------------------ kurulum
    synchronized String installWeb(String ver, String b64, String sig) {
        if (ver == null || !ver.matches("\\d+(\\.\\d+)*")) return "Geçersiz sürüm adı.";
        byte[] blob;
        try {
            blob = Base64.decode(b64, Base64.DEFAULT);
        } catch (Exception e) {
            return "Güncelleme paketi bozuk indi. Yeniden deneyin.";
        }
        if (!verify(blob, sig)) return "Güncelleme paketinin imzası doğrulanamadı; kurulmadı.";
        File dest = folder(ver);
        File tmp = new File(root, KIND + "-" + ver + ".yeni");
        deleteTree(tmp);
        tmp.mkdirs();
        boolean hasIndex = false;
        try (ZipInputStream z = new ZipInputStream(new ByteArrayInputStream(blob))) {
            ZipEntry e;
            byte[] buf = new byte[65536];
            while ((e = z.getNextEntry()) != null) {
                String name = e.getName();
                if (name.startsWith("web/")) name = name.substring(4);   // "web/" ön ekiyle paketlenmişse
                if (name.isEmpty() || name.contains("..") || name.startsWith("/")) continue;
                File out = new File(tmp, name);
                if (e.isDirectory()) { out.mkdirs(); continue; }
                File parent = out.getParentFile();
                if (parent != null) parent.mkdirs();
                try (OutputStream o = new FileOutputStream(out)) {
                    int n;
                    while ((n = z.read(buf)) > 0) o.write(buf, 0, n);
                }
                if (name.equals("index.html")) hasIndex = true;
            }
        } catch (IOException e) {
            deleteTree(tmp);
            return "Güncelleme paketi açılamadı: " + e.getMessage();
        }
        if (!hasIndex) { deleteTree(tmp); return "Pakette index.html yok."; }
        if (!ver.equals(active)) deleteTree(dest);
        if (dest.exists() || !tmp.renameTo(dest)) {
            if (!dest.exists()) { deleteTree(tmp); return "Güncelleme klasörü yazılamadı."; }
            deleteTree(tmp);
        }
        prefs.edit().remove("pending-" + ver).apply();
        write("onceki.txt", active);
        write("etkin.txt", ver);
        return "";
    }

    String installApk(String b64, String sig) {
        byte[] blob;
        try {
            blob = Base64.decode(b64, Base64.DEFAULT);
        } catch (Exception e) {
            return "Güncelleme paketi bozuk indi. Yeniden deneyin.";
        }
        if (!verify(blob, sig)) return "Güncelleme paketinin imzası doğrulanamadı; kurulmadı.";
        if (Build.VERSION.SDK_INT >= 26 && !act.getPackageManager().canRequestPackageInstalls()) {
            Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + act.getPackageName()));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(i);
            return "Önce Organizer'a \"bu kaynaktan uygulama yükleme\" izni verin, sonra yeniden deneyin.";
        }
        try {
            File dir = new File(act.getCacheDir(), "share");
            dir.mkdirs();
            File f = new File(dir, "Organizer.apk");
            try (OutputStream o = new FileOutputStream(f)) { o.write(blob); }
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(FilesProvider.uriFor(f), "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            act.startActivity(i);
            return "";
        } catch (Exception e) {
            return "APK kurulumu başlatılamadı: " + e.getMessage();
        }
    }
}
