package `is`.waiwai.say.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.HourglassBottom
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Waves
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import `is`.waiwai.say.recording.Phase

@Composable
fun StatusRing(
    phase: Phase,
    modifier: Modifier = Modifier,
) {
    val transition = rememberInfiniteTransition(label = "pulse")
    val scale = transition.animateFloat(
        initialValue = 1f,
        targetValue = 1.12f,
        animationSpec = infiniteRepeatable(
            animation = tween(1_200),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "scale",
    )
    val alpha = transition.animateFloat(
        initialValue = 0.7f,
        targetValue = 0.3f,
        animationSpec = infiniteRepeatable(
            animation = tween(1_200),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "alpha",
    )
    val tint = when (phase) {
        Phase.Idle -> MaterialTheme.colorScheme.primaryContainer
        Phase.Preparing,
        Phase.Finalizing,
        -> Color(0xFFF59E0B)
        Phase.Recording -> Color(0xFFDC2626)
    }
    val icon = when (phase) {
        Phase.Idle -> Icons.Outlined.Mic
        Phase.Preparing,
        Phase.Finalizing,
        -> Icons.Outlined.HourglassBottom
        Phase.Recording -> Icons.Outlined.Waves
    }
    Box(
        modifier = modifier.size(220.dp),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(220.dp)
                .scale(if (phase == Phase.Recording) scale.value else 1f)
                .alpha(if (phase == Phase.Recording) alpha.value else 1f)
                .background(tint.copy(alpha = 0.18f), CircleShape),
        )
        Box(
            modifier = Modifier
                .size(180.dp)
                .background(tint.copy(alpha = 0.2f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tint)
        }
    }
}
