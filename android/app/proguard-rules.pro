# ----- WaiComputer Android — release ProGuard / R8 rules -----
#
# Notes:
# - Most modern libraries ship their own keep rules via consumer ProGuard
#   files inside the AAR. The rules below cover the gaps we found
#   empirically when first enabling R8 for the v1.0 release.

# ---- App entry points and BuildConfig ----
-keepclassmembers class is.waiwai.computer.BuildConfig {
    public static <fields>;
}

# ---- Kotlin metadata + Compose helpers ----
-keepclasseswithmembers class kotlin.Metadata { *; }
-dontwarn kotlin.**
-dontwarn kotlinx.**

# ---- kotlinx.serialization ----
# Keep all @Serializable companions + their serializer() and INSTANCE.
-keepclasseswithmembers @kotlinx.serialization.Serializable class * {
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers @kotlinx.serialization.Serializable class * {
    static **$* *;
}
-keepclassmembers class **$Companion {
    kotlinx.serialization.KSerializer serializer(...);
}
# Generated serializers ($$serializer classes).
-keep,includedescriptorclasses class is.waiwai.computer.**$$serializer { *; }
-keepclassmembers class is.waiwai.computer.** {
    *** Companion;
}
-keepclasseswithmembers class is.waiwai.computer.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# ---- Ktor ----
-keep class io.ktor.** { *; }
-keep class io.ktor.client.engine.android.** { *; }
-keepclassmembers class io.ktor.** { *; }
-dontwarn io.ktor.**

# ---- OkHttp + Okio ----
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# ---- SLF4J (Ktor logging depends on it but Android has no static binder) ----
-dontwarn org.slf4j.**

# ---- Sentry ----
-keep class io.sentry.** { *; }
-keep public class * extends io.sentry.android.core.SentryAndroidOptions
-dontwarn io.sentry.**

# ---- DataStore (Preferences) ----
-keep class androidx.datastore.preferences.protobuf.** { *; }

# ---- AndroidX WorkManager ----
-keepclassmembers class * extends androidx.work.Worker {
    public <init>(android.content.Context,androidx.work.WorkerParameters);
}
-keepclassmembers class * extends androidx.work.ListenableWorker {
    public <init>(android.content.Context,androidx.work.WorkerParameters);
}

# ---- Compose ----
# Compose ships its own consumer rules. Add safety net for tooling/state.
-keepclassmembers class androidx.compose.runtime.snapshots.SnapshotStateObserver$ApplyObserver { *; }
-dontwarn org.jetbrains.skia.**

# ---- Foreground services + receivers ----
-keep public class * extends android.app.Service
-keep public class * extends android.content.BroadcastReceiver
-keepclassmembers class * extends android.content.ContentProvider {
    <init>();
}

# ---- Reflection-only types used by our deep-link / intent handling ----
-keepattributes Signature,InnerClasses,EnclosingMethod,Exceptions,RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,AnnotationDefault

# ---- Stack traces ----
-keepattributes SourceFile,LineNumberTable
# Uncomment if/when we ship symbol-mapping uploads:
# -renamesourcefileattribute SourceFile
