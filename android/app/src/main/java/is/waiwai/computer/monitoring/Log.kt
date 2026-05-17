package `is`.waiwai.computer.monitoring

import android.util.Log

object WaiLog {
    fun d(tag: String, message: String) {
        Log.d(tag, message)
    }

    fun w(tag: String, message: String, throwable: Throwable? = null) {
        Log.w(tag, message, throwable)
    }

    fun e(tag: String, message: String, throwable: Throwable? = null) {
        Log.e(tag, message, throwable)
    }
}
