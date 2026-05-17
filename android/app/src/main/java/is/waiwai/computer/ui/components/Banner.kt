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
    val background = when (variant) {
        BannerVariant.Warning -> Color(0xFFFFF4D6)
        BannerVariant.Error -> Color(0xFFFDE8E8)
        BannerVariant.Info -> MaterialTheme.colorScheme.primaryContainer
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(background, RoundedCornerShape(16.dp))
            .padding(16.dp),
    ) {
        Text(text = title, fontWeight = FontWeight.SemiBold)
        if (!body.isNullOrBlank()) {
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}
