package `is`.waiwai.computer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.auth.AuthViewModel

enum class AuthFormMode {
    Login,
    Register,
}

@Composable
fun AuthFormScreen(
    mode: AuthFormMode,
    authViewModel: AuthViewModel,
    onBack: () -> Unit,
    onMagicLink: () -> Unit,
) {
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var confirmPassword by rememberSaveable { mutableStateOf("") }
    var showPassword by rememberSaveable { mutableStateOf(false) }

    val emailError = email.takeIf { it.isNotBlank() && !EMAIL_REGEX.matches(it) }
    val passwordError = password.takeIf { it.isNotBlank() && it.trim().length < 8 }
    val confirmError = if (mode == AuthFormMode.Register && confirmPassword.isNotBlank() && confirmPassword != password) {
        "Passwords do not match."
    } else {
        null
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        TextButton(onClick = onBack) {
            Text(stringResource(R.string.common_back))
        }
        Text(
            text = if (mode == AuthFormMode.Login) {
                stringResource(R.string.auth_sign_in)
            } else {
                stringResource(R.string.auth_create_account)
            },
            style = MaterialTheme.typography.headlineMedium,
        )
        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TestTags.AuthEmailField),
            label = { Text(stringResource(R.string.auth_email_label)) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            supportingText = {
                if (emailError != null) {
                    Text(stringResource(R.string.auth_invalid_email))
                }
            },
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TestTags.AuthPasswordField),
            label = { Text(stringResource(R.string.auth_password_label)) },
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            supportingText = {
                if (passwordError != null) {
                    Text(stringResource(R.string.auth_password_too_short))
                }
            },
        )
        if (mode == AuthFormMode.Register) {
            OutlinedTextField(
                value = confirmPassword,
                onValueChange = { confirmPassword = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.auth_confirm_password_label)) },
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                supportingText = {
                    if (confirmError != null) {
                        Text(stringResource(R.string.auth_password_mismatch))
                    }
                },
            )
        }
        TextButton(onClick = { showPassword = !showPassword }) {
            Text(
                if (showPassword) stringResource(R.string.auth_hide_password)
                else stringResource(R.string.auth_show_password),
            )
        }
        Button(
            enabled = emailError == null && passwordError == null && confirmError == null && email.isNotBlank() && password.isNotBlank(),
            onClick = {
                if (mode == AuthFormMode.Login) {
                    authViewModel.login(email, password)
                } else {
                    authViewModel.register(email, password)
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TestTags.AuthSubmitButton),
        ) {
            Text(
                if (mode == AuthFormMode.Login) {
                    stringResource(R.string.auth_sign_in)
                } else {
                    stringResource(R.string.auth_create_account)
                },
            )
        }
        TextButton(onClick = onMagicLink, modifier = Modifier.padding(top = 8.dp)) {
            Text(stringResource(R.string.auth_magic_link))
        }
    }
}

@Composable
fun MagicLinkScreen(
    authViewModel: AuthViewModel,
    onBack: () -> Unit,
) {
    var email by rememberSaveable { mutableStateOf("") }
    val emailError = email.takeIf { it.isNotBlank() && !EMAIL_REGEX.matches(it) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        TextButton(onClick = onBack) {
            Text(stringResource(R.string.common_back))
        }
        Text(
            text = stringResource(R.string.auth_magic_link_title),
            style = MaterialTheme.typography.headlineMedium,
        )
        Text(
            text = stringResource(R.string.auth_magic_link_body),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TestTags.AuthEmailField),
            label = { Text(stringResource(R.string.auth_email_label)) },
            supportingText = {
                if (emailError != null) {
                    Text(stringResource(R.string.auth_invalid_email))
                }
            },
        )
        Button(
            enabled = email.isNotBlank() && emailError == null,
            onClick = { authViewModel.requestMagicLink(email) },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TestTags.AuthSubmitButton),
        ) {
            Text(stringResource(R.string.auth_magic_link_title))
        }
    }
}

private val EMAIL_REGEX = Regex("^[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}$")
