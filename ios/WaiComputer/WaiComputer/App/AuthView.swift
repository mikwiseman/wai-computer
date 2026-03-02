import SwiftUI
import WaiComputerKit

struct AuthView: View {
    @EnvironmentObject var appState: AppState
    @State private var isLoginMode = true
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                // Logo and title
                VStack(spacing: 12) {
                    Image(systemName: "brain.head.profile")
                        .font(.system(size: 60))
                        .foregroundStyle(.blue)

                    Text("WaiComputer")
                        .font(.largeTitle)
                        .fontWeight(.bold)

                    Text("Your AI Second Brain")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 40)

                // Mode picker
                Picker("Mode", selection: $isLoginMode) {
                    Text("Login").tag(true)
                    Text("Register").tag(false)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                // Form
                VStack(spacing: 16) {
                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocapitalization(.none)
                        .textFieldStyle(.roundedBorder)

                    SecureField("Password", text: $password)
                        .textContentType(isLoginMode ? .password : .newPassword)
                        .textFieldStyle(.roundedBorder)

                    if !isLoginMode {
                        SecureField("Confirm Password", text: $confirmPassword)
                            .textContentType(.newPassword)
                            .textFieldStyle(.roundedBorder)
                    }
                }
                .padding(.horizontal)

                // Error message
                if let error = appState.error {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                // Submit button
                Button(action: submit) {
                    if appState.isLoading {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text(isLoginMode ? "Login" : "Create Account")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(.blue)
                .foregroundStyle(.white)
                .cornerRadius(12)
                .padding(.horizontal)
                .disabled(appState.isLoading || !isFormValid)

                Spacer()
            }
        }
    }

    private var isFormValid: Bool {
        let emailValid = email.contains("@") && email.contains(".")
        let passwordValid = password.count >= 6

        if isLoginMode {
            return emailValid && passwordValid
        } else {
            return emailValid && passwordValid && password == confirmPassword
        }
    }

    private func submit() {
        Task {
            if isLoginMode {
                await appState.login(email: email, password: password)
            } else {
                await appState.register(email: email, password: password)
            }
        }
    }
}

#Preview {
    AuthView()
        .environmentObject(AppState())
}
