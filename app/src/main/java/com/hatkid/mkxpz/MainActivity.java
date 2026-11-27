package com.hatkid.mkxpz;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.view.InputDevice;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.os.Environment;
import android.os.FileObserver;
import android.os.Vibrator;
import android.os.VibrationEffect;
import android.os.storage.StorageManager;
import android.os.storage.OnObbStateChangeListener;
import android.net.Uri;
import android.provider.Settings;
import android.util.Log;
import android.widget.Toast;
import java.util.Locale;
import java.io.File;

import org.libsdl.app.SDLActivity;
import com.hatkid.mkxpz.gamepad.Gamepad;
import com.hatkid.mkxpz.gamepad.GamepadConfig;
import com.hatkid.mkxpz.utils.SaveShare;

public class MainActivity extends SDLActivity
{
    // This activity inherits from SDLActivity activity.
    // Put your Java-side stuff here.

    private static final String TAG = "mkxp-z[Activity]";
    private static final String GAME_PATH_DEFAULT = Environment.getExternalStorageDirectory() + "/mkxp-z";
    private static String GAME_PATH = GAME_PATH_DEFAULT;
    private static String OBB_MAIN_FILENAME;
    private static boolean DEBUG = false;

    protected boolean mStarted = false;

    private StorageManager mStorageManager;
    // 存档共用到公共目录：目录监听 + 退出前兜底同步
    private File saveSyncDir;
    private FileObserver saveObserver;
    // In-screen gamepad
    private final Gamepad mGamepad = new Gamepad();
    private boolean mGamepadInvisible = false;
    // 双击返回键：上一次按下的时间戳（uptimeMillis），0 表示没有待配对的按键
    private long mLastBackAt = 0L;
    private static final long BACK_DOUBLE_MS = 800L;

    private void runSDLThread()
    {
        if (!mStarted) {
            Log.i(TAG, "Game path: " + GAME_PATH);
        }

        mStarted = true;

        // Run (resume) native SDL thread
        if (mHasMultiWindow) {
            resumeNativeThread();
        }
    }

    OnObbStateChangeListener obbListener = new OnObbStateChangeListener()
    {
        @Override
        public void onObbStateChange(String path, int state)
        {
            super.onObbStateChange(path, state);

            Log.v(TAG, "OBB state of " + path + " changed to " + state);

            switch (state)
            {
                case OnObbStateChangeListener.MOUNTED:
                    String obbPath = mStorageManager.getMountedObbPath(path);
                    Log.v(TAG, "OBB " + path + " is mounted to " + obbPath);
                    GAME_PATH = obbPath;
                    break;

                case OnObbStateChangeListener.UNMOUNTED:
                    Log.v(TAG, "OBB " + path + " is unmounted");
                    GAME_PATH = GAME_PATH_DEFAULT;
                    break;

                default:
                    Log.e(TAG, "Failed to mount OBB " + path + ": Got state " + state);
                    break;
            }

            runSDLThread();
        }
    };

