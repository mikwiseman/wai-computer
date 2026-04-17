package `is`.waiwai.say.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import `is`.waiwai.say.R
import `is`.waiwai.say.auth.AuthState
import `is`.waiwai.say.auth.AuthViewModel
import `is`.waiwai.say.data.AppContainer
import `is`.waiwai.say.library.LibraryScreen
import `is`.waiwai.say.library.RecordingDetailScreen
import `is`.waiwai.say.library.RecordingDetailViewModel
import `is`.waiwai.say.onboarding.GuestModeInfoSheet
import `is`.waiwai.say.onboarding.OnboardingAuthChoice
import `is`.waiwai.say.onboarding.OnboardingCarousel
import `is`.waiwai.say.qa.WaiScreen
import `is`.waiwai.say.recording.RecordingScreen
import `is`.waiwai.say.recording.RecordingViewModel
import `is`.waiwai.say.settings.SettingsScreen
import `is`.waiwai.say.ui.components.BannerCard
import `is`.waiwai.say.ui.components.BannerVariant

private enum class AuthFlowScreen {
    Carousel,
    Choice,
    Login,
    Register,
    MagicLink,
}

private enum class MainTab {
    Record,
    Library,
    Wai,
    Settings,
}

@Composable
fun WaiAndroidApp(
    container: AppContainer,
    pendingMagicLinkToken: String?,
    onMagicLinkConsumed: () -> Unit,
    recordingViewModel: RecordingViewModel? = null,
) {
    val authState by container.authStore.state.collectAsStateWithLifecycle()
    val settings by container.settingsStore.settings.collectAsStateWithLifecycle(
        initialValue = `is`.waiwai.say.data.AppSettings(
            baseUrl = `is`.waiwai.say.BuildConfig.DEFAULT_BASE_URL,
            transcriptionLanguage = `is`.waiwai.say.data.SettingsStore.DEFAULT_TRANSCRIPTION_LANGUAGE,
            authMode = `is`.waiwai.say.data.StoredAuthMode.Onboarding,
            authUserId = null,
            onboardingSeen = false,
            guestSinceEpochMillis = null,
            legacyAccessToken = null,
        ),
    )
    val authViewModel = remember { AuthViewModel(container.authStore) }
    val authUiState by authViewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    var previousAuthState by remember { mutableStateOf<AuthState>(AuthState.Unknown) }
    val guestMigrationMessage = stringResource(R.string.auth_migrating_guest_recordings)
    val magicLinkSentMessage = authUiState.magicLinkSentTo?.let { email ->
        stringResource(R.string.auth_magic_link_sent_to, email)
    }

    var authFlowScreen by rememberSaveable {
        mutableStateOf(if (settings.onboardingSeen) AuthFlowScreen.Choice else AuthFlowScreen.Carousel)
    }
    var showGuestInfo by rememberSaveable { mutableStateOf(false) }
    var selectedTab by rememberSaveable { mutableStateOf(MainTab.Record) }
    var showAuthOverlay by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(authState) {
        when (authState) {
            AuthState.Onboarding -> {
                authFlowScreen = if (settings.onboardingSeen) AuthFlowScreen.Choice else AuthFlowScreen.Carousel
                showAuthOverlay = false
            }
            is AuthState.SessionExpired -> {
                authFlowScreen = AuthFlowScreen.Choice
                showAuthOverlay = false
            }
            is AuthState.Authenticated -> {
                if (previousAuthState is AuthState.Guest) {
                    val pendingGuestRecordings = container.localRecordingStore.listPending()
                        .count { it.requiresAuthentication || it.localOnly }
                    if (pendingGuestRecordings > 0) {
                        container.enqueuePendingSync()
                        snackbarHostState.showSnackbar(guestMigrationMessage)
                    }
                }
                showAuthOverlay = false
            }
            is AuthState.Guest,
            AuthState.Unknown,
            -> Unit
        }
        previousAuthState = authState
    }

    LaunchedEffect(pendingMagicLinkToken) {
        val token = pendingMagicLinkToken ?: return@LaunchedEffect
        authViewModel.verifyMagicLink(token)
        onMagicLinkConsumed()
    }

    if (authUiState.globalError != null) {
        LaunchedEffect(authUiState.globalError) {
            snackbarHostState.showSnackbar(authUiState.globalError.orEmpty())
            authViewModel.clearError()
        }
    }

    if (magicLinkSentMessage != null) {
        LaunchedEffect(magicLinkSentMessage) {
            snackbarHostState.showSnackbar(magicLinkSentMessage)
            authViewModel.consumeMagicLinkSent()
        }
    }

    when (val state = authState) {
        AuthState.Unknown -> AppLoadingScreen()
        is AuthState.Authenticated,
        is AuthState.Guest,
        -> {
            MainTabsScaffold(
                selectedTab = selectedTab,
                onTabSelected = { selectedTab = it },
                isGuest = state is AuthState.Guest,
                container = container,
                authViewModel = authViewModel,
                snackbarHostState = snackbarHostState,
                recordingViewModel = recordingViewModel,
                onRequestAuth = {
                    showAuthOverlay = true
                    authFlowScreen = AuthFlowScreen.Choice
                },
            )
            if (state is AuthState.Guest && showAuthOverlay) {
                AuthFlowSheet(
                    authFlowScreen = authFlowScreen,
                    authViewModel = authViewModel,
                    showGuestInfo = showGuestInfo,
                    onDismiss = { showAuthOverlay = false },
                    onFlowScreenChange = { authFlowScreen = it },
                    onGuestInfoChange = { showGuestInfo = it },
                )
            }
        }
        AuthState.Onboarding,
        is AuthState.SessionExpired,
        -> AuthFlowSheet(
            authFlowScreen = authFlowScreen,
            authViewModel = authViewModel,
            showGuestInfo = showGuestInfo,
            onDismiss = null,
            onFlowScreenChange = { authFlowScreen = it },
            onGuestInfoChange = { showGuestInfo = it },
            showSessionExpiredBanner = state is AuthState.SessionExpired,
        )
    }
}

