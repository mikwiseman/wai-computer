package `is`.waiwai.computer.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.recording.Phase
import `is`.waiwai.computer.ui.TestTags

@Composable
fun RecordButton(
    phase: Phase,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isBusy = phase == Phase.Preparing || phase == Phase.Finalizing
    val isRecording = phase == Phase.Recording
    Box(
        modifier = modifier
            .size(80.dp)
            .scale(if (isRecording) 0.95f else 1f)
            .background(Color(0xFFDC2626), CircleShape)
            .testTag(TestTags.RecordButton)
            .clickable(enabled = !isBusy, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        when {
            isBusy -> CircularProgressIndicator(color = Color.White)
            isRecording -> Icon(
                Icons.Default.Stop,
                contentDescription = stringResource(R.string.record_stop),
                tint = Color.White,
            )
            else -> Icon(
                Icons.Outlined.Mic,
                contentDescription = stringResource(R.string.record_start),
                tint = Color.White,
            )
        }
    }
}
