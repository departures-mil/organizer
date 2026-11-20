package com.organizer.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.webkit.MimeTypeMap;

import java.io.File;
import java.io.FileNotFoundException;

/** Önbellekteki share/ ve camera/ klasörlerindeki dosyaları başka uygulamalara (paylaşım, kamera, kurulum) verir. */
public class FilesProvider extends ContentProvider {
    static final String AUTHORITY = "com.organizer.app.files";
    private static Context ctx;

    static Uri uriFor(File f) {
        File cache = ctx.getCacheDir();
        String rel = f.getAbsolutePath().substring(cache.getAbsolutePath().length() + 1).replace(File.separatorChar, '/');
        return Uri.parse("content://" + AUTHORITY + "/" + rel);
    }

    private File fileFor(Uri uri) throws FileNotFoundException {
        String p = uri.getPath();
        if (p == null || p.contains("..")) throw new FileNotFoundException();
        p = p.startsWith("/") ? p.substring(1) : p;
        if (!(p.startsWith("share/") || p.startsWith("camera/"))) throw new FileNotFoundException();
        File f = new File(getContext().getCacheDir(), p);
        if (!f.exists()) throw new FileNotFoundException(p);
        return f;
    }

    @Override
    public boolean onCreate() { ctx = getContext(); return true; }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = fileFor(uri);
        int m = mode != null && mode.contains("w") ? ParcelFileDescriptor.MODE_READ_WRITE | ParcelFileDescriptor.MODE_TRUNCATE : ParcelFileDescriptor.MODE_READ_ONLY;
        return ParcelFileDescriptor.open(f, m);
    }

    @Override
    public String getType(Uri uri) {
        String p = uri.getLastPathSegment();
        if (p == null) return "application/octet-stream";
        String ext = p.contains(".") ? p.substring(p.lastIndexOf('.') + 1).toLowerCase() : "";
        if (ext.equals("apk")) return "application/vnd.android.package-archive";
        if (ext.equals("json")) return "application/json";
        String t = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
        return t == null ? "application/octet-stream" : t;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        File f;
        try { f = fileFor(uri); } catch (FileNotFoundException e) { return null; }
        if (projection == null) projection = new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor c = new MatrixCursor(projection, 1);
        Object[] row = new Object[projection.length];
        for (int i = 0; i < projection.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(projection[i])) row[i] = f.getName();
            else if (OpenableColumns.SIZE.equals(projection[i])) row[i] = f.length();
            else row[i] = null;
        }
        c.addRow(row);
        return c;
    }

    @Override public Uri insert(Uri uri, ContentValues v) { return null; }
    @Override public int delete(Uri uri, String s, String[] a) { return 0; }
    @Override public int update(Uri uri, ContentValues v, String s, String[] a) { return 0; }
}
