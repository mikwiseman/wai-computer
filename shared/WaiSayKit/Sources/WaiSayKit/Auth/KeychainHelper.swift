import Foundation
import Security
import LocalAuthentication

/// Simple Keychain wrapper for storing authentication tokens securely.
public enum KeychainHelper {
    private static let service = "com.waisay.auth"

    /// Save a string value to the Keychain.
    @discardableResult
    public static func save(key: String, value: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }

        delete(key: key)

        var addQuery = baseQuery(for: key, useDataProtectionKeychain: true)
        addQuery.merge([
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]) { _, new in new }

        return SecItemAdd(addQuery as CFDictionary, nil) == errSecSuccess
    }

    /// Load a string value from the Keychain without presenting system UI.
    public static func load(key: String) -> String? {
        if let value = load(key: key, useDataProtectionKeychain: true) {
            return value
        }

        guard let legacyValue = load(key: key, useDataProtectionKeychain: false) else {
            return nil
        }

        save(key: key, value: legacyValue)
        return legacyValue
    }

    private static func load(key: String, useDataProtectionKeychain: Bool) -> String? {
        let context = LAContext()
        context.interactionNotAllowed = true

        var query = baseQuery(for: key, useDataProtectionKeychain: useDataProtectionKeychain)
        query.merge([
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseAuthenticationContext as String: context,
            kSecUseAuthenticationUI as String: kSecUseAuthenticationUISkip,
        ]) { _, new in new }

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess, let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    /// Delete a value from the Keychain.
    @discardableResult
    public static func delete(key: String) -> Bool {
        let statuses = [
            delete(key: key, useDataProtectionKeychain: true),
            delete(key: key, useDataProtectionKeychain: false),
        ]
        return statuses.allSatisfy { $0 == errSecSuccess || $0 == errSecItemNotFound }
    }

    private static func delete(key: String, useDataProtectionKeychain: Bool) -> OSStatus {
        var query = baseQuery(for: key, useDataProtectionKeychain: useDataProtectionKeychain)
        query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUISkip
        return SecItemDelete(query as CFDictionary)
    }

    private static func baseQuery(for key: String, useDataProtectionKeychain: Bool) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        if useDataProtectionKeychain {
            query[kSecUseDataProtectionKeychain as String] = true
        }
        return query
    }

    // MARK: - Convenience keys

    public static let accessTokenKey = "wai_access_token"
    public static let refreshTokenKey = "wai_refresh_token"
}
