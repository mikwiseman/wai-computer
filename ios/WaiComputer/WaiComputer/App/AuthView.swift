import SwiftUI
import WaiComputerKit

struct AuthView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager

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
            ScrollView {
                VStack(spacing: 32) {
                    header
                    modePicker

                    if authMode == .magicLink && appState.magicLinkSent {
                        magicLinkSentView
                    } else {
                        formView
                    }

                    if authMode == .login, appState.passwordResetSent {
                        Text(t(
                            "If this email is registered, we sent a password reset link.",
                            "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля."
                        ))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                        .accessibilityIdentifier("auth-password-reset-sent-text")
                    }

                    if let error = appState.error {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding(.horizontal)
                            .accessibilityIdentifier("auth-error-text")
                    }

                    submitButton
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 40)
            }
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

    private var header: some View {
        VStack(spacing: 12) {
            Image(systemName: "brain.head.profile")
                .font(.system(size: 60))
                .foregroundStyle(.blue)

            Text("WaiComputer")
                .font(.largeTitle)
                .fontWeight(.bold)

            Text(t("Your AI Second Brain", "Твой второй мозг"))
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    private var modePicker: some View {
        Picker("Mode", selection: $authMode) {
            Text(t("Login", "Вход")).tag(AuthMode.login)
            Text(t("Register", "Регистрация")).tag(AuthMode.register)
            Text(t("Magic Link", "Ссылка на email")).tag(AuthMode.magicLink)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal)
        .accessibilityIdentifier("auth-mode-picker")
    }

    @ViewBuilder
    private var formView: some View {
        VStack(spacing: 16) {
            TextField(t("Email", "Email"), text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("auth-email-field")

            if authMode != .magicLink {
                SecureField(t("Password", "Пароль"), text: $password)
                    .textContentType(authMode == .login ? .password : .newPassword)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("auth-password-field")

                if authMode == .register {
                    SecureField(t("Confirm Password", "Повтори пароль"), text: $confirmPassword)
                        .textContentType(.newPassword)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("auth-confirm-password-field")

                    fieldHint(
                        t("At least \(Self.minPasswordLength) characters",
                          "Минимум \(Self.minPasswordLength) символов"),
                        isError: !password.isEmpty && password.count < Self.minPasswordLength
                    )
                    if !confirmPassword.isEmpty && confirmPassword != password {
                        fieldHint(t("Passwords don't match", "Пароли не совпадают"), isError: true)
                            .accessibilityIdentifier("auth-password-mismatch")
                    }

                    legalConsentRow
                }

                if authMode == .login {
                    Button(t("Forgot password?", "Забыли пароль?")) {
                        Task { await appState.requestPasswordReset(email: email, locale: authLocale) }
                    }
                    .font(.callout)
                    .disabled(!emailLooksValid || appState.isLoading)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("auth-forgot-password-button")
                }
            }

            // New users completing a magic-link signup must accept the legal
            // terms too — the backend enforces it, so surface the consent here.
            if authMode == .magicLink {
                legalConsentRow
            }
        }
        .padding(.horizontal)
    }

    private func fieldHint(_ text: String, isError: Bool) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(isError ? .red : .secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var legalConsentRow: some View {
        Toggle(isOn: $acceptedLegalTerms) {
            VStack(alignment: .leading, spacing: 4) {
                Text(t("I agree to WaiComputer's Terms and Privacy Policy.",
                       "Я принимаю Условия и Политику конфиденциальности WaiComputer."))
                HStack(spacing: 8) {
                    Link(t("Terms", "Условия"), destination: termsOfServiceURL)
                    Text("·")
                    Link(t("Privacy", "Конфиденциальность"), destination: privacyPolicyURL)
                }
                .font(.caption)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .toggleStyle(.switch)
        .accessibilityIdentifier("auth-legal-consent-toggle")
    }

    private var magicLinkSentView: some View {
        VStack(spacing: 16) {
            Image(systemName: "envelope.badge")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)

            Text(t("Check your email", "Проверь email"))
                .font(.title2)
                .fontWeight(.semibold)

            Text(String(format: t("We sent a sign-in link to %@", "Мы отправили ссылку для входа на %@"), email))
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button(t("Send again", "Отправить ещё раз")) {
                appState.magicLinkSent = false
            }
            .font(.callout)
        }
        .padding(.horizontal)
    }

    private var submitButton: some View {
        Button(action: submit) {
            if appState.isLoading {
                ProgressView().tint(.white)
            } else {
                Text(buttonTitle)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(.blue)
        .foregroundStyle(.white)
        .cornerRadius(12)
        .padding(.horizontal)
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

#Preview {
    AuthView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
}
