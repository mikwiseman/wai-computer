package `is`.waiwai.computer.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SecureTokenPayloadCodecTest {
    @Test
    fun `encode and decode preserve iv and ciphertext`() {
        val payload = SecureTokenPayload(
            iv = byteArrayOf(1, 2, 3, 4),
            ciphertext = byteArrayOf(9, 8, 7, 6),
        )

        val encoded = SecureTokenPayloadCodec.encode(payload)
        val decoded = SecureTokenPayloadCodec.decode(encoded)

        assertTrue(encoded.startsWith("v1:"))
        assertArrayEquals(payload.iv, decoded.iv)
        assertArrayEquals(payload.ciphertext, decoded.ciphertext)
    }

    @Test(expected = IllegalStateException::class)
    fun `decode rejects malformed payload`() {
        SecureTokenPayloadCodec.decode("broken-payload")
    }
}
