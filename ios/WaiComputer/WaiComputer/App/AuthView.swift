import SwiftUI
import WaiComputerKit

struct AuthView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    enum AuthMode: String, CaseIterable, Hashable {
        case login, register, magicLink
    }

    @State private var authMode: AuthMode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var acceptedLegalTerms = false

    // Keep in sync with the backend minimum (RegisterRequest, auth.py).
    private static let minPasswordLength = 8

    var body: some View {
        NavigationStack {
            authContent
            .background(Color(uiColor: .systemBackground).ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: authMode) { _, _ in
                appState.magicLinkSent = false
                appState.passwordResetSent = false
                appState.error = nil
                acceptedLegalTerms = false
            }
            .onChange(of: email) { _, _ in
                appState.passwordResetSent = false
            }
        }
    }

    @ViewBuilder
    private var authContent: some View {
        if horizontalSizeClass == .regular {
            regularAuthLayout
        } else {
            compactAuthLayout
        }
    }

    private var compactAuthLayout: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                compactHeader
                modePicker(maxWidth: nil)
                authFlow(maxWidth: nil)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.xxxl)
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("auth-compact-layout")
    }

    private var regularAuthLayout: some View {
        GeometryReader { proxy in
            ScrollView {
                HStack(alignment: .center, spacing: Spacing.huge) {
                    regularBrandPanel
                    regularFormPanel
                }
                .frame(maxWidth: 960)
                .frame(minHeight: proxy.size.height)
                .padding(.horizontal, Spacing.huge)
                .padding(.vertical, Spacing.xxxl)
                .frame(maxWidth: .infinity)
            }
        }
        .accessibilityIdentifier("auth-regular-layout")
    }

    private var compactHeader: some View {
        VStack(spacing: Spacing.md) {
            WaiTriangleIcon(size: 64)
                .accessibilityHidden(true)

            VStack(spacing: Spacing.xs) {
                Text("WaiComputer")
                    .font(Typography.displayLarge)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.84)

                Text(t("YOUR SECOND BRAIN", "ТВОЙ ВТОРОЙ МОЗГ"))
                    .waiSectionHeader()
            }
        }
    }

    private var regularBrandPanel: some View {
        VStack(alignment: .leading, spacing: Spacing.xl) {
            WaiTriangleIcon(size: 64)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.sm) {
                Text("WaiComputer")
                    .font(Typography.displayLarge)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.84)

                Text(t("YOUR SECOND BRAIN", "ТВОЙ ВТОРОЙ МОЗГ"))
                    .waiSectionHeader()
            }

            Divider()
        }
        .frame(maxWidth: 360, alignment: .leading)
        .accessibilityIdentifier("auth-regular-brand-panel")
    }

    private var regularFormPanel: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(authPanelTitle)
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)

                Text(authPanelSubtitle)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            modePicker(maxWidth: .infinity)
            authFlow(maxWidth: .infinity)
        }
        .padding(Spacing.xl)
        .frame(width: 408)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier("auth-regular-form-panel")
    }

    private func modePicker(maxWidth: CGFloat?) -> some View {
        Picker("Mode", selection: $authMode) {
            Text(t("Login", "Вход")).tag(AuthMode.login)
            Text(t("Register", "Регистрация")).tag(AuthMode.register)
            Text(t("Magic Link", "Ссылка на email")).tag(AuthMode.magicLink)
        }
        .pickerStyle(.segmented)
        .frame(maxWidth: maxWidth)
        .accessibilityIdentifier("auth-mode-picker")
    }

    @ViewBuilder
    private func authFlow(maxWidth: CGFloat?) -> some View {
        if authMode == .magicLink && appState.magicLinkSent {
            magicLinkSentView(maxWidth: maxWidth)
        } else {
            formView(maxWidth: maxWidth)
        }

        statusMessages(maxWidth: maxWidth)
        submitButton(maxWidth: maxWidth)
    }

    @ViewBuilder
    private func formView(maxWidth: CGFloat?) -> some View {
        VStack(spacing: Spacing.md) {
            TextField(t("Email", "Email"), text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.plain)
                .authFieldChrome(maxWidth: maxWidth)
                .accessibilityIdentifier("auth-email-field")

            if authMode != .magicLink {
                SecureField(t("Password", "Пароль"), text: $password)
                    .textContentType(authMode == .login ? .password : .newPassword)
                    .textFieldStyle(.plain)
                    .authFieldChrome(maxWidth: maxWidth)
                    .accessibilityIdentifier("auth-password-field")

                if authMode == .register {
                    SecureField(t("Confirm Password", "Повтори пароль"), text: $confirmPassword)
                        .textContentType(.newPassword)
                        .textFieldStyle(.plain)
                        .authFieldChrome(maxWidth: maxWidth)
                        .accessibilityIdentifier("auth-confirm-password-field")

                    fieldHint(
                        t("At least \(Self.minPasswordLength) characters",
                          "Минимум \(Self.minPasswordLength) символов"),
                        isError: !password.isEmpty && password.count < Self.minPasswordLength,
                        maxWidth: maxWidth
                    )
                    if !confirmPassword.isEmpty && confirmPassword != password {
                        fieldHint(
                            t("Passwords don't match", "Пароли не совпадают"),
                            isError: true,
                            maxWidth: maxWidth
                        )
                            .accessibilityIdentifier("auth-password-mismatch")
                    }

                    legalConsentRow(maxWidth: maxWidth)
                }

                if authMode == .login {
                    Button(t("Forgot password?", "Забыли пароль?")) {
                        Task { await appState.requestPasswordReset(email: email, locale: authLocale) }
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                    .disabled(!emailLooksValid || appState.isLoading)
                    .frame(maxWidth: maxWidth ?? .infinity, alignment: .leading)
                    .accessibilityIdentifier("auth-forgot-password-button")
                }
            }

            // New users completing a magic-link signup must accept the legal
            // terms too — the backend enforces it, so surface the consent here.
            if authMode == .magicLink {
                legalConsentRow(maxWidth: maxWidth)
            }
        }
        .frame(maxWidth: maxWidth)
    }

    private func fieldHint(_ text: String, isError: Bool, maxWidth: CGFloat?) -> some View {
        Text(text)
            .font(Typography.caption)
            .foregroundStyle(isError ? Palette.recording : Palette.textSecondary)
            .frame(maxWidth: maxWidth ?? .infinity, alignment: .leading)
    }

    private func legalConsentRow(maxWidth: CGFloat?) -> some View {
        Toggle(isOn: $acceptedLegalTerms) {
            VStack(alignment: .leading, spacing: 4) {
                Text(t("I agree to WaiComputer's Terms and Privacy Policy.",
                       "Я принимаю Условия и Политику конфиденциальности WaiComputer."))
                HStack(spacing: 8) {
                    Link(t("Terms", "Условия"), destination: termsOfServiceURL)
                    Text("·")
                    Link(t("Privacy", "Конфиденциальность"), destination: privacyPolicyURL)
                }
                .font(Typography.caption)
            }
            .font(Typography.caption)
            .foregroundStyle(Palette.textSecondary)
        }
        .toggleStyle(.switch)
        .frame(maxWidth: maxWidth ?? .infinity, alignment: .leading)
        .accessibilityIdentifier("auth-legal-consent-toggle")
    }

    private func magicLinkSentView(maxWidth: CGFloat?) -> some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "envelope.badge")
                .font(.system(size: 48))
                .foregroundStyle(Palette.textSecondary)

            Text(t("Check your email", "Проверь email"))
                .font(Typography.displaySmall)
                .foregroundStyle(Palette.textPrimary)

            Text(String(format: t("We sent a sign-in link to %@", "Мы отправили ссылку для входа на %@"), email))
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            Button(t("Send again", "Отправить ещё раз")) {
                appState.magicLinkSent = false
            }
            .buttonStyle(WaiGhostButtonStyle())
        }
        .frame(maxWidth: maxWidth ?? .infinity)
    }

    @ViewBuilder
    private func statusMessages(maxWidth: CGFloat?) -> some View {
        if authMode == .login, appState.passwordResetSent {
            Text(t(
                "If this email is registered, we sent a password reset link.",
                "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля."
            ))
            .font(Typography.caption)
            .foregroundStyle(Palette.textSecondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: maxWidth ?? .infinity)
            .accessibilityIdentifier("auth-password-reset-sent-text")
        }

        if let error = appState.error {
            Text(error)
                .font(Typography.caption)
                .foregroundStyle(Palette.recording)
                .frame(maxWidth: maxWidth ?? .infinity)
                .accessibilityIdentifier("auth-error-text")
        }
    }

    private func submitButton(maxWidth: CGFloat?) -> some View {
        Button(action: submit) {
            Group {
                if appState.isLoading {
                    ProgressView().tint(.white)
                } else {
                    Text(buttonTitle)
                        .lineLimit(1)
                        .minimumScaleFactor(0.84)
                }
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(WaiPrimaryButtonStyle(isDisabled: appState.isLoading || !isFormValid))
        .frame(maxWidth: maxWidth ?? .infinity)
        .disabled(appState.isLoading || !isFormValid)
        .accessibilityIdentifier("auth-submit-button")
    }

    private var buttonTitle: String {
        switch authMode {
        case .login: return t("Login", "Войти")
        case .register: return t("Create Account", "Создать аккаунт")
        case .magicLink: return t("Send Magic Link", "Отправить ссылку")
        }
    }

    private var authPanelTitle: String {
        switch authMode {
        case .login: return t("Welcome back", "С возвращением")
        case .register: return t("Create your account", "Создай аккаунт")
        case .magicLink: return t("Email sign-in", "Вход по email")
        }
    }

    private var authPanelSubtitle: String {
        switch authMode {
        case .login:
            return t("Sign in to sync recordings, notes, and recall.", "Войди, чтобы синхронизировать записи, заметки и поиск.")
        case .register:
            return t("Start a private second brain on wai.computer.", "Запусти личный второй мозг на wai.computer.")
        case .magicLink:
            return t("Get a secure link instead of typing a password.", "Получи безопасную ссылку вместо пароля.")
        }
    }

    private var emailLooksValid: Bool {
        email.contains("@") && email.contains(".")
    }

    private var isFormValid: Bool {
        if authMode == .magicLink && appState.magicLinkSent { return false }
        switch authMode {
        case .login:
            return emailLooksValid && !password.isEmpty
        case .register:
            return emailLooksValid
                && password.count >= Self.minPasswordLength
                && password == confirmPassword
                && acceptedLegalTerms
        case .magicLink:
            return emailLooksValid && acceptedLegalTerms
        }
    }

    private var authLocale: String {
        languageManager.preferredLocale.language.languageCode?.identifier == "ru" ? "ru" : "en"
    }

    private var termsOfServiceURL: URL {
        URL(string: authLocale == "ru" ? "https://wai.computer/ru/terms" : "https://wai.computer/terms")!
    }

    private var privacyPolicyURL: URL {
        URL(string: authLocale == "ru" ? "https://wai.computer/ru/privacy" : "https://wai.computer/privacy")!
    }

    private func submit() {
        Task {
            switch authMode {
            case .login:
                await appState.login(email: email, password: password)
            case .register:
                await appState.register(email: email, password: password, acceptedLegalTerms: acceptedLegalTerms)
            case .magicLink:
                await appState.requestMagicLink(email: email, acceptedLegalTerms: acceptedLegalTerms)
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private extension View {
    func authFieldChrome(maxWidth: CGFloat?) -> some View {
        self
            .font(Typography.body)
            .foregroundStyle(Palette.textPrimary)
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.md)
            .background(Color(uiColor: .secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Palette.border, lineWidth: 1)
            )
            .frame(maxWidth: maxWidth ?? .infinity)
    }
}

#Preview {
    AuthView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
}
