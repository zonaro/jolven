package com.redclaw.jolven_flutter

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream

class RomFingerprintTest {
    @Test
    fun knownDigest() {
        val result = RomFingerprint.digest(ByteArrayInputStream("abc".toByteArray()))
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            result.sha256
        )
        assertEquals(3L, result.size)
    }

    @Test
    fun refusesOversizedInput() {
        assertThrows(IllegalArgumentException::class.java) {
            RomFingerprint.digest(ByteArrayInputStream(ByteArray(11)), maxBytes = 10L)
        }
    }
}
