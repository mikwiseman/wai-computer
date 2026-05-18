package `is`.waiwai.computer.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val LightColors = lightColorScheme(
    primary = Color(0xFF2563EB),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE8FF),
    onPrimaryContainer = Color(0xFF0F172A),
    secondary = Color(0xFF0F172A),
    onSecondary = Color.White,
    tertiary = Color(0xFF059669),
    error = Color(0xFFDC2626),
    surface = Color(0xFFFCFCFD),
    onSurface = Color(0xFF0F172A),
    surfaceVariant = Color(0xFFF5F5F7),
    onSurfaceVariant = Color(0xFF475569),
    outline = Color(0xFFD4D4D8),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF60A5FA),
    onPrimary = Color(0xFF0F172A),
    primaryContainer = Color(0xFF1D4ED8),
    onPrimaryContainer = Color.White,
    secondary = Color(0xFFE2E8F0),
    onSecondary = Color(0xFF0F172A),
    tertiary = Color(0xFF34D399),
    error = Color(0xFFF87171),
    surface = Color(0xFF09090B),
    onSurface = Color(0xFFF8FAFC),
    surfaceVariant = Color(0xFF1C1C1E),
    onSurfaceVariant = Color(0xFFCBD5E1),
    outline = Color(0xFF3F3F46),
)

@Immutable
data class WaiSpacing(
    val xxs: Int = 2,
    val xs: Int = 4,
    val sm: Int = 8,
    val md: Int = 12,
    val lg: Int = 16,
    val xl: Int = 24,
    val xxl: Int = 32,
)

@Immutable
data class WaiRadius(
    val sm: Int = 8,
    val md: Int = 12,
    val lg: Int = 16,
    val xl: Int = 20,
)

@Immutable
data class WaiPalette(
    val recording: Color = Color(0xFFDC2626),
    val warning: Color = Color(0xFFF59E0B),
    val success: Color = Color(0xFF059669),
    val surfaceSubtleLight: Color = Color(0xFFF5F5F7),
    val surfaceSubtleDark: Color = Color(0xFF1C1C1E),
)

val LocalWaiSpacing = staticCompositionLocalOf { WaiSpacing() }
val LocalWaiRadius = staticCompositionLocalOf { WaiRadius() }
val LocalWaiPalette = staticCompositionLocalOf { WaiPalette() }

private val WaiTypography = Typography(
    displayLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 32.sp, lineHeight = 38.sp),
    displayMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 28.sp, lineHeight = 34.sp),
    displaySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 24.sp, lineHeight = 30.sp),
    headlineMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 20.sp, lineHeight = 26.sp),
    headlineSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 18.sp, lineHeight = 24.sp),
    bodyLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 12.sp, lineHeight = 16.sp),
)

private val WaiShapes = Shapes(
    small = androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
    medium = androidx.compose.foundation.shape.RoundedCornerShape(12.dp),
    large = androidx.compose.foundation.shape.RoundedCornerShape(16.dp),
    extraLarge = androidx.compose.foundation.shape.RoundedCornerShape(20.dp),
)

object WaiTheme {
    val spacing
        @Composable get() = LocalWaiSpacing.current

    val radius
        @Composable get() = LocalWaiRadius.current

    val palette
        @Composable get() = LocalWaiPalette.current
}

@Composable
fun WaiTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val colors: ColorScheme = when {
        // Material You dynamic colors on Android 12+ — opt-in only because
        // a strong Wai brand identity beats device-themed accents for an
        // app that should feel consistent across phones.
        dynamicColor && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S -> {
            if (darkTheme) {
                androidx.compose.material3.dynamicDarkColorScheme(context)
            } else {
                androidx.compose.material3.dynamicLightColorScheme(context)
            }
        }
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(
        colorScheme = colors,
        typography = WaiTypography,
        shapes = WaiShapes,
        content = content,
    )
}