    /**
     * RGSS has no way to ask for the physical screen size, but the canvas
     * width has to be decided before the first script runs: mkxp_compat.rb
     * calls Graphics.resize_screen() from a preload script.
     *
     * So drop "WxH" into the game directory here, before the native library
     * loads and mkxp starts evaluating scripts. The Ruby side reads it and
     * picks a canvas width matching the device aspect ratio, clamped so an
     * ultra-wide panel does not stretch the world absurdly far.
     */
    private void writeScreenMetrics(File gameDir)
    {
        try
        {
            android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
            int longSide = Math.max(dm.widthPixels, dm.heightPixels);
            int shortSide = Math.min(dm.widthPixels, dm.heightPixels);
            if (longSide <= 0 || shortSide <= 0)
                return;
            File f = new File(gameDir, "tj_screen");
            java.io.FileWriter w = new java.io.FileWriter(f);
            w.write(longSide + "x" + shortSide);
            w.close();
        }
        catch (Exception e)
        {
            // 拿不到就退回默认 16:9，不影响启动
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState)
    {
        File gameDir = new File(getFilesDir(), "game");
        GAME_PATH = gameDir.getAbsolutePath();
        if (!new File(gameDir, BootstrapActivity.READY_FILE).isFile()) {
            startActivity(new Intent(this, BootstrapActivity.class));
            finish();
            return;
        }

        writeScreenMetrics(gameDir);

        // 存档共用：先把公共目录的最新进度拉进来，再盯着后续的存档
        saveSyncDir = gameDir;
        if (SaveShare.hasAccess(this)) {
            SaveShare.sync(gameDir);
            saveObserver = SaveShare.watch(gameDir);
        }

        super.onCreate(savedInstanceState);
        applyImmersiveMode();

        mStorageManager = (StorageManager) getSystemService(STORAGE_SERVICE);

        // Get main OBB filepath
        final String obbPrefix = "main"; // "main", "patch"
        final int obbVersion = 1;
        OBB_MAIN_FILENAME = getObbDir() + "/" + obbPrefix + "." + obbVersion + "." + getPackageName() + ".obb";

        // Get Debug flag
        try {
            ActivityInfo actInfo = getPackageManager().getActivityInfo(this.getComponentName(), PackageManager.GET_META_DATA);
            DEBUG = actInfo.metaData.getBoolean("mkxp_debug");
        } catch (PackageManager.NameNotFoundException e) {
            Log.w(TAG, "Failed to set debug flag: " + e);
            e.printStackTrace();
        }

        // Setup in-screen gamepad
        mGamepadInvisible = (isAndroidTV() || isChromebook());
        GamepadConfig gpadConfig = new GamepadConfig();
        mGamepad.init(gpadConfig, mGamepadInvisible);
        mGamepad.setOnKeyDownListener(SDLActivity::onNativeKeyDown);
        mGamepad.setOnKeyUpListener(SDLActivity::onNativeKeyUp);

        if (mLayout != null) {
            mGamepad.attachTo(this, mLayout);
        }
    }

    /**
     * Keep the game edge-to-edge and hide both the status bar and the
     * navigation bar. Some ROMs ignore the legacy fullscreen flags (or show
     * the bars again after a focus change), which used to cover the top of the
     * map and the message window at the bottom.
     */
    private void applyImmersiveMode()
    {
        Window window = getWindow();
        if (window == null) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            WindowManager.LayoutParams lp = window.getAttributes();
            lp.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            window.setAttributes(lp);
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false);
            WindowInsetsController controller = window.getInsetsController();
            if (controller != null) {
                controller.setSystemBarsBehavior(
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controller.hide(WindowInsets.Type.systemBars());
            }
        } else {
            window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            window.getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
    }

    @Override
    protected void onResume()
    {
        super.onResume();
        applyImmersiveMode();
    }

    @Override
    protected void onPause()
    {
        super.onPause();
        // 切后台/退出前把存档回写公共目录，避免进程被直接杀掉丢进度
        if (saveSyncDir != null && SaveShare.hasAccess(this)) {
            SaveShare.sync(saveSyncDir);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus)
    {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            applyImmersiveMode();
        }
    }

    @Override
    protected void onStart()
    {
        super.onStart();

        if (!mStarted) {
            // Check for main OBB file
            if (new File(OBB_MAIN_FILENAME).exists()) {
                Log.v(TAG, "Main OBB file found, starting with main OBB mount");

                // Try to mount main OBB file
                mStorageManager.mountObb(OBB_MAIN_FILENAME, null, obbListener);
            } else {
                Log.v(TAG, "Main OBB file not found, starting without main OBB mount");

                // Run from default game directory
                runSDLThread();
            }
        } else {
            // onStart: Resume SDL thread
            runSDLThread();
        }
    }

    @Override
    protected void onDestroy()
    {
        super.onDestroy();

        if (saveObserver != null) {
            saveObserver.stopWatching();
            saveObserver = null;
        }
        if (saveSyncDir != null && SaveShare.hasAccess(this)) {
            SaveShare.sync(saveSyncDir);
        }

        // HACK: Exiting the JVM (process) since Ruby does not likes when we
        // trying to re-initialize Ruby VM in mkxp-z (JNI native library)
        // that leads to segmentation fault, even we have cleanup the Ruby VM.
        System.exit(0);
    }

    /**
     * 双击返回键打开「结束游戏」确认框。
     *
     * 第一次按下只提示，第二次在 800ms 内则通知 Ruby。物理返回键在 SDL 里
     * 没有对应的 RGSS 输入位（硬塞 keycode 只会落到未映射的 scancode 上），
     * 所以走标记文件：Ruby 侧 TJTouch.poll_back 在 Input.update 里轮询，
     * 命中后由 Scene_Map 切到 Scene_End。
     *
     * 返回键一律不交给系统：单按现在什么都不做，双击才弹确认框，
     * 避免手滑直接把游戏进程关掉。
     */
    private void handleBackKey()
    {
        long now = SystemClock.uptimeMillis();

        if (mLastBackAt != 0L && now - mLastBackAt <= BACK_DOUBLE_MS)
        {
            mLastBackAt = 0L;
            requestExitMenu();
            return;
        }

        mLastBackAt = now;
        Toast.makeText(this, "再按一次返回键，打开游戏菜单", Toast.LENGTH_SHORT).show();
    }

    /** 写 game/tj_back_exit，Ruby 侧读到后弹出退出确认框。 */
    private void requestExitMenu()
    {
        try
        {
            File dir = new File(getFilesDir(), "game");

            if (!dir.exists())
                dir.mkdirs();

            File marker = new File(dir, "tj_back_exit");
            java.io.FileOutputStream out = new java.io.FileOutputStream(marker, false);

            out.write(String.valueOf(System.currentTimeMillis()).getBytes("UTF-8"));
            out.close();
        }
        catch (Exception e)
        {
            Log.w(TAG, "requestExitMenu failed", e);
        }
    }

    @Override
    public void onBackPressed()
    {
        // 部分场景（手势返回）不会走 dispatchKeyEvent，这里兜底
        handleBackKey();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent evt)
    {
        if (evt.getKeyCode() == KeyEvent.KEYCODE_BACK)
        {
            if (evt.getAction() == KeyEvent.ACTION_DOWN && evt.getRepeatCount() == 0)
                handleBackKey();

            return true;
        }

        if (
            evt.getKeyCode() != KeyEvent.KEYCODE_BACK &&
            evt.getKeyCode() != KeyEvent.KEYCODE_VOLUME_UP &&
            evt.getKeyCode() != KeyEvent.KEYCODE_VOLUME_DOWN &&
            evt.getKeyCode() != KeyEvent.KEYCODE_VOLUME_MUTE
        ) {
            // Hide gamepad view on key events when visible
            if (!mGamepadInvisible) {
                mGamepad.hideView();
                mGamepadInvisible = true;
            }
        }

        if (mGamepad.processGamepadEvent(evt))
            return true;

        return super.dispatchKeyEvent(evt);
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent evt)
    {
        // Show gamepad view on touch when hidden
        if (mGamepadInvisible) {
            mGamepad.showView();
            mGamepadInvisible = false;
        }

        // TouchLayer owns all touch input: joystick / action gestures become
        // held SDL keys, tap gestures become synthetic real mouse events.
        // Nothing is forwarded to SDLSurface, so SDL never sees a joystick
        // finger and a tap pointer can never be misattributed.
        if (mGamepad.handleTouch(evt))
            return true;

        return super.dispatchTouchEvent(evt);
    }

    @Override
    public boolean onGenericMotionEvent(MotionEvent evt)
    {
        if (mGamepad.processDPadEvent(evt))
            return true;

        return super.onGenericMotionEvent(evt);
    }

    /**
     * This method is for arguments for launching native mkxp-z.
     * 
     * @return arguments for the mkxp-z
     */
    @Override
    protected String[] getArguments()
    {
        String[] args;

        if (DEBUG) {
            // Arguments in Debug mode
            args = new String[] { "debug" };
        } else {
            // Arguments in normal mode
            args = new String[] {};
        }

        return args;
    }

    /**
     * This static method is used in native mkxp-z. (see systemImpl.cpp)
     * This method returns a string of current device locale tag. (e.g. "en_US")
     * 
     * @return string of locale tag
     */
    @SuppressWarnings("unused")
    private static String getSystemLanguage()
    {
        return Locale.getDefault().toString();
    }

    /**
     * This static method is used in native mkxp-z. (see android-binding.cpp)
     * This method returns a boolean indicating that the device has a vibrator or not.
     * 
     * @return boolean
     */
    @SuppressWarnings("unused")
    private static boolean hasVibrator()
    {
        Vibrator vib = (Vibrator) getContext().getSystemService(Context.VIBRATOR_SERVICE);
        return vib.hasVibrator();
    }

    /**
     * This static method is used in native mkxp-z. (see android-binding.cpp)
     * This method makes device vibrating with given milliseconds duration.
     * 
     * @param duration milliseconds duration of vibration
     */
    @SuppressWarnings("unused")
    private static void vibrate(int duration)
    {
        Vibrator vib = (Vibrator) getContext().getSystemService(Context.VIBRATOR_SERVICE);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vib.vibrate(VibrationEffect.createOneShot(duration, VibrationEffect.EFFECT_HEAVY_CLICK));
        } else {
            vib.vibrate(duration);
        }
    }

    /**
     * This static method is used in native mkxp-z. (see android-binding.cpp)
     * This method turns off the current device vibration.
     */
    @SuppressWarnings("unused")
    private static void vibrateStop()
    {
        Vibrator vib = (Vibrator) getContext().getSystemService(Context.VIBRATOR_SERVICE);
        vib.cancel();
    }

    /**
     * This static method is used in native mkxp-z. (see android-binding.cpp)
     * This method returns a boolean indicating the app is in multi window mode or not.
     * (Multi-window mode supports from Android 7.0 Nougat (API 24) and higher.)
     * 
     * @param activity current MainActivity instance
     * @return boolean
     */
    @SuppressWarnings("unused")
    private static boolean inMultiWindow(Activity activity)
    {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.N && activity.isInMultiWindowMode();
    }
}