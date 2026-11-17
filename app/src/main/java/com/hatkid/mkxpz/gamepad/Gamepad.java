package com.hatkid.mkxpz.gamepad;

import android.content.Context;
import android.view.ViewGroup;
import android.view.LayoutInflater;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.animation.AlphaAnimation;
import android.widget.RelativeLayout;

import com.hatkid.mkxpz.R;

/**
 * Owns the on-screen touch layer and bridges physical gamepad / D-pad events.
 *
 * Touch handling itself lives in TouchLayer. MainActivity asks this class
 * whether a MotionEvent belongs to a joystick / action-button gesture; if not,
 * the event is forwarded to SDLSurface so SDL2 can synthesize mouse events
 * from the tap finger (used by the Ruby touch layer for menu hit-testing).
 */
public class Gamepad
{
    private static final int DIR_UP    = 1;
    private static final int DIR_DOWN  = 2;
    private static final int DIR_LEFT  = 4;
    private static final int DIR_RIGHT = 8;

    private boolean mInvisible = false;
    private int mStickMask = 0;

    private OnKeyDownListener mOnKeyDownListener = key -> {};
    private OnKeyUpListener mOnKeyUpListener = key -> {};

    public interface OnKeyDownListener
    {
        void onKeyDown(int key);
    }

    public interface OnKeyUpListener
    {
        void onKeyUp(int key);
    }

    public void setOnKeyDownListener(OnKeyDownListener onKeyDownListener)
    {
        mOnKeyDownListener = onKeyDownListener;
    }

    public void setOnKeyUpListener(OnKeyUpListener onKeyUpListener)
    {
        mOnKeyUpListener = onKeyUpListener;
    }

    private RelativeLayout mGamepadLayout;
    private TouchLayer mTouchLayer;

    public void init(GamepadConfig gpadConfig, boolean invisible)
    {
        mInvisible = invisible;
    }

    public void attachTo(Context context, ViewGroup viewGroup)
    {
        LayoutInflater inflater =
            (LayoutInflater) context.getSystemService(Context.LAYOUT_INFLATER_SERVICE);
        ViewGroup layout = (ViewGroup) inflater.inflate(R.layout.gamepad_layout, viewGroup);
        mGamepadLayout = layout.findViewById(R.id.gamepad_layout);
        mTouchLayer = layout.findViewById(R.id.touch_layer);

        if (mInvisible && mGamepadLayout != null)
            mGamepadLayout.setAlpha(0);
    }

    /** @return true when the event is a joystick / action-button gesture. */
    public boolean handleTouch(MotionEvent evt)
    {
        return mTouchLayer != null && mTouchLayer.handleTouch(evt);
    }

    public void showView()
    {
        if (mGamepadLayout != null) {
            if (mGamepadLayout.getAlpha() == 0)
                mGamepadLayout.setAlpha(1);

            AlphaAnimation anim = new AlphaAnimation(0.0f, 1.0f);
            anim.setDuration(250);
            anim.setFillAfter(true);
            mGamepadLayout.startAnimation(anim);
        }
    }

    public void hideView()
    {
        if (mGamepadLayout != null) {
            AlphaAnimation anim = new AlphaAnimation(1.0f, 0.0f);
            anim.setDuration(500);
            anim.setFillAfter(true);
            mGamepadLayout.startAnimation(anim);
        }
    }

    /**
     * Android reports physical pad buttons with dedicated key codes
     * (KEYCODE_BUTTON_A = 96, ...), but mkxp-z's input layer is driven by
     * keyboard scancodes: SDLActivity only hands controller-sized codes to
     * SDLControllerManager when its own dispatchKeyEvent runs, and
     * MainActivity intercepts pad events before that. Passing 96 straight
     * through onNativeKeyDown therefore lands on an unmapped scancode and
     * the game ignores it.
     *
     * Translating to the codes RGSS1 actually binds restores native pad
     * play with no engine change. Targets come from mkxp-z's
     * defaultCtrlBindings plus defaultKbBindings1:
     *   A -> Space (Input::C, confirm)     B -> X (Input::B, cancel/menu)
     *   X -> Shift (Input::A)              Y -> A (Input::X)
     *   L1/R1 -> Q/W (Input::L/R)          Start -> Esc (Input::B, menu)
     */
    private static int mapPadKey(int keyCode)
    {
        switch (keyCode)
        {
            case KeyEvent.KEYCODE_BUTTON_A:      return KeyEvent.KEYCODE_SPACE;
            case KeyEvent.KEYCODE_BUTTON_B:      return KeyEvent.KEYCODE_X;
            case KeyEvent.KEYCODE_BUTTON_X:      return KeyEvent.KEYCODE_SHIFT_LEFT;
            case KeyEvent.KEYCODE_BUTTON_Y:      return KeyEvent.KEYCODE_A;
            case KeyEvent.KEYCODE_BUTTON_L1:     return KeyEvent.KEYCODE_Q;
            case KeyEvent.KEYCODE_BUTTON_R1:     return KeyEvent.KEYCODE_W;
            case KeyEvent.KEYCODE_BUTTON_L2:     return KeyEvent.KEYCODE_PAGE_UP;
            case KeyEvent.KEYCODE_BUTTON_R2:     return KeyEvent.KEYCODE_PAGE_DOWN;
            case KeyEvent.KEYCODE_BUTTON_START:  return KeyEvent.KEYCODE_ESCAPE;
            case KeyEvent.KEYCODE_BUTTON_SELECT: return KeyEvent.KEYCODE_ESCAPE;
            default:
                // D-pad and unbound buttons already carry scancodes mkxp maps.
                return keyCode;
        }
    }