@Composable
private fun MainTabsScaffold(
    selectedTab: MainTab,
    onTabSelected: (MainTab) -> Unit,
    isGuest: Boolean,
    container: AppContainer,
    authViewModel: AuthViewModel,
    snackbarHostState: SnackbarHostState,
    recordingViewModel: RecordingViewModel?,
    onRequestAuth: () -> Unit,
) {
    var selectedRecordingId by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedRecordingLocalOnly by rememberSaveable { mutableStateOf(false) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (selectedRecordingId == null) {
                BottomAppBar {
                    MainTab.entries.forEach { tab ->
                        val label = when (tab) {
                            MainTab.Record -> stringResource(R.string.tab_record)
                            MainTab.Library -> stringResource(R.string.tab_library)
                            MainTab.Wai -> stringResource(R.string.tab_wai)
                            MainTab.Settings -> stringResource(R.string.tab_settings)
                        }
                        val icon = when (tab) {
                            MainTab.Record -> Icons.Outlined.Mic
                            MainTab.Library -> Icons.Outlined.Folder
                            MainTab.Wai -> Icons.Outlined.AutoAwesome
                            MainTab.Settings -> Icons.Outlined.Settings
                        }
                        NavigationBarItem(
                            selected = selectedTab == tab,
                            onClick = { onTabSelected(tab) },
                            icon = { Icon(icon, contentDescription = label) },
                            label = { Text(label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        if (selectedRecordingId != null) {
            val detailViewModel = remember(selectedRecordingId, selectedRecordingLocalOnly) {
                RecordingDetailViewModel(
                    waiApi = container.waiApi,
                    localRecordingStore = container.localRecordingStore,
                    recordingId = requireNotNull(selectedRecordingId),
                    localOnly = selectedRecordingLocalOnly,
                )
            }
            RecordingDetailScreen(
                modifier = Modifier.padding(padding),
                viewModel = detailViewModel,
                isGuest = isGuest,
                onBack = {
                    selectedRecordingId = null
                    selectedRecordingLocalOnly = false
                },
                onRequestSignIn = onRequestAuth,
            )
            return@Scaffold
        }
        when (selectedTab) {
            MainTab.Record -> RecordingScreen(
                modifier = Modifier.padding(padding),
                container = container,
                isGuest = isGuest,
                viewModel = recordingViewModel,
            )
            MainTab.Library -> LibraryScreen(
                modifier = Modifier.padding(padding),
                container = container,
                isGuest = isGuest,
                onSwitchToRecord = { onTabSelected(MainTab.Record) },
                onOpenRecording = { recordingId, localOnly ->
                    selectedRecordingId = recordingId
                    selectedRecordingLocalOnly = localOnly
                },
            )
            MainTab.Wai -> WaiScreen(
                modifier = Modifier.padding(padding),
                container = container,
                isGuest = isGuest,
                onOpenRecording = { recordingId ->
                    selectedRecordingId = recordingId
                    selectedRecordingLocalOnly = false
                },
            )
            MainTab.Settings -> SettingsScreen(
                modifier = Modifier.padding(padding),
                container = container,
                isGuest = isGuest,
                onContinueSignIn = onRequestAuth,
                authViewModel = authViewModel,
            )
        }
    }
}

@Composable
private fun AuthFlowSheet(
    authFlowScreen: AuthFlowScreen,
    authViewModel: AuthViewModel,
    showGuestInfo: Boolean,
    onDismiss: (() -> Unit)?,
    onFlowScreenChange: (AuthFlowScreen) -> Unit,
    onGuestInfoChange: (Boolean) -> Unit,
    showSessionExpiredBanner: Boolean = false,
) {
    Scaffold(
        snackbarHost = {},
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (showSessionExpiredBanner) {
                BannerCard(
                    title = stringResource(R.string.session_expired),
                    body = null,
                    variant = BannerVariant.Warning,
                )
            }
            when (authFlowScreen) {
                AuthFlowScreen.Carousel -> OnboardingCarousel(
                    onFinished = { onFlowScreenChange(AuthFlowScreen.Choice) },
                )
                AuthFlowScreen.Choice -> OnboardingAuthChoice(
                    onSignIn = { onFlowScreenChange(AuthFlowScreen.Login) },
                    onCreateAccount = { onFlowScreenChange(AuthFlowScreen.Register) },
                    onTryGuest = { onGuestInfoChange(true) },
                )
                AuthFlowScreen.Login -> AuthFormScreen(
                    mode = AuthFormMode.Login,
                    authViewModel = authViewModel,
                    onBack = { onFlowScreenChange(AuthFlowScreen.Choice) },
                    onMagicLink = { onFlowScreenChange(AuthFlowScreen.MagicLink) },
                )
                AuthFlowScreen.Register -> AuthFormScreen(
                    mode = AuthFormMode.Register,
                    authViewModel = authViewModel,
                    onBack = { onFlowScreenChange(AuthFlowScreen.Choice) },
                    onMagicLink = { onFlowScreenChange(AuthFlowScreen.MagicLink) },
                )
                AuthFlowScreen.MagicLink -> MagicLinkScreen(
                    authViewModel = authViewModel,
                    onBack = { onFlowScreenChange(AuthFlowScreen.Choice) },
                )
            }
        }
        if (showGuestInfo) {
            GuestModeInfoSheet(
                onDismiss = { onGuestInfoChange(false) },
                onConfirm = {
                    onGuestInfoChange(false)
                    authViewModel.continueAsGuest()
                    onDismiss?.invoke()
                },
            )
        }
    }
}

@Composable
private fun AppLoadingScreen() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.record_preparing),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
