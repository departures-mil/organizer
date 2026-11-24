package com.organizer.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * İndirilen güncelleme APK'sını paket yükleyicisine verir (androidx FileProvider yerine; Gradle'sız kabuk).
 * Yalnız content://com.organizer.app.guncelleme/updates/<ad>.apk → cacheDir/updates/<ad>.apk (ortak ApkPatchInstaller).
 */
public class UpdateFileProvider extends ContentProvider {
    private File file(Uri u) throws FileNotFoundException {
        java.util.List<String> seg = u.getPathSegments();
        if (seg == null || seg.size() != 2 || !"updates".equals(seg.get(0)) || !seg.get(1).matches("[A-Za-z0-9._-]+\\.apk"))
            throw new FileNotFoundException();
        File f = new File(new File(getContext().getCacheDir(), "updates"), seg.get(1));
        if (!f.isFile()) throw new FileNotFoundException();
        return f;
    }

    @Override public boolean onCreate() { return true; }

    @Override
    public ParcelFileDescriptor openFile(Uri u, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(file(u), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri u, String[] p, String s, String[] a, String o) {
        try {
            File f = file(u);
            MatrixCursor c = new MatrixCursor(new String[]{"_display_name", "_size"});
            c.addRow(new Object[]{f.getName(), f.length()});
            return c;
        } catch (Exception e) {
            return null;
        }
    }

    @Override public String getType(Uri u) { return "application/vnd.android.package-archive"; }
    @Override public Uri insert(Uri u, ContentValues v) { return null; }
    @Override public int delete(Uri u, String s, String[] a) { return 0; }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { return 0; }
}
