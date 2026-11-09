package com.redclaw.jolven_flutter.rompatcher

import java.nio.file.Files
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class RomPatchEngineTest {
    @Test fun appliesIpsToIndependentFile() {
        val original = Files.createTempFile("jolven-rom-", ".gba")
        val patch = Files.createTempFile("jolven-patch-", ".ips")
        val output = Files.createTempFile("jolven-output-", ".gba")
        try {
            val bytes = byteArrayOf(0, 0, 0, 0)
            Files.write(original, bytes)
            val ips = "PATCH".toByteArray() +
                byteArrayOf(0, 0, 1, 0, 1, 0x7f) +
                "EOF".toByteArray()
            Files.write(patch, ips)
            assertEquals(PatchFormat.IPS, RomPatchEngine.inspect(patch).format)
            RomPatchEngine.apply(original, patch, output)
            assertArrayEquals(bytes, Files.readAllBytes(original))
            assertArrayEquals(byteArrayOf(0, 0x7f, 0, 0), Files.readAllBytes(output))
        } finally {
            Files.deleteIfExists(original)
            Files.deleteIfExists(patch)
            Files.deleteIfExists(output)
        }
    }

    @Test fun rejectsUnsupportedPatchMagic() {
        val patch = Files.createTempFile("jolven-bad-", ".bin")
        try {
            Files.write(patch, "THIS IS NOT A PATCH".toByteArray())
            assertThrows(IllegalStateException::class.java) {
                RomPatchEngine.inspect(patch)
            }
        } finally {
            Files.deleteIfExists(patch)
        }
    }
}