    /** Physical gamepad buttons still go through the original SDL key path. */
    public boolean processGamepadEvent(KeyEvent evt)
    {
        InputDevice device = evt.getDevice();

        if (device == null)
            return false;

        // System back must keep working as back, not become a game button.
        if (evt.getKeyCode() == KeyEvent.KEYCODE_BACK)
            return false;

        int sources = device.getSources();

        if (
            ((sources & InputDevice.SOURCE_GAMEPAD) != InputDevice.SOURCE_GAMEPAD) &&
            ((sources & InputDevice.SOURCE_DPAD) != InputDevice.SOURCE_DPAD) &&
            ((sources & InputDevice.SOURCE_JOYSTICK) != InputDevice.SOURCE_JOYSTICK)
        )
            return false;

        int keycode = mapPadKey(evt.getKeyCode());

        switch (evt.getAction())
        {
            case MotionEvent.ACTION_DOWN:
                mOnKeyDownListener.onKeyDown(keycode);
                break;

            case MotionEvent.ACTION_CANCEL:
            case MotionEvent.ACTION_UP:
                mOnKeyUpListener.onKeyUp(keycode);
                break;
        }

        return true;
    }

    /**
     * D-pad hat and left-stick axes, both folded into the RGSS direction
     * keys. Hat wins when both report at once, matching how pads behave
     * during the overlap at the edge of a press.
     */
    public boolean processDPadEvent(MotionEvent evt)
    {
        InputDevice device = evt.getDevice();

        if (device == null)
            return false;

        int sources = device.getSources();

        if ((sources & (InputDevice.SOURCE_DPAD
                     | InputDevice.SOURCE_GAMEPAD
                     | InputDevice.SOURCE_JOYSTICK)) == 0)
            return false;

        float xAxis = evt.getAxisValue(MotionEvent.AXIS_HAT_X);
        float yAxis = evt.getAxisValue(MotionEvent.AXIS_HAT_Y);
        float lx = evt.getAxisValue(MotionEvent.AXIS_X);
        float ly = evt.getAxisValue(MotionEvent.AXIS_Y);

        int mask = 0;

        if (Math.abs(xAxis) > 0.5f || Math.abs(yAxis) > 0.5f)
        {
            if (xAxis < -0.5f) mask |= DIR_LEFT;
            if (xAxis >  0.5f) mask |= DIR_RIGHT;
            if (yAxis < -0.5f) mask |= DIR_UP;
            if (yAxis >  0.5f) mask |= DIR_DOWN;
        }
        else if (Math.abs(lx) > STICK_DEADZONE || Math.abs(ly) > STICK_DEADZONE)
        {
            // Stick sign convention matches the touch joystick: screen +y is down.
            if (lx < -STICK_DEADZONE) mask |= DIR_LEFT;
            if (lx >  STICK_DEADZONE) mask |= DIR_RIGHT;
            if (ly < -STICK_DEADZONE) mask |= DIR_UP;
            if (ly >  STICK_DEADZONE) mask |= DIR_DOWN;
        }

        if (mask != mStickMask)
        {
            syncDirection(DIR_UP,    KeyEvent.KEYCODE_DPAD_UP,    mask);
            syncDirection(DIR_DOWN,  KeyEvent.KEYCODE_DPAD_DOWN,  mask);
            syncDirection(DIR_LEFT,  KeyEvent.KEYCODE_DPAD_LEFT,  mask);
            syncDirection(DIR_RIGHT, KeyEvent.KEYCODE_DPAD_RIGHT, mask);
            mStickMask = mask;
        }

        // Own all motion from pad devices so SDL never sees a duplicate axis.
        return true;
    }

    private static final float STICK_DEADZONE = 0.45f;

    private void syncDirection(int bit, int keycode, int mask)
    {
        boolean was = (mStickMask & bit) != 0;
        boolean now = (mask & bit) != 0;
        if (now && !was) mOnKeyDownListener.onKeyDown(keycode);
        else if (!now && was) mOnKeyUpListener.onKeyUp(keycode);
    }

    /** Drop any held direction when the pad disconnects. */
    public void resetDirections()
    {
        if (mStickMask == 0)
            return;
        syncDirection(DIR_UP,    KeyEvent.KEYCODE_DPAD_UP,    0);
        syncDirection(DIR_DOWN,  KeyEvent.KEYCODE_DPAD_DOWN,  0);
        syncDirection(DIR_LEFT,  KeyEvent.KEYCODE_DPAD_LEFT,  0);
        syncDirection(DIR_RIGHT, KeyEvent.KEYCODE_DPAD_RIGHT, 0);
        mStickMask = 0;
    }
}
