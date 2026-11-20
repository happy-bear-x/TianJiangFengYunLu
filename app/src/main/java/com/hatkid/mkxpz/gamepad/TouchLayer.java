package com.hatkid.mkxpz.gamepad;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Handler;
import android.os.Looper;
import android.util.AttributeSet;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;

import org.libsdl.app.SDLActivity;

/**
 * Unified touch input for the RGSS game.
 *
 * Two gesture families are handled here, in Java, so they never reach SDL:
 *   - a floating joystick: press anywhere in the lower-left zone, the knob
 *     follows the finger, and 8 directions (including diagonals) are sent as
 *     held DPAD keys. Diagonals hold BOTH keys at once; the game reads them
 *     through Input.dir8 and calls the built-in diagonal move methods.
 *   - two action buttons (confirm / cancel) in the lower-right zone.
 *
 * Every other pointer is turned into a synthetic, REAL SDL mouse event
 * (not a touch-synthesized one). Those drive Input.mouse_x / mouse_y and
 * Input::MOUSELEFT, which the injected Ruby touch layer uses for menu
 * hit-testing. TouchLayer consumes the whole MotionEvent so SDL never sees
 * a joystick finger: SDL would otherwise synthesize a mouse from the first
 * finger only and menu taps would be attributed to the wrong pointer.
 */
public class TouchLayer extends View
{
    private static final int DIR_UP    = 1;
    private static final int DIR_DOWN  = 2;
    private static final int DIR_LEFT  = 4;
    private static final int DIR_RIGHT = 8;

    private static final int KEY_CONFIRM = KeyEvent.KEYCODE_C;
    private static final int KEY_CANCEL  = KeyEvent.KEYCODE_X;

    /**
     * Joystick trigger zone ("跟手范围"): where a finger may land and still
     * grab the stick. The knob itself keeps its own size (see mJoyRadius);
     * this only decides how generous the catch area is. Widened from the
     * old 30%/32% corner because reaching that far down-left forced the
     * thumb to leave the screen edge on tall phones.
     *
     * Still an explicit box rather than the whole lower-left half: an
     * oversized zone used to swallow taps meant for left-side menu items.
     */
    private static final float JOY_ZONE_MAX_X   = 0.42f;   // left 42%
    private static final float JOY_ZONE_MIN_Y   = 0.52f;   // bottom 48%
    private static final float JOY_HOME_X       = 0.16f;   // idle hint centre
    private static final float JOY_HOME_Y       = 0.78f;

    private int mWidth, mHeight;
    private float mJoyRadius, mDeadZone;
    private float mBtnRadius;
    private float mConfirmX, mConfirmY, mCancelX, mCancelY;
    private float mHomeX, mHomeY;

    private int mJoyPointer = -1;
    private int mBtnPointer = -1;
    private int mTapPointer = -1;
    private int mBtnKey = 0;
    private int mTapSeq = 0;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private int mDirMask = 0;
    private float mJoyCx, mJoyCy, mJoyKx, mJoyKy;

    private final Paint mFill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mStroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mText = new Paint(Paint.ANTI_ALIAS_FLAG);

