package `is`.waiwai.computer.ui.components

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View

/**
 * Centralized haptic feedback so every screen uses the same physical
 * vocabulary. Each tap maps to one Android [HapticFeedbackConstants]
 * value that we feel is closest to the iOS UIImpactFeedbackGenerator
 * equivalent.
 */
object WaiHaptics {
    /** Subtle tap. Use for star toggle, filter chip select. */
    fun tick(view: View) {
        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
    }

    /** Stronger tap. Use for start/stop recording, confirm dialogs. */
    fun confirm(view: View) {
        view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    /** Two-step success buzz. Use after a successful save/upload/import. */
    fun success(view: View) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
        } else {
            view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        }
    }

    /** Sharp warning pulse. Use when surfacing an error banner. */
    fun warn(view: View) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            view.performHapticFeedback(HapticFeedbackConstants.REJECT)
        } else {
            view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
        }
    }
}
