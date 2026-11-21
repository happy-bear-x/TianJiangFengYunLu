package com.hatkid.mkxpz.utils;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.FileObserver;
import android.provider.Settings;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;

/**
 * 高清版与原版共用存档。
 *
 * 换了包名之后两边私有目录互相隔离，原版存档在
 * /data/data/com.tianjiang.fengyun/files/game 里，高清版读不到。
 * 所以两边共用一份「公共存档目录」，引擎仍然只读写自己的内部目录，
 * 由这一层负责双向同步：
 *
 *   - 启动前  sync()：两边比对修改时间，新的覆盖旧的（顺便完成老存档迁移）
 *   - 运行中  监听内部目录，玩家一存档就立刻回写公共目录
 *   - 退到后台 sync()：兜底再同步一次
 *
 * 拿不到「所有文件访问」权限时全部降级为空操作，游戏照常能玩，
 * 只是存档不再跨版本共用。
 */
public final class SaveShare {

    private static final String TAG = "TianJiang[Save]";
    private static final String PREF = "save_share";
    private static final String KEY_ASKED = "asked_access";
    /** 公共目录：Documents/天降风云录 */
    private static final String PUBLIC_DIR_NAME = "天降风云录";
    /** 允许 2 秒的时间戳误差，避免复制后 mtime 精度不同导致来回覆盖 */
    private static final long TIME_SLACK_MS = 2000L;

    private SaveShare() {
    }

    public static boolean isSaveFile(String name) {
        return name != null && name.startsWith("Save") && name.endsWith(".rxdata");
    }

    /** 公共存档目录，没有权限或不可用时返回 null */
    public static File publicDir() {
        try {
            File docs = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS);
            if (docs == null) return null;
            return new File(docs, PUBLIC_DIR_NAME);
        } catch (Exception e) {
            return null;
        }
    }

    public static boolean hasAccess(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            return Environment.isExternalStorageManager();
        }
        return context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                == PackageManager.PERMISSION_GRANTED;
    }

    /** 跳转到授权页；API 30+ 是「所有文件访问」，以下是普通存储权限 */
    public static Intent accessIntent(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
            intent.setData(Uri.parse("package:" + context.getPackageName()));
            if (intent.resolveActivity(context.getPackageManager()) != null) {
                return intent;
            }
            return new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
        }
        return null;
    }

    public static boolean askedBefore(Context context) {
        return prefs(context).getBoolean(KEY_ASKED, false);
    }

    public static void markAsked(Context context) {
        prefs(context).edit().putBoolean(KEY_ASKED, true).apply();
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    /**
     * 双向同步：同名文件新的覆盖旧的，只在一侧存在就补到另一侧。
     * 这样既能拿到另一版本的进度，也能把权限授予之前攒下的老存档迁出去。
     *
     * @return 实际复制的文件数
     */
    public static int sync(File gameDir) {
        if (gameDir == null || !gameDir.isDirectory()) return 0;
        File pub = publicDir();
        if (pub == null) return 0;
        if (!pub.isDirectory() && !pub.mkdirs()) {
            Log.w(TAG, "无法创建公共存档目录: " + pub);
            return 0;
        }

        Set<String> names = new HashSet<>();
        collectSaves(gameDir, names);
        collectSaves(pub, names);

        int copied = 0;
        for (String name : names) {
            File inner = new File(gameDir, name);
            File outer = new File(pub, name);
            boolean hasInner = inner.isFile();
            boolean hasOuter = outer.isFile();
            try {
                if (hasInner && !hasOuter) {
                    copy(inner, outer);
                    copied++;
                } else if (!hasInner && hasOuter) {
                    copy(outer, inner);
                    copied++;
                } else if (hasOuter && outer.lastModified() > inner.lastModified() + TIME_SLACK_MS) {
                    copy(outer, inner);
                    copied++;
                } else if (hasInner && inner.lastModified() > outer.lastModified() + TIME_SLACK_MS) {
                    copy(inner, outer);
                    copied++;
                }
            } catch (IOException e) {
                Log.e(TAG, "同步存档失败: " + name, e);
            }
        }
        if (copied > 0) {
            Log.i(TAG, "存档同步完成，共 " + copied + " 个文件");
        }
        return copied;
    }

    private static void collectSaves(File dir, Set<String> out) {
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) {
            if (f.isFile() && isSaveFile(f.getName())) {
                out.add(f.getName());
            }
        }
    }

    /** 原子复制：先写 .tmp 再改名，避免另一版本读到写了一半的存档 */
    private static void copy(File src, File dst) throws IOException {
        File parent = dst.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("无法创建目录: " + parent);
        }
        File tmp = new File(parent, dst.getName() + ".share.tmp");
        try (FileInputStream in = new FileInputStream(src);
             FileOutputStream out = new FileOutputStream(tmp)) {
            byte[] buffer = new byte[16 * 1024];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            out.getFD().sync();
        }
        if (!tmp.renameTo(dst)) {
            // 某些设备 rename 到已有文件会失败，退化成覆盖写
            try (FileInputStream in = new FileInputStream(tmp);
                 FileOutputStream out = new FileOutputStream(dst)) {
                byte[] buffer = new byte[16 * 1024];
                int read;
                while ((read = in.read(buffer)) > 0) {
                    out.write(buffer, 0, read);
                }
            }
            tmp.delete();
        }
        dst.setLastModified(src.lastModified());
    }

    /**
     * 监听内部存档目录，玩家存档后立刻回写公共目录。
     * 文件名以 Save 开头才会触发（引擎还会写 Graphics/Data 等缓存）。
     */
    public static FileObserver watch(final File gameDir) {
        if (gameDir == null || publicDir() == null) return null;
        int mask = FileObserver.CLOSE_WRITE | FileObserver.MOVED_TO | FileObserver.CREATE;
        final FileObserver observer = new FileObserver(gameDir.getAbsolutePath(), mask) {
            private final Set<String> pending = new HashSet<>();
            private long lastPush;

            @Override
            public void onEvent(int event, String path) {
                if (!isSaveFile(path)) return;
                long now = System.currentTimeMillis();
                // 引擎保存时可能连写多个文件，合并成一次同步
                synchronized (pending) {
                    pending.add(path);
                    if (now - lastPush < 600) return;
                    lastPush = now;
                }
                final long stamp = now;
                new Thread(() -> {
                    try {
                        Thread.sleep(700);
                    } catch (InterruptedException ignored) {
                        return;
                    }
                    synchronized (pending) {
                        if (stamp != lastPush) return;
                    }
                    sync(gameDir);
                }, "tianjiang-save-sync").start();
            }
        };
        try {
            observer.startWatching();
            return observer;
        } catch (Exception e) {
            Log.w(TAG, "存档监听启动失败", e);
            return null;
        }
    }
}
