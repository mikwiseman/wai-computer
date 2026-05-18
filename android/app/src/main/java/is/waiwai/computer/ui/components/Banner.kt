package `is`.waiwai.computer.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

enum class BannerVariant {
    Warning,
    Error,
    Info,
}

@Composable
fun BannerCard(
    title: String,
    body: String?,
    variant: BannerVariant,
) {
    val isDark = MaterialTheme.colorScheme.surface.luminance() < 0.5f
    val background = when (variant) {
        BannerVariant.Warning -> if (isDark) Color(0xFF3F2D00) else Color(0xFFFFF4D6)
        BannerVariant.Error -> if (isDark) Color(0xFF3F1414) else Color(0xFFFDE8E8)
        BannerVariant.Info -> MaterialTheme.colorScheme.primaryContainer
    }
    val titleColor = when (variant) {
        BannerVariant.Warning -> if (isDark) Color(0xFFFFE6A8) else Color(0xFF7A5500)
        BannerVariant.Error -> if (isDark) Color(0xFFFFC1C1) else Color(0xFFB91C1C)
        BannerVariant.Info -> MaterialTheme.colorScheme.onPrimaryContainer
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(background, RoundedCornerShape(16.dp))
            .padding(16.dp),
    ) {
        Text(text = title, fontWeight = FontWeight.SemiBold, color = titleColor)
        if (!body.isNullOrBlank()) {
            Text(
                text = body,
                color = titleColor.copy(alpha = 0.8f),
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

private fun Color.luminance(): Float =
    0.2126f * red + 0.7152f * green + 0.0722f * blue
