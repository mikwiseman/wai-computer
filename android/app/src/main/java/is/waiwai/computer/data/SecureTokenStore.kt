package `is`.waiwai.computer.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureTokenStore(context: Context) {
    private val accessStore = SecureValueFileStore(
        context = context.applicationContext,
        keyAlias = "wai_android_access_token",
        fileName = "wai_access_token.secure",
    )
    private val refreshStore = SecureValueFileStore(
        context = context.applicationContext,
        keyAlias = "wai_android_refresh_token",
        fileName = "wai_refresh_token.secure",
    )

    fun readAccessToken(): String? = accessStore.read()

    fun writeAccessToken(token: String?) {
        accessStore.write(token)
    }

    fun readRefreshToken(): String? = refreshStore.read()

    fun writeRefreshToken(token: String?) {
        refreshStore.write(token)
    }

    fun clearAll() {
        accessStore.clear()
        refreshStore.clear()
    }
}

private class SecureValueFileStore(
    context: Context,
    private val keyAlias: String,
    fileName: String,
) {
    private val tokenFile = File(context.noBackupFilesDir, fileName)

    fun read(): String? {
        if (!tokenFile.exists()) return null

        val serializedPayload = tokenFile.readText(StandardCharsets.UTF_8)
        if (serializedPayload.isBlank()) {
            throw IllegalStateException("Stored token payload is blank.")
        }

        val payload = SecureTokenPayloadCodec.decode(serializedPayload)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            getOrCreateSecretKey(),
            GCMParameterSpec(GCM_TAG_LENGTH_BITS, payload.iv),
        )

        return cipher.doFinal(payload.ciphertext).toString(StandardCharsets.UTF_8)
    }

    fun write(token: String?) {
        val normalizedToken = token?.trim().orEmpty()
        if (normalizedToken.isEmpty()) {
            clear()
            return
        }

        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
        val ciphertext = cipher.doFinal(normalizedToken.toByteArray(StandardCharsets.UTF_8))
        val payload = SecureTokenPayload(iv = cipher.iv, ciphertext = ciphertext)

        tokenFile.parentFile?.mkdirs()
        tokenFile.writeText(
            SecureTokenPayloadCodec.encode(payload),
            StandardCharsets.UTF_8,
        )
    }

    fun clear() {
        if (tokenFile.exists() && !tokenFile.delete()) {
            throw IllegalStateException("Failed to delete stored token.")
        }
    }

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val existingKey = keyStore.getKey(keyAlias, null)
        if (existingKey is SecretKey) {
            return existingKey
        }

        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            ANDROID_KEYSTORE,
        )
        val keySpec = KeyGenParameterSpec.Builder(
            keyAlias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        keyGenerator.init(keySpec)
        return keyGenerator.generateKey()
    }

    private companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_TAG_LENGTH_BITS = 128
    }
}

internal data class SecureTokenPayload(
    val iv: ByteArray,
    val ciphertext: ByteArray,
)

internal object SecureTokenPayloadCodec {
    private const val PAYLOAD_VERSION = "v1"
    private const val PAYLOAD_DELIMITER = ":"

    private val encoder = Base64.getUrlEncoder().withoutPadding()
    private val decoder = Base64.getUrlDecoder()

    fun encode(payload: SecureTokenPayload): String {
        return listOf(
            PAYLOAD_VERSION,
            encoder.encodeToString(payload.iv),
            encoder.encodeToString(payload.ciphertext),
        ).joinToString(PAYLOAD_DELIMITER)
    }

    fun decode(serializedPayload: String): SecureTokenPayload {
        val parts = serializedPayload.split(PAYLOAD_DELIMITER)
        if (parts.size != 3 || parts.first() != PAYLOAD_VERSION) {
            throw IllegalStateException("Stored token payload format is invalid.")
        }

        return try {
            SecureTokenPayload(
                iv = decoder.decode(parts[1]),
                ciphertext = decoder.decode(parts[2]),
            )
        } catch (error: IllegalArgumentException) {
            throw IllegalStateException("Stored token payload is corrupted.", error)
        }
    }
}
