package `is`.waiwai.say.onboarding

import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import `is`.waiwai.say.R
import `is`.waiwai.say.ui.TestTags

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GuestModeInfoSheet(
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            text = stringResource(R.string.guest_info_title),
            style = MaterialTheme.typography.headlineSmall,
        )
        Text(
            text = stringResource(R.string.guest_info_body),
            style = MaterialTheme.typography.bodyLarge,
        )
        Button(
            onClick = onConfirm,
            modifier = Modifier.testTag(TestTags.GuestConfirmButton),
        ) {
            Text(stringResource(R.string.guest_info_confirm))
        }
        OutlinedButton(onClick = onDismiss) {
            Text(stringResource(R.string.guest_info_cancel))
        }
    }
}