    public TouchLayer(Context context) { super(context); init(); }
    public TouchLayer(Context context, AttributeSet attrs) { super(context, attrs); init(); }
    public TouchLayer(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr); init();
    }

    private void init()
    {
        setClickable(false);
        setFocusable(false);
        mStroke.setStyle(Paint.Style.STROKE);
        mStroke.setStrokeWidth(3f);
        mText.setTextAlign(Paint.Align.CENTER);
        mText.setColor(Color.argb(210, 255, 255, 255));
        startClipboardWatcher();
    }

    /**
     * RGSS has no clipboard API, so the injected Ruby layer drops the text
     * it wants copied into a small file inside the game directory and this
     * poller forwards it to the real system clipboard.
     *
     * File-as-mailbox keeps the engine binary untouched (no .so rebuild)
     * and works on every API level we support. The game runs in the
     * foreground whenever this fires, which is what Android 10+ requires
     * for clipboard writes.
     */
    private void startClipboardWatcher()
    {
        mHandler.postDelayed(new Runnable()
        {
            @Override public void run()
            {
                pollClipboardRequest();
                mHandler.postDelayed(this, 450);
            }
        }, 450);
    }

    private void pollClipboardRequest()
    {
        try
        {
            File f = new File(getContext().getFilesDir(), "game/tj_clipboard");
            if (!f.exists())
                return;
            long len = f.length();
            if (len <= 0 || len > 512)
            {
                f.delete();
                return;
            }
            byte[] buf = new byte[(int) len];
            FileInputStream in = new FileInputStream(f);
            int read = in.read(buf);
            in.close();
            f.delete();
            if (read <= 0)
                return;
            String text = new String(buf, 0, read, "UTF-8").trim();
            if (text.length() == 0)
                return;
            ClipboardManager cm = (ClipboardManager)
                    getContext().getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm == null)
                return;
            cm.setPrimaryClip(ClipData.newPlainText("TianJiangFengYun", text));
            Toast.makeText(getContext(), "已复制：" + text, Toast.LENGTH_SHORT).show();
        }
        catch (Exception e)
        {
            // 剪贴板被系统策略拒绝时不打扰玩家，下次再试
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldW, int oldH)
    {
        mWidth = w;
        mHeight = h;
        float base = Math.min(w, h);
        mJoyRadius = base * 0.13f;
        mDeadZone = mJoyRadius * 0.18f;
        mBtnRadius = base * 0.075f;
        // Xbox face-button geometry: A sits at the bottom of the diamond,
        // B to its upper right. Windows / Android players read position
        // before letter, so the on-screen pair mirrors a physical pad
        // instead of the old Nintendo-style (A right, B bottom) layout.
        mConfirmX = w * 0.835f;   // A — confirm, lower button
        mConfirmY = h * 0.875f;
        mCancelX = w * 0.925f;    // B — cancel, right button
        mCancelY = h * 0.755f;
        mHomeX = w * JOY_HOME_X;
        mHomeY = h * JOY_HOME_Y;
    }

    private boolean inJoystickZone(float x, float y)
    {
        return x < mWidth * JOY_ZONE_MAX_X && y > mHeight * JOY_ZONE_MIN_Y;
    }

    private int hitActionButton(float x, float y)
    {
        float r2 = mBtnRadius * mBtnRadius * 1.7f;
        float dx = x - mConfirmX, dy = y - mConfirmY;
        if (dx * dx + dy * dy <= r2) return KEY_CONFIRM;
        dx = x - mCancelX; dy = y - mCancelY;
        if (dx * dx + dy * dy <= r2) return KEY_CANCEL;
        return 0;
    }

    /**
     * Consumes every touch. Joystick / action pointers become held SDL keys;
     * every other pointer becomes a synthetic, real SDL mouse event.
     *
     * Returning true for the WHOLE MotionEvent is what keeps a joystick
     * finger out of SDL. That also lets a joystick and a tap work at the
     * same time, which the old overlay could never do.
     */
    public boolean handleTouch(MotionEvent evt)
    {
        final int action = evt.getActionMasked();
        final int idx = evt.getActionIndex();

        switch (action)
        {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN:
            {
                int pid = evt.getPointerId(idx);
                float x = evt.getX(idx), y = evt.getY(idx);
                if (mJoyPointer < 0 && inJoystickZone(x, y))
                {
                    mJoyPointer = pid;
                    mJoyCx = mJoyKx = x;
                    mJoyCy = mJoyKy = y;
                    mDirMask = 0;
                }
                else
                {
                    int key = hitActionButton(x, y);
                    if (key != 0 && mBtnPointer < 0)
                    {
                        mBtnPointer = pid;
                        mBtnKey = key;
                        SDLActivity.onNativeKeyDown(key);
                    }
                    else if (mTapPointer < 0)
                    {
                        mTapPointer = pid;
                        final int seq = ++mTapSeq;
                        // SDL only refreshes mouseState.x/y on a MOVE event,
                        // so position the cursor BEFORE signalling the tap.
                        sendMouse(MotionEvent.ACTION_MOVE, x, y);
                        // Tap signal rides the KEYBOARD path: on this device
                        // SDL's onNativeMouse DOWN never reaches the engine
                        // (motion does), while onNativeKeyDown is the path
                        // the legacy on-screen pad used and is proven.
                        // Ruby watches it via Input.raw_key_states as a
                        // rising edge on SDL_SCANCODE_F10 (= 67).
                        SDLActivity.onNativeKeyUp(TAP_KEY);
                        SDLActivity.onNativeKeyDown(TAP_KEY);
                        // Hold ~140 ms so RGSS (40 fps) samples the edge
                        // even for a very quick tap; ACTION_UP does not
                        // release early, only this timeout does.
                        mHandler.postDelayed(new Runnable()
                        {
                            @Override public void run()
                            {
                                if (seq == mTapSeq)
                                    SDLActivity.onNativeKeyUp(TAP_KEY);
                            }
                        }, 140);
                    }
                }
                break;
            }

            case MotionEvent.ACTION_MOVE:
                for (int i = 0; i < evt.getPointerCount(); i++)
                {
                    int pid = evt.getPointerId(i);
                    if (pid == mJoyPointer)
                        applyJoystick(evt.getX(i), evt.getY(i));
                    else if (pid == mTapPointer)
                        sendMouse(MotionEvent.ACTION_MOVE, evt.getX(i), evt.getY(i));
                }
                break;

            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP:
            {
                int pid = evt.getPointerId(idx);
                if (pid == mJoyPointer) stopJoystick();
                if (pid == mBtnPointer) stopButton();
                if (pid == mTapPointer)
                {
                    // Do NOT release here. The delayed release scheduled on
                    // DOWN keeps the button held ~140 ms so RGSS (40 fps)
                    // samples at least one pressed frame. An immediate UP
                    // after a 1 ms tap would close the same frame and
                    // Input.trigger?(MOUSELEFT) would never see the edge.
                    mTapPointer = -1;
                }
                break;
            }

            case MotionEvent.ACTION_CANCEL:
                ++mTapSeq;
                stopJoystick();
                stopButton();
                if (mTapPointer >= 0)
                {
                    SDLActivity.onNativeKeyUp(TAP_KEY);
                    mTapPointer = -1;
                }
                break;

            default:
                break;
        }

        invalidate();
        return true;
    }

    /**
     * Inject a genuine (non touch-synthesized) SDL mouse event. Button 1 is
     * SDL_BUTTON_LEFT, matching MsBinding(SDL_BUTTON_LEFT, Input::MouseLeft).
     * eventthread.cpp drops SDL_TOUCH_MOUSEID events, so a real mouse event
     * is required for this to work without rebuilding the native library.
     */
    /**
     * KEYCODE_F10 (= 140). Double-checked against the Android keycode table:
     * 142 would be KEYCODE_F12, and mkxp-z handles F12 as an RGSS reset
     * (eventthread.cpp), which kills the game. Ruby listens on
     * SDL_SCANCODE_F10 (= 67) via Input.raw_key_states.
     */
    private static final int TAP_KEY = 140;

    private void sendMouse(int action, float x, float y)
    {
        android.util.Log.d("TJTouch", "sendMouse action=" + action
            + " x=" + (int) x + " y=" + (int) y);
        SDLActivity.onNativeMouse(1, action, x, y, false);
    }

    private void applyJoystick(float x, float y)
    {
        float dx = x - mJoyCx, dy = y - mJoyCy;
        float dist = (float) Math.hypot(dx, dy);
        if (dist > mJoyRadius)
        {
            float k = mJoyRadius / dist;
            dx *= k; dy *= k;
            dist = mJoyRadius;
        }
        mJoyKx = mJoyCx + dx;
        mJoyKy = mJoyCy + dy;

        int mask = 0;
        if (dist >= mDeadZone)
        {
            // Screen coordinates: +x right, +y down. Sector 0 = right,
            // then clockwise in 45 degree steps.
            float angle = (float) Math.toDegrees(Math.atan2(dy, dx));
            int sector = ((int) Math.floor((angle + 22.5f + 360f) / 45f)) % 8;
            switch (sector)
            {
                case 0: mask = DIR_RIGHT;                 break;
                case 1: mask = DIR_RIGHT | DIR_DOWN;     break;
                case 2: mask = DIR_DOWN;                  break;
                case 3: mask = DIR_DOWN  | DIR_LEFT;     break;
                case 4: mask = DIR_LEFT;                  break;
                case 5: mask = DIR_LEFT  | DIR_UP;       break;
                case 6: mask = DIR_UP;                    break;
                default: mask = DIR_UP   | DIR_RIGHT;    break;
            }
        }
        setDirectionMask(mask);
    }

    /** Diff the held-direction set so diagonal changes never leave a stuck key. */
    private void setDirectionMask(int mask)
    {
        if (mask == mDirMask) return;
        syncKey(DIR_UP,    KeyEvent.KEYCODE_DPAD_UP,    mask);
        syncKey(DIR_DOWN,  KeyEvent.KEYCODE_DPAD_DOWN,  mask);
        syncKey(DIR_LEFT,  KeyEvent.KEYCODE_DPAD_LEFT,  mask);
        syncKey(DIR_RIGHT, KeyEvent.KEYCODE_DPAD_RIGHT, mask);
        mDirMask = mask;
    }

    private void syncKey(int bit, int keycode, int mask)
    {
        boolean was = (mDirMask & bit) != 0;
        boolean now = (mask & bit) != 0;
        if (now && !was) SDLActivity.onNativeKeyDown(keycode);
        else if (!now && was) SDLActivity.onNativeKeyUp(keycode);
    }

    private void stopJoystick()
    {
        setDirectionMask(0);
        mJoyPointer = -1;
    }

    private void stopButton()
    {
        if (mBtnKey != 0)
        {
            SDLActivity.onNativeKeyUp(mBtnKey);
            mBtnKey = 0;
        }
        mBtnPointer = -1;
    }

    @Override
    protected void onDraw(Canvas c)
    {
        super.onDraw(c);
        // Letter first, meaning second: pad users scan for A/B, touch-only
        // players fall back to the Chinese verb underneath.
        drawButton(c, mConfirmX, mConfirmY, "A", "确定", mBtnKey == KEY_CONFIRM);
        drawButton(c, mCancelX, mCancelY, "B", "返回", mBtnKey == KEY_CANCEL);

        if (mJoyPointer >= 0)
        {
            mFill.setColor(Color.argb(45, 255, 255, 255));
            mFill.setStyle(Paint.Style.FILL);
            mStroke.setColor(Color.argb(110, 255, 255, 255));
            c.drawCircle(mJoyCx, mJoyCy, mJoyRadius, mFill);
            c.drawCircle(mJoyCx, mJoyCy, mJoyRadius, mStroke);
            mFill.setColor(Color.argb(120, 255, 255, 255));
            c.drawCircle(mJoyKx, mJoyKy, mJoyRadius * 0.44f, mFill);
        }
        else
        {
            // Idle hint: just enough to show where the joystick lives,
            // faint enough to disappear over map art (alpha 20-40).
            float r = mJoyRadius * 0.80f;
            mFill.setStyle(Paint.Style.FILL);
            mFill.setColor(Color.argb(20, 255, 255, 255));
            c.drawCircle(mHomeX, mHomeY, r, mFill);
            mStroke.setColor(Color.argb(36, 255, 255, 255));
            c.drawCircle(mHomeX, mHomeY, r, mStroke);
            mFill.setColor(Color.argb(30, 255, 255, 255));
            c.drawCircle(mHomeX, mHomeY, mJoyRadius * 0.30f, mFill);
        }
    }

    private void drawButton(Canvas c, float x, float y, String letter, String label, boolean pressed)
    {
        mFill.setStyle(Paint.Style.FILL);
        mFill.setColor(pressed ? Color.argb(115, 255, 255, 255)
                               : Color.argb(40, 255, 255, 255));
        mStroke.setColor(Color.argb(95, 255, 255, 255));
        c.drawCircle(x, y, mBtnRadius, mFill);
        c.drawCircle(x, y, mBtnRadius, mStroke);
        // Xbox face buttons are prominent glyphs, so the letter gets the
        // large slot above centre and the action word rides beneath it.
        mText.setTextSize(mBtnRadius * 0.74f);
        Paint.FontMetrics fm = mText.getFontMetrics();
        c.drawText(letter, x, y - mBtnRadius * 0.20f - (fm.ascent + fm.descent) / 2f, mText);
        mText.setTextSize(mBtnRadius * 0.34f);
        fm = mText.getFontMetrics();
        c.drawText(label, x, y + mBtnRadius * 0.48f - (fm.ascent + fm.descent) / 2f, mText);
    }
}
