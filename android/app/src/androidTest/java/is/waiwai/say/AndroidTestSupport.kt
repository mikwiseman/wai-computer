package `is`.waiwai.say

import androidx.annotation.StringRes
import androidx.test.core.app.ApplicationProvider

fun string(
    @StringRes resId: Int,
    vararg formatArgs: Any,
): String {
    return ApplicationProvider.getApplicationContext<android.content.Context>()
        .getString(resId, *formatArgs)
}
